"""User-controlled data paths and explicit security settings."""
from dataclasses import dataclass, field
import os
from pathlib import Path


def data_root() -> Path:
    override = os.environ.get('INSTAGRAM_MCP_HOME')
    if override:
        return Path(override).expanduser().resolve()
    if os.name == 'nt':
        base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local')))
    else:
        base = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local' / 'share')))
    return (base / 'instagram-obscura-mcp').resolve()


def opt_in_file_access() -> bool:
    value = os.environ.get('INSTAGRAM_ALLOW_FILE_ACCESS', 'false').strip().lower()
    if value in ('true', '1', 'yes'): return True
    if value in ('false', '0', 'no'): return False
    raise ValueError('INSTAGRAM_ALLOW_FILE_ACCESS must be true or false')


@dataclass(frozen=True)
class Settings:
    binary: Path = field(default_factory=lambda: Path(os.environ.get('INSTAGRAM_OBSCURA_BINARY', str(data_root() / 'obscura' / ('obscura.exe' if os.name == 'nt' else 'obscura')))).expanduser().resolve())
    profile: Path = field(default_factory=lambda: data_root() / 'profile')
    jobs: Path = field(default_factory=lambda: data_root() / 'jobs')
    model: Path = field(default_factory=lambda: Path(os.environ.get('INSTAGRAM_WHISPER_MODEL', str(data_root() / 'models' / 'whisper-small'))).expanduser().resolve())
    registration_compat: bool = True
    media_supported: bool = True
    allow_file_access: bool = field(default_factory=opt_in_file_access)
