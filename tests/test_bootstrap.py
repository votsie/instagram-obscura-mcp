import hashlib
from pathlib import Path
import zipfile
import pytest


def test_archive_only_extracts_expected_executables(tmp_path, monkeypatch):
    from instagram_mcp import bootstrap
    archive=tmp_path/'fixture.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('obscura.exe', b'a')
        z.writestr('obscura-worker.exe', b'b')
        z.writestr('../escape', b'bad')
    monkeypatch.setattr(bootstrap, 'sha256', lambda _: bootstrap.OBSCURA_SHA256)
    with pytest.raises(ValueError, match='archive'):
        bootstrap.install_obscura_archive(archive, tmp_path/'out')
    assert not (tmp_path.parent/'escape').exists()


def test_archive_hash_must_match_before_extract(tmp_path):
    from instagram_mcp import bootstrap
    archive=tmp_path/'fixture.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('obscura.exe', b'a')
        z.writestr('obscura-worker.exe', b'b')
    with pytest.raises(ValueError, match='SHA-256'):
        bootstrap.install_obscura_archive(archive, tmp_path/'out')
    assert not (tmp_path/'out'/'obscura.exe').exists()


def test_setup_requires_explicit_choice(capsys):
    from instagram_mcp import bootstrap
    with pytest.raises(SystemExit):
        bootstrap.main([])
    assert 'select' in capsys.readouterr().err.lower()


def test_setup_download_validates_size_and_hash(tmp_path, monkeypatch):
    import types
    from instagram_mcp import bootstrap
    monkeypatch.setattr(bootstrap.shutil,'which',lambda _: 'aria2c')
    def fake_run(command,**kwargs):
        assert '--split=16' in command and '--max-connection-per-server=16' in command
        (Path(command[command.index('--dir')+1])/command[command.index('--out')+1]).write_bytes(b'fixture')
    monkeypatch.setattr(bootstrap.subprocess,'run',fake_run)
    target=tmp_path/'x.bin'
    bootstrap.download('https://example.test/x',target,hashlib.sha256(b'fixture').hexdigest(),7)
    with pytest.raises(ValueError,match='verification'):
        bootstrap.download('https://example.test/x',target,'wrong',7)


def test_model_setup_uses_pinned_revision_and_stages_weights(tmp_path, monkeypatch):
    import sys,types
    from instagram_mcp import bootstrap
    monkeypatch.setenv('INSTAGRAM_MCP_HOME',str(tmp_path))
    monkeypatch.delenv('INSTAGRAM_WHISPER_MODEL',raising=False)
    calls=[]
    def snapshot(repo,**kwargs): calls.append((repo,kwargs))
    monkeypatch.setitem(sys.modules,'huggingface_hub',types.SimpleNamespace(snapshot_download=snapshot))
    def download(url,target,digest,size):
        assert digest==bootstrap.MODEL_SHA256 and size==bootstrap.MODEL_SIZE
        target.write_bytes(b'weights')
    monkeypatch.setattr(bootstrap,'download',download)
    bootstrap.setup_model()
    assert calls[0][1]['revision']==bootstrap.MODEL_REVISION
    assert calls[0][1]['max_workers']==16
    assert (tmp_path/'models'/'whisper-small'/'model.bin').read_bytes()==b'weights'


def test_download_retries_unreachable_ipv6_with_ipv4(tmp_path, monkeypatch):
    import subprocess
    from instagram_mcp import bootstrap
    monkeypatch.setattr(bootstrap.shutil,'which',lambda _: 'aria2c')
    calls=[]
    def run(command, **kwargs):
        calls.append(command)
        if len(calls)==1: raise subprocess.CalledProcessError(1,command)
        assert '--disable-ipv6=true' in command
        (Path(command[command.index('--dir')+1])/command[command.index('--out')+1]).write_bytes(b'ok')
    monkeypatch.setattr(bootstrap.subprocess,'run',run)
    bootstrap.download('https://example.test/x',tmp_path/'x.bin',hashlib.sha256(b'ok').hexdigest(),2)
    assert len(calls)==2
