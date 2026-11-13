import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from instagram_mcp.errors import ProtocolError
from instagram_mcp.obscura import ObscuraClient, ProfileLock, sanitize_snapshot


class FakeSocket:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.sent = []

    async def send(self, message):
        self.sent.append(json.loads(message))

    async def recv(self):
        return json.dumps(next(self.replies))


class ObscuraTests(unittest.IsolatedAsyncioTestCase):
    def test_profile_lock_excludes_other_clients_and_releases(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'profile.lock'
            first, second = ProfileLock(path), ProfileLock(path)
            first.acquire()
            try:
                with self.assertRaises(RuntimeError):
                    second.acquire()
            finally:
                first.release()
            second.acquire()
            second.release()

    def test_profile_lock_excludes_another_process(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'profile.lock'
            script = ('import sys;from pathlib import Path;from instagram_mcp.obscura import ProfileLock;'
                      'lock=ProfileLock(Path(sys.argv[1]));lock.acquire();print("ready",flush=True);'
                      'sys.stdin.readline();lock.release()')
            child = subprocess.Popen([sys.executable, '-c', script, str(path)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'ready')
                lock = ProfileLock(path)
                with self.assertRaises(RuntimeError):
                    lock.acquire()
                child.stdin.write('\n')
                child.stdin.flush()
                self.assertEqual(child.wait(timeout=5), 0)
                lock.acquire()
                lock.release()
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
                child.stdin.close()
                child.stdout.close()

    async def test_start_failure_releases_profile_lock(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fake_binary = root / 'fake.exe'
            fake_binary.write_bytes(b'file')
            client = ObscuraClient(fake_binary, root / 'profile')
            with mock.patch('instagram_mcp.obscura.private_profile', side_effect=RuntimeError('fail')):
                with self.assertRaises(RuntimeError):
                    await client.start()
            lock = ProfileLock(root / 'profile' / '.session.lock')
            lock.acquire()
            lock.release()
    async def test_job_closed_even_if_browser_parent_already_exited(self):
        client = ObscuraClient('unused.exe', 'unused')
        client._process = mock.Mock(pid=999, returncode=0)
        client._job = mock.Mock()
        client._job_assigned = True
        job = client._job
        await client.close()
        job.Close.assert_called_once_with()

    def test_snapshot_strips_signed_queries_and_challenge_information(self):
        result = sanitize_snapshot({'url': 'https://www.instagram.com/p/abc/?token=secret',
            'title': 'test', 'text': 'see https://example.com/a?sig=secret#frag',
            'links': [{'text': 'post', 'href': 'https://www.instagram.com/reel/abc/?sig=secret'},
                      {'text': 'external', 'href': 'https://example.com/?secret=1'}]})
        self.assertNotIn('secret', repr(result))
        self.assertEqual(result['links'][0]['href'], 'https://www.instagram.com/reel/abc/')
        challenge = sanitize_snapshot({'url': 'https://www.instagram.com/challenge/secret/?token=secret',
                                       'text': 'private challenge details', 'links': []})
        self.assertNotIn('secret', repr(challenge))
        self.assertNotIn('private challenge details', repr(challenge))

    async def test_user_agent_restores_to_new_browser_target(self):
        with tempfile.TemporaryDirectory() as d:
            first = ObscuraClient('unused.exe', d)
            first.save_user_agent('Mozilla/5.0 ExampleChrome')
            second = ObscuraClient('unused.exe', d)
            with mock.patch.object(second, '_command', new_callable=mock.AsyncMock) as command:
                await second.restore_user_agent()
            command.assert_awaited_once_with('Network.setUserAgentOverride',
                                             {'userAgent': 'Mozilla/5.0 ExampleChrome'}, target=True)
            with self.assertRaises(ValueError):
                first.save_user_agent('UA\r\nInjected: value')

    async def test_registration_compat_is_explicit_and_narrow(self):
        disabled = ObscuraClient('unused.exe', 'unused')
        enabled = ObscuraClient('unused.exe', 'unused', registration_compat=True)
        with mock.patch.object(disabled, '_command', new_callable=mock.AsyncMock) as command:
            await disabled.install_registration_compat()
            command.assert_not_awaited()
        with mock.patch.object(enabled, '_command', new_callable=mock.AsyncMock,
                               return_value={'identifier': 'shim'}) as command:
            await enabled.install_registration_compat()
        self.assertEqual(command.call_args.args[0], 'Page.addScriptToEvaluateOnNewDocument')
        source = command.call_args.args[1]['source']
        self.assertIn('ServiceWorkerRegistration', source)
        self.assertIn('Illegal constructor', source)
        self.assertNotIn('navigator.serviceWorker', source)
    async def test_command_discards_events_and_attaches_target_session(self):
        client = ObscuraClient('unused.exe', 'unused')
        client._socket = FakeSocket([{'method': 'Page.event'}, {'id': 1, 'result': {'ok': True}}])
        client._session_id = 'target-session'
        self.assertEqual(await client._command('Page.enable', {}, target=True), {'ok': True})
        self.assertEqual(client._socket.sent[0]['sessionId'], 'target-session')

    async def test_raw_response_range_is_captured_without_other_headers(self):
        client = ObscuraClient('unused.exe', 'unused')
        url = 'https://scontent.cdninstagram.com/file.mp4?sig=secret'
        client._socket = FakeSocket([
            {'method': 'Network.responseReceived', 'sessionId': 'target-session', 'params': {
                'response': {'url': url, 'status': 206, 'headers': {'Content-Range': 'bytes 1-9/10',
                                                                     'Set-Cookie': 'secret-cookie'}}}},
            {'id': 1, 'result': {}},
        ])
        client._session_id = 'target-session'
        await client._command('Runtime.evaluate', {}, target=True)
        self.assertEqual(client.get_cdn_content_range(url, 1, 9), 'bytes 1-9/10')
        self.assertIsNone(client.get_cdn_content_range(url, 0, 1))
        self.assertNotIn('secret-cookie', repr(client._media_responses))
        client.clear_cdn_responses()
        self.assertIsNone(client.get_cdn_content_range(url, 1, 9))

    async def test_errors_do_not_return_sensitive_protocol_detail(self):
        client = ObscuraClient('unused.exe', 'unused')
        client._socket = FakeSocket([{'id': 1, 'error': {'message': 'secret cookie'}}])
        with self.assertRaises(ProtocolError) as context:
            await client._command('Network.setCookies', {})
        self.assertNotIn('secret cookie', str(context.exception))

    async def test_diagnostics_record_codes_without_secret_message(self):
        with tempfile.TemporaryDirectory() as d:
            client = ObscuraClient('unused.exe', d, diagnostics=True)
            client._socket = FakeSocket([{'id': 1, 'error': {'code': -32000, 'message': 'secret cookie'}}])
            with self.assertRaises(ProtocolError):
                await client._command('Runtime.evaluate', {})
            log = (Path(d) / 'cdp-diagnostics.jsonl').read_text(encoding='utf-8')
            self.assertIn('-32000', log)
            self.assertNotIn('secret cookie', log)

    async def test_transport_diagnostics_record_only_numeric_close_codes(self):
        class Closed(Exception):
            sent = mock.Mock(code=1009)
            rcvd = None
        class BrokenSocket:
            async def send(self, message):
                pass
            async def recv(self):
                raise Closed('secret close reason')
        with tempfile.TemporaryDirectory() as d:
            client = ObscuraClient('unused.exe', d, diagnostics=True)
            client._socket = BrokenSocket()
            with self.assertRaises(ProtocolError):
                await client._command('Runtime.evaluate', {})
            log = (Path(d) / 'cdp-diagnostics.jsonl').read_text(encoding='utf-8')
            self.assertIn('1009', log)
            self.assertNotIn('secret close reason', log)

    async def test_state_rejects_other_origins_and_never_evaluates_them(self):
        client = ObscuraClient('unused.exe', 'unused')
        with mock.patch.object(client, '_command', new_callable=mock.AsyncMock) as command:
            with self.assertRaises(ValueError):
                await client.import_instagram_state({'cookies': [], 'local_storage': {'https://evil.test': []},
                                                     'session_storage': {}})
        command.assert_not_called()

    async def test_navigation_requires_instagram_https(self):
        client = ObscuraClient('unused.exe', 'unused')
        with self.assertRaises(ValueError):
            await client.navigate('http://localhost:1234/')

    async def test_navigation_rejects_reported_transport_error(self):
        client = ObscuraClient('unused.exe', 'unused')
        with mock.patch.object(client, '_command', new_callable=mock.AsyncMock,
                               return_value={'errorText': 'private error detail'}):
            with self.assertRaises(ProtocolError) as context:
                await client.navigate('https://www.instagram.com/')
        self.assertNotIn('private error detail', str(context.exception))

    async def test_navigation_requires_safe_final_document(self):
        client = ObscuraClient('unused.exe', 'unused')
        with mock.patch.object(client, '_command', new_callable=mock.AsyncMock, return_value={}), \
             mock.patch.object(client, '_evaluate', new_callable=mock.AsyncMock,
                               return_value=json.dumps({'url': 'https://evil.test/', 'ready': 'complete'})):
            with self.assertRaises(ProtocolError):
                await client.navigate('https://www.instagram.com/')

    async def test_import_sends_filtered_cookies_and_temporary_preload(self):
        client = ObscuraClient('unused.exe', 'unused')
        state = {'cookies': [{'name': 'sessionid', 'value': 'sensitive', 'domain': '.instagram.com',
                              'path': '/', 'httpOnly': True, 'secure': True}],
                 'local_storage': {'https://www.instagram.com': [{'name': 'key', 'value': 'value'}]},
                 'session_storage': {'temporary': 'value'}, 'session_origin': 'https://www.instagram.com'}
        async def cdp(method, params, target=False):
            return {'identifier': 'preload-id'} if method == 'Page.addScriptToEvaluateOnNewDocument' else {}
        with mock.patch.object(client, '_command', side_effect=cdp) as command, \
             mock.patch.object(client, 'navigate', new_callable=mock.AsyncMock) as navigate:
            await client.import_instagram_state(state)
        self.assertEqual(command.call_args_list[0].args[0], 'Network.setCookies')
        self.assertTrue(command.call_args_list[0].args[1]['cookies'][0]['httpOnly'])
        self.assertEqual(command.call_args_list[-1].args[0], 'Page.removeScriptToEvaluateOnNewDocument')
        navigate.assert_awaited_once_with('https://www.instagram.com/')


if __name__ == '__main__':
    unittest.main()
