"""Bounded in-process jobs and safe access to their derived artifacts."""
from __future__ import annotations

import asyncio
import json
import re
import secrets
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from .analyzer import cache_valid, sha256

Worker = Callable[[Path], Awaitable[None]]


@dataclass
class _Record:
    key: str
    directory: Path
    state: str = 'queued'
    task: asyncio.Task | None = None
    error_category: str | None = None


class JobManager:
    def __init__(self, root: Path, *, limit: int = 2, max_active: int = 32, max_history: int = 256):
        if not 1 <= limit <= 4 or not limit <= max_active <= 32 or not max_active <= max_history <= 256:
            raise ValueError('Invalid job concurrency')
        self.root = Path(root).resolve()
        self._records: dict[str, _Record] = {}
        self._lock = asyncio.Lock()
        self._slots = asyncio.Semaphore(limit)
        self._max_active = max_active
        self._max_history = max_history
        self._loaded = False
        self._load_lock = threading.Lock()

    def _recover(self) -> None:
        if self._loaded:
            return
        with self._load_lock:
            if self._loaded:
                return
            if self.root.is_dir():
                candidates = []
                for path in self.root.iterdir():
                    try:
                        if (not path.is_symlink() and path.is_dir() and re.fullmatch(r'[0-9a-f]{32}', path.name)
                                and (path / '.job.json').is_file() and not (path / '.job.json').is_symlink()):
                            candidates.append(((path / '.job.json').stat().st_mtime_ns, path))
                    except OSError:
                        continue
                for _, path in sorted(candidates, key=lambda item: item[0])[-self._max_history:]:
                    try:
                        meta = path / '.job.json'
                        if meta.stat().st_size > 4096:
                            continue
                        data = json.loads(meta.read_text(encoding='utf-8'))
                        key = data.get('key') if isinstance(data, dict) else None
                        if isinstance(data, dict) and data.get('version') == 1 and data.get('state') == 'completed' and isinstance(key, str) and 0 < len(key) <= 512:
                            self._records[path.name] = _Record(key=key, directory=path, state='completed')
                    except (OSError, ValueError, TypeError):
                        continue
            self._loaded = True

    @staticmethod
    def _verified_cache(record: _Record) -> bool:
        try:
            url, count, language = record.key.rsplit('|', 2)
            frame_count = int(count)
            if not 1 <= frame_count <= 24:
                return False
            source = record.directory / 'source.mp4'
            manifest_path = record.directory / 'manifest.json'
            if (source.is_symlink() or manifest_path.is_symlink() or not source.is_file()
                    or not manifest_path.is_file() or manifest_path.stat().st_size > 5 * 1024 * 1024):
                return False
            data = json.loads(manifest_path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or data.get('source_url') != url:
                return False
            artifacts = data.get('artifacts')
            if not isinstance(artifacts, dict) or 'transcript.txt' not in artifacts or 'contact.jpg' not in artifacts:
                return False
            return cache_valid(record.directory, data, sha256(source),
                               None if language == 'auto' else language, frame_count)
        except (OSError, ValueError, TypeError, ImportError, AttributeError):
            return False

    @staticmethod
    def _save_record(record: _Record) -> None:
        target = record.directory / '.job.json'
        temp = record.directory / '.job.tmp'
        temp.write_text(json.dumps({'version': 1, 'state': 'completed', 'key': record.key}), encoding='utf-8')
        temp.replace(target)

    def _get(self, job_id: str) -> _Record:
        if not isinstance(job_id, str) or not re.fullmatch(r'[0-9a-f]{32}', job_id):
            raise ValueError('Unknown job')
        self._recover()
        result = self._records.get(job_id)
        if result is None:
            raise ValueError('Unknown job')
        return result

    async def start(self, key: str, worker: Worker, *, refresh: bool = False) -> str:
        if not isinstance(key, str) or not key or len(key) > 512:
            raise ValueError('Invalid job request')
        async with self._lock:
            self._recover()
            for job_id, record in reversed(list(self._records.items())):
                if record.key == key and record.state in ('queued', 'running'):
                    return job_id
                if record.key == key and record.state == 'completed' and not refresh:
                    if await asyncio.to_thread(self._verified_cache, record):
                        return job_id
            if sum(record.state in ('queued', 'running') for record in self._records.values()) >= self._max_active:
                raise RuntimeError('Job queue capacity reached')
            while len(self._records) >= self._max_history:
                inactive = next((item_id for item_id, record in self._records.items()
                                 if record.state not in ('queued', 'running')), None)
                if inactive is None:
                    raise RuntimeError('Job history capacity reached')
                del self._records[inactive]  # Never delete prior media or artifacts.
            self.root.mkdir(parents=True, exist_ok=True)
            job_id = secrets.token_hex(16)
            directory = self.root / job_id
            directory.mkdir(mode=0o700)
            record = _Record(key=key, directory=directory)
            self._records[job_id] = record
            record.task = asyncio.create_task(self._run(record, worker))
            return job_id

    async def _run(self, record: _Record, worker: Worker) -> None:
        try:
            async with self._slots:
                record.state = 'running'
                await worker(record.directory)
                self._save_record(record)
                record.state = 'completed'
        except asyncio.CancelledError:
            record.state = 'cancelled'
            raise
        except Exception as exc:
            # Worker errors may contain account data, signed URLs or credentials.
            record.state = 'failed'
            category = type(exc).__name__
            record.error_category = category if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', category) else 'Error'

    def status(self, job_id: str) -> dict:
        record = self._get(job_id)
        result = {'job_id': job_id, 'state': record.state}
        if record.state == 'failed':
            result['error'] = 'Reel preparation failed; check account access and local dependencies.'
            result['error_category'] = record.error_category or 'Error'
        return result

    async def wait(self, job_id: str) -> None:
        record = self._get(job_id)
        if record.task:
            await asyncio.gather(record.task, return_exceptions=True)

    async def cancel(self, job_id: str) -> dict:
        record = self._get(job_id)
        if record.task and record.state in ('queued', 'running'):
            record.task.cancel()
            await asyncio.gather(record.task, return_exceptions=True)
            record.state = 'cancelled'
        return self.status(job_id)

    def read_artifact(self, job_id: str, name: str) -> bytes:
        record = self._get(job_id)
        if record.state != 'completed':
            raise ValueError('Job is not completed')
        if not isinstance(name, str) or not (name in ('transcript.txt', 'contact.jpg', 'manifest.json')
                or re.fullmatch(r'frame_\d{3}\.jpg', name)):
            raise ValueError('Artifact is unavailable')
        target = record.directory / name
        if target.is_symlink() or not target.resolve().is_relative_to(record.directory.resolve()) or not target.is_file():
            raise ValueError('Artifact is unavailable')
        if target.stat().st_size > 5 * 1024 * 1024:
            raise ValueError('Artifact exceeds the output limit')
        return target.read_bytes()

    async def close(self) -> None:
        for job_id, record in list(self._records.items()):
            if record.state in ('queued', 'running'):
                await self.cancel(job_id)
