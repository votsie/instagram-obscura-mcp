"""Offline integration checks for the real local engine and manual auth adapter."""
import asyncio
import base64
import tempfile
import unittest
import os
from pathlib import Path
from unittest import mock

from instagram_mcp.auth import AuthSession
from instagram_mcp.errors import LoginRequired, ProtocolError
from instagram_mcp.obscura import ObscuraClient, ProfileBusy
from instagram_mcp.ui import InstagramUI


BINARY = Path(os.environ.get('INSTAGRAM_TEST_OBSCURA', 'nonexistent-test-obscura'))


class ManualLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_browser_launch_failure_closes_playwright(self):
        playwright = mock.Mock()
        playwright.chromium.launch = mock.AsyncMock(side_effect=RuntimeError('unavailable'))
        playwright.stop = mock.AsyncMock()
        manager = mock.Mock()
        manager.start = mock.AsyncMock(return_value=playwright)
        auth = AuthSession()
        with mock.patch('playwright.async_api.async_playwright', return_value=manager):
            with self.assertRaisesRegex(RuntimeError, 'Could not open'):
                await auth.start()
        playwright.stop.assert_awaited_once()
        with self.assertRaisesRegex(RuntimeError, 'not active'):
            await auth.status()

    async def test_pending_login_keeps_browser_open_for_user(self):
        auth = AuthSession()
        auth._context = mock.Mock()
        auth._context.cookies = mock.AsyncMock(return_value=[])
        auth._page = mock.Mock(url='https://www.instagram.com/accounts/login/')
        auth._browser = mock.Mock()
        auth._browser.close = mock.AsyncMock()
        with self.assertRaises(LoginRequired):
            await auth.finish()
        auth._browser.close.assert_not_awaited()
        await auth.close()

    async def test_manual_login_handoff_filters_state_and_closes_browser(self):
        cookies = [
            {'name': 'sessionid', 'value': 'synthetic-session', 'domain': '.instagram.com',
             'path': '/', 'secure': True, 'httpOnly': True, 'sameSite': 'None', 'expires': -1},
            {'name': 'foreign', 'value': 'synthetic-foreign', 'domain': '.example.com', 'path': '/'},
        ]
        page = mock.Mock()
        page.url = 'https://www.instagram.com/'
        page.goto = mock.AsyncMock()
        page.evaluate = mock.AsyncMock(side_effect=[{'synthetic': 'session-storage'}, 'SyntheticAgent/1.0'])
        context = mock.Mock()
        context.new_page = mock.AsyncMock(return_value=page)
        context.cookies = mock.AsyncMock(return_value=cookies)
        context.storage_state = mock.AsyncMock(return_value={'cookies': cookies, 'origins': [
            {'origin': 'https://www.instagram.com', 'localStorage': [{'name': 'ok', 'value': '1'}]},
            {'origin': 'https://example.com', 'localStorage': [{'name': 'foreign', 'value': '2'}]},
        ]})
        browser = mock.Mock()
        browser.new_context = mock.AsyncMock(return_value=context)
        browser.close = mock.AsyncMock()
        playwright = mock.Mock()
        playwright.chromium.launch = mock.AsyncMock(return_value=browser)
        playwright.stop = mock.AsyncMock()
        manager = mock.Mock()
        manager.start = mock.AsyncMock(return_value=playwright)
        with mock.patch('playwright.async_api.async_playwright', return_value=manager):
            auth = AuthSession()
            await auth.start()
            status = await auth.status()
            self.assertTrue(status['authenticated'])
            state = await auth.finish()
        self.assertEqual([c['name'] for c in state['cookies']], ['sessionid'])
        self.assertEqual(set(state['local_storage']), {'https://www.instagram.com'})
        self.assertEqual(state['session_storage'], {'synthetic': 'session-storage'})
        self.assertEqual(state['user_agent'], 'SyntheticAgent/1.0')
        browser.close.assert_awaited_once()
        playwright.stop.assert_awaited_once()
        playwright.chromium.launch.assert_awaited_once_with(channel='chrome', headless=False)
        self.assertNotIn('synthetic-session', repr(status))


@unittest.skipUnless(BINARY.is_file(), 'Local Obscura binary is not installed')
class LocalEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_upload_opt_in_in_local_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            upload_dir = root / 'uploads'
            upload_dir.mkdir()
            original = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')
            media = upload_dir / 'fixture.png'
            media.write_bytes(original)
            async with ObscuraClient(BINARY, root / 'profile', allow_file_access=True) as client:
                await client._evaluate("document.body.innerHTML='<input id=file type=file style=\"display:none\">'")
                client.snapshot = mock.AsyncMock(return_value={'url':'about:blank','title':'','text':'','links':[]})
                verifier = mock.AsyncMock(return_value=True)
                ui = InstagramUI(client, upload_dir, verifier)
                with mock.patch('instagram_mcp.ui.valid_instagram_url', return_value=True):
                    ref = next(item['ref'] for item in (await ui.observe())['controls'] if item['type'] == 'file')
                    await ui.upload(ref, [str(media)], 'fixture')
                value = await client._evaluate("(async()=>{const f=document.querySelector('#file').files[0];return JSON.stringify({name:f.name,size:f.size,hex:Array.from(new Uint8Array(await f.arrayBuffer())).map(b=>b.toString(16).padStart(2,'0')).join('')})})()")
                data = __import__('json').loads(value)
                self.assertEqual(data, {'name':'fixture.png','size':len(original),'hex':original.hex()})

    async def test_engine_lifecycle_lock_screenshot_and_ui(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = ObscuraClient(BINARY, root / 'profile')
            await first.start()
            process = first._process
            try:
                self.assertTrue(first._job_assigned if __import__('os').name == 'nt' else True)
                from websockets.asyncio.client import connect
                from websockets.exceptions import InvalidStatus
                host, port = first._socket.remote_address[:2]
                self.assertEqual(host, '127.0.0.1')
                with self.assertRaises(InvalidStatus):
                    async with connect(f'ws://127.0.0.1:{port}/devtools/browser', open_timeout=5):
                        pass
                second = ObscuraClient(BINARY, root / 'profile')
                with self.assertRaises(ProfileBusy):
                    await second.start()
                with self.assertRaises(ValueError):
                    await first.navigate('http://127.0.0.1/')
                self.assertEqual((await first.snapshot())['url'], 'about:blank')
                screenshot = await first._command('Page.captureScreenshot', {'format': 'png'}, target=True)
                self.assertTrue(base64.b64decode(screenshot['data']).startswith(b'\x89PNG\r\n\x1a\n'))
                await first._evaluate("document.body.innerHTML='<button id=go onclick=\"window.fixtureClicked=1\">Go</button><input id=t aria-label=Text value=old><input id=file type=file style=\"display:none\">';window.fixtureClicked=0")
                # about:blank is used only by this isolated fixture; real UI accepts Instagram URLs only.
                first.snapshot = mock.AsyncMock(return_value={'url': 'about:blank', 'title': '', 'text': '', 'links': []})
                verifier = mock.AsyncMock(return_value=True)
                ui = InstagramUI(first, root / 'uploads', verifier)
                with mock.patch('instagram_mcp.ui.valid_instagram_url', return_value=True):
                    observed = await ui.observe()
                    button = next(item['ref'] for item in observed['controls'] if item['tag'] == 'BUTTON')
                    after_click = await ui.click(button, 'fixture')
                    self.assertEqual(await first._evaluate('window.fixtureClicked'), 1)
                    text = next(item['ref'] for item in after_click['controls'] if item['tag'] == 'INPUT')
                    after_fill = await ui.fill(text, 'new', 'fixture')
                    self.assertEqual(await first._evaluate("document.querySelector('#t').value"), 'new')
                    text = next(item['ref'] for item in after_fill['controls'] if item['type'] != 'file' and item['tag'] == 'INPUT')
                    after_press = await ui.press(text, 'Home', 'fixture')
                    after_scroll = await ui.scroll('down', 'fixture')
                    file_ref = next(item['ref'] for item in after_scroll['controls'] if item['type'] == 'file')
                    upload_dir = root / 'uploads'
                    upload_dir.mkdir()
                    upload = upload_dir / 'fixture.png'
                    upload.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='))
                    # The secure engine default disables file access; unsupported must be explicit.
                    with self.assertRaises(ProtocolError):
                        await ui.upload(file_ref, [str(upload)], 'fixture')
                    self.assertEqual(await first._evaluate("document.querySelector('#file').files.length"), 0)
                    self.assertGreaterEqual(verifier.await_count, 2)
            finally:
                await first.close()
            self.assertIsNotNone(process.returncode)
            # A stopped instance must not leave the profile locked.
            async with ObscuraClient(BINARY, root / 'profile') as restarted:
                self.assertEqual((await restarted.snapshot())['url'], 'about:blank')


if __name__ == '__main__':
    unittest.main()
