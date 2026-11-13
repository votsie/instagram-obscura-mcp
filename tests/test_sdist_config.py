"""Release packaging invariants independent of host gitignore and user files."""
from pathlib import Path
import tomllib


def test_sdist_is_explicitly_allowlisted_and_excludes_runtime():
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    sdist = config['tool']['hatch']['build']['targets']['sdist']
    includes = set(sdist['only-include'])
    assert {'src', 'tests', 'docs', 'site', 'scripts', 'skills', 'examples', '.github',
            'pyproject.toml', 'README.md', 'README.ru.md', 'LICENSE'} <= includes
    assert not includes.intersection({'graphify-out', '.work', '.venv', '.git', 'dist'})
    excludes = ' '.join(sdist['exclude'])
    for forbidden in ('graphify-out', '.work', '.venv', '__pycache__', '.pytest_cache'):
        assert forbidden in excludes
