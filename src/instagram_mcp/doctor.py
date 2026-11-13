"""Report local requirements without launching a browser or accessing the network."""
import importlib.util
import json
import shutil
from .config import Settings


def checks():
    config = Settings()
    model = config.model
    return {'obscura': config.binary.is_file(), 'ffmpeg': bool(shutil.which('ffmpeg')),
            'ffprobe': bool(shutil.which('ffprobe')), 'aria2c': bool(shutil.which('aria2c')),
            'faster_whisper': bool(importlib.util.find_spec('faster_whisper')),
            'whisper_model': (model / 'model.bin').is_file(),
            'model_not_named_english_only': not model.name.lower().endswith('.en'),
            'file_upload_enabled': config.allow_file_access}


def main():
    result = checks()
    print(json.dumps(result, indent=2))
    return 0 if all(result[k] for k in ('obscura', 'ffmpeg', 'ffprobe', 'faster_whisper', 'whisper_model', 'model_not_named_english_only')) else 1


if __name__ == '__main__':
    raise SystemExit(main())
