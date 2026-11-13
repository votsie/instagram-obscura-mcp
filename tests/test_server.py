import asyncio
import hashlib
import json
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from instagram_mcp.server import Runtime, create_server
import instagram_mcp.server as server_module


@pytest.mark.asyncio
async def test_health_does_not_start_browser(tmp_path):
    runtime = Runtime.for_test(tmp_path)
    server = create_server(runtime)
    async with Client(server) as client:
        result = await client.call_tool('instagram_health', {})
        assert result.structured_content['engine'] == 'obscura'
        assert runtime.browser is None
    await runtime.close()


@pytest.mark.asyncio
async def test_real_stdio_protocol_discovers_and_calls_health():
    params = StdioServerParameters(command=sys.executable, args=['-m', 'instagram_mcp.server'])
    async with Client(params) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert {'instagram_health', 'instagram_login_start', 'instagram_login_status',
                'instagram_login_finish', 'instagram_reel_start', 'instagram_reel_status',
                'instagram_reel_cancel', 'instagram_reel_artifact'} <= names
        result = await client.call_tool('instagram_health', {})
        assert not result.is_error
        assert result.structured_content['engine'] == 'obscura'
        bad = await client.call_tool('instagram_reel_status', {'job_id': '../secret'})
        assert bad.is_error


@pytest.mark.asyncio
async def test_login_transfers_state_without_exposing_credentials(tmp_path, monkeypatch):
    class FakeAuth:
        async def start(self): pass
        async def status(self): return {'authenticated': True, 'password': 'PRIVATE'}
        async def finish(self): return {'cookies': [{'name': 'sessionid', 'value': 'PRIVATE'}]}
        async def close(self): pass
    class FakeBrowser:
        def __init__(self, *_, **kwargs): self.received = None; self.options = kwargs
        async def start(self): pass
        async def import_instagram_state(self, state): self.received = state
        async def close(self): pass
    monkeypatch.setattr(server_module, 'AuthSession', FakeAuth)
    monkeypatch.setattr(server_module, 'ObscuraClient', FakeBrowser)
    runtime = Runtime.for_test(tmp_path)
    async with Client(create_server(runtime)) as client:
        before = await client.call_tool('instagram_login_status', {})
        assert before.structured_content['state'] == 'not_started'
        opened = await client.call_tool('instagram_login_start', {})
        assert opened.structured_content['state'] == 'waiting_for_user'
        duplicate = await client.call_tool('instagram_login_start', {})
        assert duplicate.is_error
        status = await client.call_tool('instagram_login_status', {})
        assert status.structured_content['state'] == 'ready_to_transfer'
        completed = await client.call_tool('instagram_login_finish', {})
        assert completed.structured_content['state'] == 'transferred'
        assert completed.structured_content['account_verified'] is False
        assert runtime.browser.received['cookies'][0]['value'] == 'PRIVATE'
        assert runtime.browser.options['registration_compat'] is True
        assert all('PRIVATE' not in str(result.model_dump()) for result in (before, opened, status, completed))
    await runtime.close()


@pytest.mark.asyncio
async def test_reel_invalid_urls_and_unverified_backend_fail_explicitly(tmp_path):
    runtime = Runtime.for_test(tmp_path)
    async with Client(create_server(runtime)) as client:
        invalid = await client.call_tool('instagram_reel_start', {'url': 'https://evil.test/reel/abc'})
        assert invalid.is_error
        unavailable = await client.call_tool('instagram_reel_start', {'url': 'https://instagram.com/reel/abc'})
        assert unavailable.is_error
        assert 'verification' in str(unavailable.content)
        assert runtime.browser is None
    await runtime.close()


@pytest.mark.asyncio
async def test_text_and_image_artifact_use_mcp_content(tmp_path):
    runtime = Runtime.for_test(tmp_path)
    async def work(directory):
        (directory / 'transcript.txt').write_text('hello', encoding='utf-8')
        (directory / 'contact.jpg').write_bytes(b'jpegbytes')
    job_id = await runtime.jobs.start('artifact-test', work)
    await runtime.jobs.wait(job_id)
    async with Client(create_server(runtime)) as client:
        text = await client.call_tool('instagram_reel_artifact', {'job_id': job_id, 'name': 'transcript.txt'})
        assert not text.is_error
        assert text.content[0].text == 'hello'
        image = await client.call_tool('instagram_reel_artifact', {'job_id': job_id, 'name': 'contact.jpg'})
        assert not image.is_error
        assert image.content[0].type == 'image'
        assert image.content[0].mime_type == 'image/jpeg'
        bad = await client.call_tool('instagram_reel_artifact', {'job_id': job_id, 'name': '../private'})
        assert bad.is_error
    await runtime.close()


@pytest.mark.asyncio
async def test_failed_login_transfer_closes_auth_and_does_not_leak_exception(tmp_path, monkeypatch):
    class FakeAuth:
        closed = False
        async def start(self): pass
        async def status(self): return {'authenticated': True}
        async def finish(self): raise RuntimeError('SECRET')
        async def close(self): self.closed = True
    monkeypatch.setattr(server_module, 'AuthSession', FakeAuth)
    runtime = Runtime.for_test(tmp_path)
    async with Client(create_server(runtime)) as client:
        await client.call_tool('instagram_login_start', {})
        session = runtime.auth
        failed = await client.call_tool('instagram_login_finish', {})
        assert failed.is_error
        assert 'SECRET' not in str(failed.model_dump())
        assert session.closed
        assert runtime.auth is None
    await runtime.close()


@pytest.mark.asyncio
async def test_cancel_analyzer_stops_process_tree():
    task = asyncio.create_task(server_module._run_analyzer([sys.executable, '-c', 'import time; time.sleep(30)']))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_verified_backend_reel_job_returns_artifacts_without_url_secrets(tmp_path, monkeypatch):
    from instagram_mcp import media
    observed = {}
    class FakeBrowser:
        def __init__(self, *_, **_kwargs): pass
        async def start(self): pass
        async def close(self): pass
    async def prepare(browser, url, target):
        observed['url'] = url
        target.write_bytes(b'video')
        return {'path': str(target)}
    async def analyzer(command):
        directory = Path(command[command.index('--output') + 1])
        (directory / 'transcript.txt').write_text('spoken words', encoding='utf-8')
        (directory / 'frame_001.jpg').write_bytes(b'frame')
        (directory / 'contact.jpg').write_bytes(b'sheet')
        digest = lambda name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        manifest = {'version': 3, 'source_url': command[command.index('--source-url') + 1],
                    'source_sha256': digest('source.mp4'), 'language': 'ru', 'requested_frames': 5,
                    'duration_seconds': 1, 'has_audio': True,
                    'model_identity': __import__('instagram_mcp.analyzer', fromlist=['model_identity']).model_identity(), 'speech': {'status': 'ok', 'text': 'spoken words', 'segments': []},
                    'frames': ['frame_001.jpg', 'contact.jpg'], 'frame_times_seconds': [0.5],
                    'artifacts': {name: digest(name) for name in ('transcript.txt', 'frame_001.jpg', 'contact.jpg')}}
        (directory / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    monkeypatch.setattr(server_module, 'ObscuraClient', FakeBrowser)
    monkeypatch.setattr(server_module, 'private_profile', lambda path: path.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(server_module, '_run_analyzer', analyzer)
    monkeypatch.setattr(media, 'prepare_obscura_media', prepare)
    runtime = Runtime.for_test(tmp_path)
    runtime.media_supported = True
    async with Client(create_server(runtime)) as client:
        started = await client.call_tool('instagram_reel_start', {
            'url': 'https://www.instagram.com/user/reel/ABC_12/?token=SECRET', 'frames': 5, 'language': 'ru'})
        assert not started.is_error
        job_id = started.structured_content['job_id']
        await runtime.jobs.wait(job_id)
        status = await client.call_tool('instagram_reel_status', {'job_id': job_id})
        assert status.structured_content['state'] == 'completed'
        result = await client.call_tool('instagram_reel_artifact', {'job_id': job_id, 'name': 'transcript.txt'})
        assert result.content[0].text == 'spoken words'
        assert observed['url'] == 'https://www.instagram.com/reel/ABC_12/'
        assert 'SECRET' not in str(started.model_dump())
        repeated = await client.call_tool('instagram_reel_start', {
            'url': 'https://instagram.com/reel/ABC_12/', 'frames': 5, 'language': 'ru'})
        assert repeated.structured_content['job_id'] == job_id
        refreshed = await client.call_tool('instagram_reel_start', {
            'url': 'https://instagram.com/reel/ABC_12/', 'frames': 5, 'language': 'ru', 'refresh': True})
        assert refreshed.structured_content['job_id'] != job_id
        await runtime.jobs.wait(refreshed.structured_content['job_id'])
    await runtime.close()


@pytest.mark.asyncio
async def test_untrusted_media_path_is_rejected_before_local_processing(tmp_path, monkeypatch):
    from instagram_mcp import media
    class FakeBrowser:
        def __init__(self, *_, **_kwargs): pass
        async def start(self): pass
        async def close(self): pass
    async def prepare(_browser, _url, _target):
        return {'path': str(tmp_path / 'private.mp4')}
    called = []
    async def analyzer(_command): called.append(True)
    monkeypatch.setattr(server_module, 'ObscuraClient', FakeBrowser)
    monkeypatch.setattr(server_module, 'private_profile', lambda path: path.mkdir(parents=True, exist_ok=True))
    monkeypatch.setattr(server_module, '_run_analyzer', analyzer)
    monkeypatch.setattr(media, 'prepare_obscura_media', prepare)
    runtime = Runtime.for_test(tmp_path)
    runtime.media_supported = True
    async with Client(create_server(runtime)) as client:
        result = await client.call_tool('instagram_reel_start', {'url':'https://instagram.com/p/abc'})
        job_id = result.structured_content['job_id']
        await runtime.jobs.wait(job_id)
        assert runtime.jobs.status(job_id)['state'] == 'failed'
        assert not called
    await runtime.close()


@pytest.mark.asyncio
async def test_analyzer_reports_failure_without_propagating_child_output():
    with pytest.raises(RuntimeError, match='Local Reel analysis failed'):
        await server_module._run_analyzer([sys.executable, '-c', 'import sys; print("SECRET"); sys.exit(7)'])


@pytest.mark.asyncio
async def test_analyzer_assignment_failure_cleans_parent_process(monkeypatch):
    if sys.platform != 'win32':
        pytest.skip('Windows Job Object assignment')
    import instagram_mcp.obscura as obscura
    def fail_assignment(_job, _pid):
        raise RuntimeError('job assignment failed')
    monkeypatch.setattr(obscura, 'assign_process_job', fail_assignment)
    with pytest.raises(RuntimeError, match='job assignment failed'):
        await asyncio.wait_for(server_module._run_analyzer([sys.executable, '-c', 'import time; time.sleep(30)']), timeout=5)


@pytest.mark.asyncio
async def test_status_exception_is_sanitized(tmp_path, monkeypatch):
    class BadAuth:
        async def start(self): pass
        async def status(self): raise RuntimeError('private-token')
        async def close(self): pass
    monkeypatch.setattr(server_module, 'AuthSession', BadAuth)
    runtime = Runtime.for_test(tmp_path)
    async with Client(create_server(runtime)) as client:
        await client.call_tool('instagram_login_start', {})
        status = await client.call_tool('instagram_login_status', {})
        finish = await client.call_tool('instagram_login_finish', {})
        assert status.is_error and finish.is_error
        assert 'private-token' not in str(status.model_dump()) + str(finish.model_dump())
    await runtime.close()
