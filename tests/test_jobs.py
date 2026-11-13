import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from instagram_mcp.jobs import JobManager


@pytest.mark.asyncio
async def test_duplicate_active_request_shares_job_and_cancel_stops_worker(tmp_path):
    jobs = JobManager(tmp_path, limit=1)
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def worker(_directory):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    first = await jobs.start('same-request', worker)
    await started.wait()
    assert await jobs.start('same-request', worker) == first
    assert jobs.status(first)['state'] == 'running'
    await jobs.cancel(first)
    assert stopped.is_set()
    assert jobs.status(first)['state'] == 'cancelled'
    await jobs.close()


@pytest.mark.asyncio
async def test_corrupt_source_and_malformed_saved_metadata_are_not_reused(tmp_path):
    invalid = tmp_path / ('a' * 32)
    invalid.mkdir()
    (invalid / '.job.json').write_text('[]', encoding='utf-8')
    key = 'https://www.instagram.com/reel/ABC/|1|auto'
    calls = []
    async def worker(directory):
        calls.append(True)
        write_complete_job(directory)
    jobs = JobManager(tmp_path)
    first = await jobs.start(key, worker)
    await jobs.wait(first)
    (tmp_path / first / 'source.mp4').write_bytes(b'wrong source')
    second = await jobs.start(key, worker)
    await jobs.wait(second)
    assert second != first and len(calls) == 2
    await jobs.close()


@pytest.mark.asyncio
async def test_failed_job_hides_exception_and_unknown_id_is_rejected(tmp_path):
    jobs = JobManager(tmp_path)
    async def worker(_directory):
        raise RuntimeError('secret-token')
    job_id = await jobs.start('failure', worker)
    await jobs.wait(job_id)
    result = jobs.status(job_id)
    assert result['state'] == 'failed'
    assert result['error_category'] == 'RuntimeError'
    assert 'secret-token' not in str(result)
    with pytest.raises(ValueError):
        jobs.status('../private')
    await jobs.close()


def write_complete_job(directory):
    data = {'source.mp4': b'video', 'frame_001.jpg': b'frame', 'contact.jpg': b'sheet',
            'transcript.txt': b'hello'}
    for name, content in data.items():
        (directory / name).write_bytes(content)
    sha = lambda name: hashlib.sha256(data[name]).hexdigest()
    manifest = {'version': 3, 'source_url': 'https://www.instagram.com/reel/ABC/',
                'source_sha256': sha('source.mp4'), 'language': None, 'requested_frames': 1,
                'duration_seconds': 1.0, 'has_audio': True,
                'model_identity': __import__('instagram_mcp.analyzer', fromlist=['model_identity']).model_identity(), 'speech': {'status': 'ok', 'text': 'hello', 'segments': []},
                'frames': ['frame_001.jpg', 'contact.jpg'], 'frame_times_seconds': [0.5],
                'artifacts': {name: sha(name) for name in ('frame_001.jpg', 'contact.jpg', 'transcript.txt')}}
    (directory / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')


@pytest.mark.asyncio
async def test_verified_completed_job_is_reused_across_restart_and_corruption_forces_new_job(tmp_path):
    calls = []
    key = 'https://www.instagram.com/reel/ABC/|1|auto'
    async def worker(directory):
        calls.append(True)
        write_complete_job(directory)
    jobs = JobManager(tmp_path)
    first = await jobs.start(key, worker)
    await jobs.wait(first)
    assert await jobs.start(key, worker) == first
    await jobs.close()

    jobs = JobManager(tmp_path)
    assert await jobs.start(key, worker) == first
    assert calls == [True]
    (tmp_path / first / 'frame_001.jpg').write_bytes(b'corrupted')
    replacement = await jobs.start(key, worker)
    assert replacement != first
    await jobs.wait(replacement)
    assert calls == [True, True]
    forced = await jobs.start(key, worker, refresh=True)
    assert forced not in (first, replacement)
    await jobs.wait(forced)
    assert calls == [True, True, True]
    await jobs.close()


@pytest.mark.asyncio
async def test_rejects_excessive_active_jobs_and_preserves_completed_files(tmp_path):
    jobs = JobManager(tmp_path, limit=1, max_active=2, max_history=3)
    gate = asyncio.Event()
    async def work(directory):
        (directory / 'proof.txt').write_text('existing', encoding='utf-8')
        await gate.wait()
    first = await jobs.start('first', work)
    await asyncio.sleep(0)
    second = await jobs.start('second', work)
    with pytest.raises(RuntimeError, match='capacity'):
        await jobs.start('third', work)
    gate.set()
    await jobs.wait(first)
    await jobs.wait(second)
    third = await jobs.start('third', work)
    await jobs.wait(third)
    fourth = await jobs.start('fourth', work)
    await jobs.wait(fourth)
    assert (tmp_path / first / 'proof.txt').read_text(encoding='utf-8') == 'existing'
    with pytest.raises(ValueError):
        jobs.status(first)
    assert jobs.status(fourth)['state'] == 'completed'
    await jobs.close()


@pytest.mark.asyncio
async def test_artifacts_are_restricted_to_completed_job_and_safe_names(tmp_path):
    jobs = JobManager(tmp_path)
    async def worker(directory):
        (directory / 'transcript.txt').write_text('Привет', encoding='utf-8')
        (directory / 'contact.jpg').write_bytes(b'example')
    job_id = await jobs.start('success', worker)
    await jobs.wait(job_id)
    assert jobs.status(job_id)['state'] == 'completed'
    assert jobs.read_artifact(job_id, 'transcript.txt') == b'\xd0\x9f\xd1\x80\xd0\xb8\xd0\xb2\xd0\xb5\xd1\x82'
    for name in ('../secret', 'media.mp4', 'frame_001.jpg/../../secret', ''):
        with pytest.raises(ValueError):
            jobs.read_artifact(job_id, name)
    await jobs.close()
