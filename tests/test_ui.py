import asyncio
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from instagram_mcp.ui import InstagramUI, UIError


class UITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(asyncio.to_thread, self.temp.cleanup)
        self.client = mock.Mock()
        self.client.allow_file_access = False
        self.client.snapshot = mock.AsyncMock(return_value={'url':'https://www.instagram.com/', 'title':'', 'text':'', 'links':[]})
        self.client._command = mock.AsyncMock(side_effect=self.command)
        self.client._evaluate = mock.AsyncMock(side_effect=self.evaluate)
        self.verify = mock.AsyncMock(return_value=True)
        self.ui = InstagramUI(self.client, Path(self.temp.name), self.verify)
        self.metadata = {'url': 'https://www.instagram.com/', 'tag': 'BUTTON', 'type': '',
                         'role': '', 'href': '', 'action': '', 'x': 20, 'y': 20,
                         'connected': True, 'disabled': False, 'visible': True, 'unobstructed': True}
        self.node_id = 10

    async def command(self, method, params, target=False):
        if method == 'DOM.getDocument':
            return {'root': {'nodeId': 1}}
        if method == 'DOM.querySelector':
            return {'nodeId': self.node_id}
        return {}

    async def evaluate(self, expression):
        if 'OBSERVE_CONTROLS' in expression:
            nonce = re.search(r'const nonce="([0-9a-f]+)"', expression).group(1)
            return json.dumps([{'marker':nonce+'-0', 'tag':'BUTTON', 'type':'', 'role':'', 'label':'Open'}])
        if 'SELECT_TEXT' in expression or 'VERIFY_FILL' in expression or 'VERIFY_UPLOAD' in expression or 'document.activeElement' in expression:
            return True
        return json.dumps(self.metadata)

    async def test_observe_and_click_return_fresh_refs_and_stale_old_ref(self):
        first = await self.ui.observe()
        old = first['controls'][0]['ref']
        self.assertNotIn('internal', old)
        refreshed = await self.ui.click(old, 'fixture_owner')
        self.assertNotEqual(refreshed['controls'][0]['ref'], old)
        with self.assertRaises(UIError):
            await self.ui.click(old, 'fixture_owner')
        self.verify.assert_awaited()

    async def test_replaced_dom_node_is_rejected(self):
        ref = (await self.ui.observe())['controls'][0]['ref']
        self.node_id = 11
        with self.assertRaises(UIError):
            await self.ui.click(ref, 'fixture_owner')

    async def test_external_link_and_form_are_blocked_before_click(self):
        for key in ('href', 'action'):
            ref = (await self.ui.observe())['controls'][0]['ref']
            self.metadata[key] = 'https://evil.test/collect?secret=1'
            with self.assertRaises(UIError) as error:
                await self.ui.click(ref, 'fixture_owner')
            self.assertNotIn('secret', str(error.exception))
            self.metadata[key] = ''

    async def test_obscured_or_offscreen_control_cannot_be_clicked(self):
        for field in ('visible', 'unobstructed'):
            ref = (await self.ui.observe())['controls'][0]['ref']
            self.metadata[field] = False
            with self.assertRaises(UIError):
                await self.ui.click(ref, 'fixture_owner')
            self.metadata[field] = True
        self.assertFalse(any(call.args[0] == 'Input.dispatchMouseEvent' for call in self.client._command.call_args_list))

    async def test_account_must_match_before_action(self):
        ref = (await self.ui.observe())['controls'][0]['ref']
        self.verify.return_value = False
        with self.assertRaises(UIError):
            await self.ui.click(ref, 'fixture_owner')
        self.assertFalse(any(call.args[0] == 'Input.dispatchMouseEvent' for call in self.client._command.call_args_list))

    async def test_fill_password_or_otp_is_never_allowed(self):
        for field in ({'tag':'INPUT','type':'password','name':'pass','autocomplete':''},
                      {'tag':'INPUT','type':'text','name':'verification_code','autocomplete':'one-time-code'}):
            ref = (await self.ui.observe())['controls'][0]['ref']
            self.metadata.update(field)
            with self.assertRaises(UIError):
                await self.ui.fill(ref, 'secret', 'fixture_owner')
            self.metadata.update({'tag':'BUTTON','type':'','name':'','autocomplete':''})

    async def test_fill_selects_and_verifies_exact_text(self):
        ref = (await self.ui.observe())['controls'][0]['ref']
        self.metadata.update({'tag':'INPUT','type':'text'})
        await self.ui.fill(ref, 'new text', 'fixture_owner')
        self.assertTrue(any(call.args[0] == 'Input.insertText' and call.args[1] == {'text':'new text'}
                            for call in self.client._command.call_args_list))
        self.assertTrue(any('VERIFY_FILL' in call.args[0] for call in self.client._evaluate.call_args_list))

    async def test_upload_rejects_outside_root_and_symlinks(self):
        outside = Path(self.temp.name).parent / 'outside-instagram-test.png'
        outside.write_bytes(b'not-image')
        self.addCleanup(outside.unlink, missing_ok=True)
        ref = (await self.ui.observe())['controls'][0]['ref']
        self.metadata.update({'tag':'INPUT', 'type':'file'})
        with self.assertRaises(UIError):
            await self.ui.upload(ref, [str(outside)], 'fixture_owner')

    async def test_upload_reports_unsupported_without_enabling_file_access(self):
        media = Path(self.temp.name) / 'fixture.png'
        media.write_bytes(b'fixture')
        ref = (await self.ui.observe())['controls'][0]['ref']
        self.metadata.update({'tag': 'INPUT', 'type': 'file'})
        with self.assertRaisesRegex(UIError, 'unsupported'):
            await self.ui.upload(ref, [str(media)], 'fixture_owner')
        self.assertFalse(any(call.args[0] == 'DOM.setFileInputFiles'
                             for call in self.client._command.call_args_list))

    async def test_upload_opt_in_calls_file_input_only_after_validation(self):
        media = Path(self.temp.name) / 'fixture.png'
        media.write_bytes(b'fixture')
        self.client.allow_file_access = True
        ref = (await self.ui.observe())['controls'][0]['ref']
        self.metadata.update({'tag': 'INPUT', 'type': 'file'})
        await self.ui.upload(ref, [str(media)], 'fixture_owner')
        calls = [call for call in self.client._command.call_args_list if call.args[0] == 'DOM.setFileInputFiles']
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args[1]['files'], [str(media.resolve())])

    async def test_upload_does_not_report_success_when_input_unchanged(self):
        media = Path(self.temp.name) / 'fixture.png'
        media.write_bytes(b'fixture')
        self.client.allow_file_access = True
        ref = (await self.ui.observe())['controls'][0]['ref']
        self.metadata.update({'tag': 'INPUT', 'type': 'file'})
        original = self.evaluate
        async def evaluate(expression):
            if 'VERIFY_UPLOAD' in expression:
                return False
            return await original(expression)
        self.client._evaluate.side_effect = evaluate
        with self.assertRaisesRegex(UIError, 'not confirmed'):
            await self.ui.upload(ref, [str(media)], 'fixture_owner')

    async def test_press_rejects_arbitrary_key(self):
        ref = (await self.ui.observe())['controls'][0]['ref']
        with self.assertRaises(UIError):
            await self.ui.press(ref, 'Control+R', 'fixture_owner')


if __name__ == '__main__':
    unittest.main()
