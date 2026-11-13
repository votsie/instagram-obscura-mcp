"""Explicit, pinned setup for the optional local Obscura and multilingual model."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from .analyzer import sha256
from .config import Settings, data_root

OBSCURA_VERSION = 'v0.2.6'
OBSCURA_SHA256 = '0a110d0693753a252ed7ffd61e682363e8622caf79697f564c529099a31a6242'
OBSCURA_SIZE = 69076668
OBSCURA_URL = 'https://github.com/h4ckf0r0day/obscura/releases/download/v0.2.6/obscura-x86_64-windows.zip'
MODEL_REPO = 'Systran/faster-whisper-small'
MODEL_REVISION = '536b0662742c02347bc0e980a01041f333bce120'
MODEL_SHA256 = '3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671'
MODEL_SIZE = 483546902
MODEL_URL = f'https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/model.bin'


def download(url: str, target: Path, digest: str, size: int) -> None:
    aria = shutil.which('aria2c')
    if not aria:
        raise RuntimeError('Install aria2c for parallel, verified downloads and retry')
    target.parent.mkdir(parents=True, exist_ok=True)
    command = [aria, '--no-conf=true', '--allow-overwrite=true', '--auto-file-renaming=false',
               '--continue=true', '--max-connection-per-server=16', '--split=16', '--min-split-size=1M',
               '--summary-interval=0', '--dir', str(target.parent), '--out', target.name, '--', url]
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError:
        # Some hosts advertise IPv6 without a route. Retry once with IPv4; all
        # bytes remain subject to the same length and digest verification.
        subprocess.run(command[:1] + ['--disable-ipv6=true'] + command[1:], check=True)
    if target.stat().st_size != size or sha256(target) != digest:
        raise ValueError('Downloaded file failed size or SHA-256 verification')


def install_obscura_archive(archive: Path, target: Path) -> None:
    if sha256(archive) != OBSCURA_SHA256:
        raise ValueError('Obscura archive SHA-256 verification failed')
    with zipfile.ZipFile(archive) as source:
        names = source.namelist()
        expected = {'obscura.exe', 'obscura-worker.exe'}
        if len(names) != 2 or set(names) != expected:
            raise ValueError('Unexpected archive entries')
        if any(info.file_size > 100_000_000 or info.is_dir() for info in source.infolist()):
            raise ValueError('Unexpected archive entries')
        target.mkdir(parents=True, exist_ok=True)
        for name in names:
            with source.open(name) as src, (target / name).open('wb') as out:
                shutil.copyfileobj(src, out)


def setup_obscura() -> None:
    if os.name != 'nt':
        raise RuntimeError('Automatic Obscura install is currently supported on Windows x86-64 only; set INSTAGRAM_OBSCURA_BINARY manually elsewhere')
    binary = Settings().binary
    if binary.name != 'obscura.exe':
        raise ValueError('For setup, INSTAGRAM_OBSCURA_BINARY must name obscura.exe')
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='obscura-setup-', dir=root) as work:
        archive = Path(work) / 'obscura.zip'
        download(OBSCURA_URL, archive, OBSCURA_SHA256, OBSCURA_SIZE)
        install_obscura_archive(archive, binary.parent)
    print('Verified Obscura installed.')


def setup_model() -> None:
    from huggingface_hub import snapshot_download
    settings = Settings()
    target = settings.model
    if target.name.lower().endswith('.en'):
        raise ValueError('Use a multilingual model directory')
    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(MODEL_REPO, revision=MODEL_REVISION, local_dir=str(target),
                      allow_patterns=['config.json', 'tokenizer.json', 'vocabulary.txt'], max_workers=16)
    with tempfile.TemporaryDirectory(prefix='whisper-setup-', dir=target) as work:
        staged = Path(work) / 'model.bin'
        download(MODEL_URL, staged, MODEL_SHA256, MODEL_SIZE)
        os.replace(staged, target / 'model.bin')
    print('Verified multilingual Whisper model installed.')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--obscura', action='store_true', help='Install the pinned Windows Obscura binary')
    parser.add_argument('--model', action='store_true', help='Install the pinned multilingual Whisper small model')
    args = parser.parse_args(argv)
    if not (args.obscura or args.model):
        parser.error('Select --obscura, --model or both')
    if args.obscura: setup_obscura()
    if args.model: setup_model()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
