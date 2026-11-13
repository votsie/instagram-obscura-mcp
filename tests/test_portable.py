import pytest


def test_settings_use_portable_data_and_opt_in_upload(tmp_path, monkeypatch):
    from instagram_mcp.config import Settings
    monkeypatch.setenv('INSTAGRAM_MCP_HOME', str(tmp_path / 'home'))
    monkeypatch.delenv('INSTAGRAM_ALLOW_FILE_ACCESS', raising=False)
    settings = Settings()
    assert settings.profile == tmp_path / 'home' / 'profile'
    assert settings.jobs == tmp_path / 'home' / 'jobs'
    assert settings.allow_file_access is False
    monkeypatch.setenv('INSTAGRAM_ALLOW_FILE_ACCESS', 'true')
    assert Settings().allow_file_access is True
    monkeypatch.setenv('INSTAGRAM_ALLOW_FILE_ACCESS', 'invalid')
    with pytest.raises(ValueError): Settings()


def test_model_language_and_local_path_guards(tmp_path, monkeypatch):
    from instagram_mcp import analyzer
    for lang in (None, 'en', 'ru', 'es', 'ja', 'ar', 'yue'):
        analyzer.validate_options(lang, 12)
    for lang in ('', 'zz', 'EN', '../../private'):
        with pytest.raises(ValueError): analyzer.validate_options(lang, 12)
    monkeypatch.setenv('INSTAGRAM_WHISPER_MODEL', str(tmp_path / 'model.en'))
    with pytest.raises(ValueError): analyzer.model_path()


def test_multilingual_transcription_passes_language_and_preserves_text(tmp_path, monkeypatch):
    from instagram_mcp import analyzer
    from types import SimpleNamespace
    import sys
    model_path = tmp_path / 'multilingual-small'
    model_path.mkdir()
    (model_path / 'model.bin').write_bytes(b'fake')
    monkeypatch.setenv('INSTAGRAM_WHISPER_MODEL', str(model_path))
    seen = []
    class Model:
        def __init__(self, *args, **kwargs): self.model = SimpleNamespace(is_multilingual=True)
        def transcribe(self, samples, **kwargs):
            seen.append(kwargs)
            return [SimpleNamespace(start=0, end=1, text=' こんにちは ')], SimpleNamespace(language='ja', language_probability=.9)
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Model))
    monkeypatch.setitem(sys.modules, 'numpy', SimpleNamespace(frombuffer=lambda *a, **k: [0], float32=object()))
    monkeypatch.setattr(analyzer.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout=b'audio'))
    for language in (None, 'es', 'ja', 'ar'):
        result = analyzer._transcribe(tmp_path / 'fixture.mp4', language)
        assert result['text'] == 'こんにちは'
        assert result['language'] == 'ja'
        assert result['language_probability'] == .9
        assert seen[-1]['language'] == language
        assert seen[-1]['task'] == 'transcribe'


def test_model_change_invalidates_cache(tmp_path, monkeypatch):
    from instagram_mcp import analyzer
    monkeypatch.setenv('INSTAGRAM_WHISPER_MODEL', str(tmp_path / 'one'))
    one = analyzer.model_identity()
    monkeypatch.setenv('INSTAGRAM_WHISPER_MODEL', str(tmp_path / 'two'))
    assert analyzer.model_identity() != one


def test_offline_analyzer_on_synthetic_silent_video_and_cache(tmp_path):
    import json, shutil, subprocess
    from instagram_mcp import analyzer
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg is required for this offline test')
    video=tmp_path/'synthetic.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi',
                    '-i','color=c=blue:s=160x240:r=4:d=2','-pix_fmt','yuv420p',str(video)], check=True)
    out=tmp_path/'out'
    first=analyzer.analyze_file(video,out,None,'https://www.instagram.com/p/ABC/',4)
    assert first['speech']['status']=='no_audio'
    assert len(first['frame_times_seconds'])==4
    assert (out/'contact.jpg').is_file() and (out/'transcript.txt').read_text(encoding='utf-8')==''
    again=analyzer.analyze_file(video,out,None,'https://www.instagram.com/p/ABC/',4)
    assert again['cached'] is True
    (out/'frame_001.jpg').write_bytes(b'corruption')
    last=analyzer.analyze_file(video,out,None,'https://www.instagram.com/p/ABC/',4)
    assert last['cached'] is False
    assert analyzer.cache_valid(out,last,analyzer.sha256(video),None,4)


def test_transcribe_requires_model_and_keeps_subprocess_offline(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from instagram_mcp import analyzer
    monkeypatch.setenv('INSTAGRAM_WHISPER_MODEL',str(tmp_path/'missing'))
    with pytest.raises(RuntimeError, match='missing'):
        analyzer._transcribe(tmp_path/'a.mp4',None)
    def run(command, **kwargs):
        assert kwargs['env']['HF_HUB_OFFLINE']=='1'
        assert command[-2:]==['--language','es']
        return SimpleNamespace(returncode=0, stdout=json.dumps({'status':'ok','text':'hola'}))
    monkeypatch.setattr(analyzer.subprocess,'run',run)
    assert analyzer.transcribe(tmp_path/'a.mp4','es')['text']=='hola'


def test_doctor_reports_missing_without_network(tmp_path, monkeypatch):
    from instagram_mcp import doctor
    monkeypatch.setenv('INSTAGRAM_MCP_HOME',str(tmp_path))
    monkeypatch.delenv('INSTAGRAM_OBSCURA_BINARY',raising=False)
    monkeypatch.delenv('INSTAGRAM_WHISPER_MODEL',raising=False)
    assert doctor.checks()['obscura'] is False
    assert doctor.checks()['whisper_model'] is False
    assert doctor.main()==1
