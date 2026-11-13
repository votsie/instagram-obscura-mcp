import asyncio
import base64
import hashlib
import json
import subprocess
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from instagram_mcp.media import (MediaUnsupported, allowed_media_url, parse_content_range,
                                 prepare_obscura_media, wait_settled_snapshot, CHUNK,
                                 _candidate_expression, _fetch_expression)


class MediaValidationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is required to evaluate the isolated DOM fixture')
    def test_discovery_never_prioritizes_unrelated_dom_video(self):
        bootstrap = json.dumps({'data': [{'code': 'other', 'video_versions': [{'url': 'https://cdninstagram.com/wrong'}]},
                                         {'code': 'abc', 'video_versions': [{'url': 'https://cdninstagram.com/right'}]}]})
        fixture = ('global.location={href:"https://instagram.com/reel/abc/"};'
                   'global.document={querySelectorAll:(selector)=>selector.includes("script")?'
                   '[{textContent:' + json.dumps(bootstrap) + '}]:[{currentSrc:"https://cdninstagram.com/wrong",getAttribute:()=>"https://cdninstagram.com/wrong"}]};'
                   'console.log(' + _candidate_expression('abc') + ');')
        result = subprocess.run(['node', '-e', fixture], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)['candidates'], ['https://cdninstagram.com/right'])

    def test_signed_url_is_not_mutated_when_containing_single(self):
        url = 'https://cdninstagram.com/SINGLE.mp4?sig=SINGLE'
        expression = _fetch_expression(url, [(0, 0)], single=True)
        self.assertIn(url, expression)
    def test_only_https_instagram_cdn_hosts(self):
        self.assertTrue(allowed_media_url('https://scontent.cdninstagram.com/file.mp4?sig=secret'))
        self.assertTrue(allowed_media_url('https://scontent.xx.fbcdn.net/file.mp4'))
        for url in ('https://cdninstagram.com.evil.test/x', 'http://cdninstagram.com/x',
                    'https://evil@cdninstagram.com/x', 'https://127.0.0.1/x',
                    'https://cdninstagram.com:444/x', 'blob:https://instagram.com/x'):
            self.assertFalse(allowed_media_url(url))

    def test_range_is_exact_and_has_known_total(self):
        self.assertEqual(parse_content_range('bytes 0-9/100'), (0, 9, 100))
        for value in ('bytes 0-9/*', 'bytes 10-2/100', 'bytes 0-100/100', 'garbage'):
            with self.subTest(value=value), self.assertRaises(MediaUnsupported):
                parse_content_range(value)


class MediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_reads_validated_range_chunks_and_saves_only_local_path(self):
        client = mock.Mock()
        client._media_lock = asyncio.Lock()
        client.navigate = mock.AsyncMock()
        body = b'video payload'
        candidate = 'https://scontent.cdninstagram.com/file.mp4?sig=secret'
        client._evaluate = mock.AsyncMock(side_effect=[
            json.dumps({'page_url': 'https://www.instagram.com/reel/abc/', 'candidates': [candidate]}),
            json.dumps({'status': 206, 'range': f'bytes 0-0/{len(body)}', 'data': base64.b64encode(body[:1]).decode()}),
            json.dumps([{'status': 206, 'range': f'bytes 0-{len(body)-1}/{len(body)}',
                         'data': base64.b64encode(body).decode()}]),
        ])
        with tempfile.TemporaryDirectory() as d, \
             mock.patch('instagram_mcp.media.probe_media', new_callable=mock.AsyncMock,
                        return_value={'duration': 4.0, 'has_audio': True}):
            target = Path(d) / 'out.mp4'
            result = await prepare_obscura_media(client, 'https://instagram.com/reel/abc/?tracking=secret', target)
            self.assertEqual(target.read_bytes(), body)
            self.assertEqual(result['sha256'], hashlib.sha256(body).hexdigest())
            self.assertTrue(result['has_audio'])
            self.assertNotIn('secret', repr(result))

    async def test_wrong_page_or_nonrange_response_does_not_replace_existing(self):
        for page, status in (('https://instagram.com/reel/other/', 206),
                             ('https://instagram.com/reel/abc/', 200)):
            with self.subTest(page=page, status=status), tempfile.TemporaryDirectory() as d:
                target = Path(d) / 'out.mp4'
                target.write_bytes(b'old')
                client = mock.Mock()
                client._media_lock = asyncio.Lock()
                client.navigate = mock.AsyncMock()
                client._evaluate = mock.AsyncMock(side_effect=[
                    json.dumps({'page_url': page, 'candidates': ['https://cdninstagram.com/v.mp4?sensitive=1']}),
                    json.dumps({'status': status, 'range': None, 'data': ''}),
                ])
                with self.assertRaises(MediaUnsupported) as err:
                    await prepare_obscura_media(client, 'https://instagram.com/reel/abc/', target)
                self.assertEqual(target.read_bytes(), b'old')
                self.assertNotIn('sensitive', str(err.exception))

    async def test_failed_range_does_not_leave_partial_file(self):
        client = mock.Mock()
        client._media_lock = asyncio.Lock()
        client.navigate = mock.AsyncMock()
        client._evaluate = mock.AsyncMock(side_effect=[
            json.dumps({'page_url': 'https://instagram.com/reel/abc/', 'candidates': ['https://cdninstagram.com/a']}),
            json.dumps({'status': 206, 'range': 'bytes 0-0/10', 'data': base64.b64encode(b'x').decode()}),
            json.dumps([{'status': 206, 'range': 'bytes 1-9/10', 'data': base64.b64encode(b'x'*9).decode()}]),
        ])
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / 'out.mp4'
            with self.assertRaises(MediaUnsupported):
                await prepare_obscura_media(client, 'https://instagram.com/reel/abc/', target)
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(d).iterdir()), [])

    async def test_transport_error_reports_phase_without_sensitive_detail(self):
        client = mock.Mock()
        client._media_lock = asyncio.Lock()
        client.navigate = mock.AsyncMock()
        client._evaluate = mock.AsyncMock(side_effect=[
            json.dumps({'page_url':'https://instagram.com/reel/abc/', 'candidates':['https://cdninstagram.com/a?secret=1']}),
            RuntimeError('secret URL')])
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(MediaUnsupported) as err:
                await prepare_obscura_media(client, 'https://instagram.com/reel/abc/', Path(d) / 'out.mp4')
            self.assertIn('probe', str(err.exception))
            self.assertNotIn('secret', str(err.exception))

    async def test_multiple_ranges_keep_original_byte_order(self):
        content = b'a' * CHUNK + b'b' * CHUNK + b'c'
        ranges = [(0, CHUNK-1), (CHUNK, CHUNK*2-1), (CHUNK*2, CHUNK*2)]
        parts = [{'status': 206, 'range': f'bytes {start}-{end}/{len(content)}',
                  'data': base64.b64encode(content[start:end+1]).decode()} for start, end in ranges]
        client = mock.Mock()
        client._media_lock = asyncio.Lock()
        client.navigate = mock.AsyncMock()
        client._evaluate = mock.AsyncMock(side_effect=[
            json.dumps({'page_url': 'https://instagram.com/p/abc/', 'candidates': ['https://cdninstagram.com/a']}),
            json.dumps({'status': 206, 'range': f'bytes 0-0/{len(content)}', 'data': 'YQ=='}),
            json.dumps(parts)])
        with tempfile.TemporaryDirectory() as d, \
             mock.patch('instagram_mcp.media.probe_media', new_callable=mock.AsyncMock,
                        return_value={'duration': 1, 'has_audio': True}):
            target = Path(d) / 'out.mp4'
            result = await prepare_obscura_media(client, 'https://instagram.com/p/abc/', target)
            self.assertEqual(target.read_bytes(), content)
            self.assertEqual(result['size'], len(content))

    async def test_range_can_use_native_cdp_header_when_fetch_hides_it(self):
        client = mock.Mock()
        client._media_lock = asyncio.Lock()
        client.navigate = mock.AsyncMock()
        url = 'https://cdninstagram.com/file.mp4?sig=secret'
        client._evaluate = mock.AsyncMock(side_effect=[
            json.dumps({'page_url': 'https://instagram.com/reel/abc/', 'candidates': [url]}),
            json.dumps({'status': 206, 'range': None, 'data': 'YQ=='}),
            json.dumps([{'status': 206, 'range': None, 'data': 'YWJj'}]),
        ])
        client.get_cdn_content_range = mock.Mock(side_effect=['bytes 0-0/3', 'bytes 0-2/3'])
        with tempfile.TemporaryDirectory() as d, \
             mock.patch('instagram_mcp.media.probe_media', new_callable=mock.AsyncMock,
                        return_value={'duration': 1, 'has_audio': True}):
            target = Path(d) / 'out.mp4'
            result = await prepare_obscura_media(client, 'https://instagram.com/reel/abc/', target)
            self.assertEqual(target.read_bytes(), b'abc')
            self.assertEqual(result['size'], 3)
            self.assertNotIn('secret', repr(result))

    async def test_settle_reports_empty_page_explicitly(self):
        client = mock.Mock()
        client.snapshot = mock.AsyncMock(return_value={'url': 'https://instagram.com/', 'text': '', 'links': []})
        result = await wait_settled_snapshot(client, timeout=0.02, interval=0.01)
        self.assertFalse(result['settled'])


if __name__ == '__main__':
    unittest.main()
