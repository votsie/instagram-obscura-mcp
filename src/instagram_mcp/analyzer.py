"""Prepare an Instagram video for agent analysis using local media tools."""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

CACHE_VERSION = 3
FRAME_LIMIT = 24
MEDIA_INPUT = ['-protocol_whitelist', 'file,pipe', '-format_whitelist', 'mov,matroska,webm']
LANGUAGES = frozenset("af am ar as az ba be bg bn bo br bs ca cs cy da de el en es et eu fa fi fo fr gl gu ha haw he hi hr ht hu hy id is it ja jw ka kk km kn ko la lb ln lo lt lv mg mi mk ml mn mr ms mt my ne nl nn no oc pa pl ps pt ro ru sa sd si sk sl sn so sq sr su sv sw ta te tg th tk tl tr tt uk ur uz vi yi yo zh yue".split())


def model_path():
    from .config import Settings
    model = Settings().model
    if model.name.lower().endswith('.en'):
        raise ValueError('Use a multilingual Whisper model, not an English-only .en model')
    return model


def model_identity():
    path = model_path()
    model = path / 'model.bin'
    try:
        st = model.stat()
        stamp = f'{st.st_size}:{st.st_mtime_ns}'
    except OSError:
        stamp = 'unavailable'
    return hashlib.sha256((str(path.resolve()) + ':' + stamp).encode('utf-8')).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def cache_valid(root: Path, result: dict, source_hash: str, language: str | None, frame_count: int = 12) -> bool:
    if (not isinstance(result, dict) or result.get('version') != CACHE_VERSION
            or result.get('source_sha256') != source_hash or result.get('language') != language
            or result.get('requested_frames', 12) != frame_count
            or (result.get('has_audio') and result.get('model_identity') != model_identity())):
        return False
    artifacts = result.get('artifacts')
    if not isinstance(artifacts, dict) or not artifacts:
        return False
    speech, frames = result.get('speech'), result.get('frames')
    duration, times = result.get('duration_seconds'), result.get('frame_times_seconds')
    if (not isinstance(result.get('has_audio'), bool) or not isinstance(speech, dict)
            or speech.get('status') not in ('ok', 'no_speech', 'no_audio')
            or not isinstance(speech.get('text'), str) or not isinstance(speech.get('segments'), list)
            or not isinstance(frames, list) or not frames or any(not isinstance(x, str) or x not in artifacts for x in frames)
            or not isinstance(duration, (int, float)) or isinstance(duration, bool) or not math.isfinite(duration)
            or duration <= 0 or not isinstance(times, list)
            or any(not isinstance(t, (int, float)) or isinstance(t, bool) or not math.isfinite(t) for t in times)):
        return False
    resolved_root = root.resolve()
    try:
        for name, expected in artifacts.items():
            if not isinstance(name, str) or Path(name).is_absolute():
                return False
            target = (root / name).resolve()
            if not target.is_relative_to(resolved_root) or not target.is_file() or sha256(target) != expected:
                return False
    except (OSError, ValueError):
        return False
    return True


def probe_media(path: Path) -> dict:
    try:
        result = subprocess.run(['ffprobe', '-v', 'error', *MEDIA_INPUT, '-show_entries',
            'format=duration:stream=codec_type', '-of', 'json', str(path)],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('ffprobe failed or timed out') from exc
    if result.returncode:
        raise ValueError('The downloaded file is not a readable media file')
    try:
        info = json.loads(result.stdout)
        types = {stream.get('codec_type') for stream in info['streams']}
        duration = float(info['format']['duration'])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError('Media duration or streams could not be determined') from exc
    if 'video' not in types or not math.isfinite(duration) or not 0 < duration <= 7200:
        raise ValueError('Media must contain video with a duration between 0 and 7200 seconds')
    return {'duration': duration, 'has_audio': 'audio' in types}


def make_frames(source: Path, out: Path, duration: float, frame_count: int = 12) -> list[str]:
    # A new working directory is created for every non-cached generation.
    count = frame_count
    rate = count / duration
    frame_pattern = out / 'frame_%03d.jpg'
    try:
        subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                        *MEDIA_INPUT, '-i', str(source), '-vf', f'fps={rate:.9f},scale=720:-2:force_original_aspect_ratio=decrease',
                        '-frames:v', str(count), '-q:v', '3', str(frame_pattern)],
                       check=True, capture_output=True, timeout=300)
        frames = sorted(out.glob('frame_*.jpg'))
        if not frames:
            raise RuntimeError('No frames could be extracted')
        rows = math.ceil(len(frames) / 4)
        subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                        '-protocol_whitelist', 'file,pipe', '-format_whitelist', 'image2',
                        '-framerate', '1', '-i', str(frame_pattern), '-vf',
                        f'scale=240:240:force_original_aspect_ratio=decrease,pad=240:240:(ow-iw)/2:(oh-ih)/2,tile=4x{rows}',
                        '-frames:v', '1', str(out / 'contact.jpg')],
                       check=True, capture_output=True, timeout=120)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Frame extraction failed or timed out') from exc
    return [path.name for path in frames] + ['contact.jpg']


def transcribe(source: Path, language: str | None) -> dict:
    env = os.environ.copy()
    env.update({'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'PYTHONUTF8': '1'})
    command = [sys.executable, '-m', 'instagram_mcp.analyzer', '_transcribe', str(source)]
    if language:
        command.extend(['--language', language])
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                                errors='replace', env=env, timeout=1200)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Speech recognition failed or timed out') from exc
    if result.returncode:
        raise RuntimeError('Speech recognition failed; verify the local Whisper model and runtime')
    try:
        data = json.loads(result.stdout)
        if not isinstance(data, dict) or data.get('status') not in ('ok', 'no_speech'):
            raise ValueError('Unexpected speech result')
        return data
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError('Speech recognition returned invalid data') from exc


def _transcribe(source: Path, language: str | None) -> dict:
    MODEL = model_path()
    if not (MODEL / 'model.bin').is_file():
        raise RuntimeError('Local Whisper model is missing')
    from faster_whisper import WhisperModel
    import numpy as np
    decoded = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', *MEDIA_INPUT, '-i', str(source),
                              '-f', 'f32le', '-ac', '1', '-ar', '16000', 'pipe:1'],
                             capture_output=True, timeout=300)
    if decoded.returncode or not decoded.stdout:
        raise RuntimeError('Could not decode audio')
    samples = np.frombuffer(decoded.stdout, dtype=np.float32)
    model = WhisperModel(str(MODEL), device='cpu', compute_type='int8', local_files_only=True,
                         cpu_threads=min(os.cpu_count() or 1, 8))
    if not model.model.is_multilingual:
        raise RuntimeError('The selected Whisper model is English-only; use a multilingual model')
    segments, info = model.transcribe(samples, language=language, vad_filter=True, task='transcribe')
    segments = [{'start': round(s.start, 3), 'end': round(s.end, 3), 'text': s.text.strip()}
                for s in segments if s.text.strip()]
    return {'status': 'ok' if segments else 'no_speech', 'language': info.language,
            'language_probability': getattr(info, 'language_probability', None),
            'text': ' '.join(s['text'] for s in segments), 'segments': segments}


def validate_options(language: str | None, frame_count: int) -> None:
    if language is not None and language not in LANGUAGES:
        raise ValueError('Unsupported Whisper language code')
    if not isinstance(frame_count, int) or not 1 <= frame_count <= FRAME_LIMIT:
        raise ValueError('Frames must be between 1 and 24')


def analyze_file(source: Path, out: Path, language: str | None, source_url: str | None,
                 frame_count: int = 12) -> dict:
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError('Media file does not exist or is empty')
    validate_options(language, frame_count)
    source_hash = sha256(source)
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / 'manifest.json'
    if manifest_path.is_file():
        try:
            previous = json.loads(manifest_path.read_text(encoding='utf-8'))
            if (isinstance(previous, dict) and previous.get('source_url') == source_url
                    and cache_valid(out, previous, source_hash, language, frame_count)):
                return {**previous, 'cached': True}
        except (OSError, ValueError, TypeError):
            pass
    metadata = probe_media(source)
    # Build in an isolated directory; a failed run cannot corrupt the last good result.
    with tempfile.TemporaryDirectory(prefix='.reel-', dir=out) as temp:
        stage = Path(temp)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_frames = executor.submit(make_frames, source, stage, metadata['duration'], frame_count)
            future_speech = executor.submit(transcribe, source, language) if metadata['has_audio'] else None
            frames = future_frames.result()
            speech = future_speech.result() if future_speech else {'status': 'no_audio', 'text': '', 'segments': []}
        frame_times = []
        count = len([name for name in frames if name.startswith('frame_')])
        for i in range(count):
            frame_times.append(round((i + 0.5) * metadata['duration'] / count, 3))
        (stage / 'transcript.txt').write_text(speech['text'], encoding='utf-8')
        result = {'version': CACHE_VERSION, 'source_url': source_url, 'source_sha256': source_hash,
                  'language': language, 'requested_frames': frame_count, 'duration_seconds': metadata['duration'], 'has_audio': metadata['has_audio'],
                  'speech': speech, 'model_identity': model_identity() if metadata['has_audio'] else None,
                  'frames': frames, 'frame_times_seconds': frame_times,
                  'artifacts': {name: sha256(stage / name) for name in frames + ['transcript.txt']}}
        # Replace manifest last. Existing artifacts are revalidated by hashes on every reuse.
        for name in frames + ['transcript.txt']:
            os.replace(stage / name, out / name)
        (stage / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(stage / 'manifest.json', manifest_path)
    return {**result, 'cached': False}


def main() -> int:
    parser = argparse.ArgumentParser(description='Offline Reel frame extraction and multilingual speech transcription')
    commands = parser.add_subparsers(dest='command', required=True)
    analyze = commands.add_parser('analyze')
    analyze.add_argument('--file', type=Path, required=True)
    analyze.add_argument('--source-url')
    analyze.add_argument('--language')
    analyze.add_argument('--frames', type=int, default=12)
    analyze.add_argument('--output', type=Path, required=True)
    worker = commands.add_parser('_transcribe', help=argparse.SUPPRESS)
    worker.add_argument('file', type=Path)
    worker.add_argument('--language')
    args = parser.parse_args()
    if args.command == '_transcribe':
        validate_options(args.language, 1)
        result = _transcribe(args.file, args.language)
    else:
        result = analyze_file(args.file, args.output, args.language, args.source_url, args.frames)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
