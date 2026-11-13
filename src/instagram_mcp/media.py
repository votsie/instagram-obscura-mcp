"""Prepare one explicitly selected Instagram video through Obscura only."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from .errors import ProtocolError
from .obscura import valid_instagram_url

CHUNK = 128 * 1024
PARALLEL = 16
MAX_BYTES = 200 * 1024 * 1024


class MediaUnsupported(ProtocolError):
    """The current Obscura/Instagram combination did not expose usable media."""


def allowed_media_url(url: object) -> bool:
    if not isinstance(url, str) or len(url) > 16384 or any(ord(c) < 32 for c in url):
        return False
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        return (parsed.scheme == 'https' and parsed.username is None and parsed.password is None
                and parsed.port is None and (host == 'cdninstagram.com' or host.endswith('.cdninstagram.com')
                                             or host == 'fbcdn.net' or host.endswith('.fbcdn.net')))
    except ValueError:
        return False


def post_identity(url: str) -> tuple[str, str]:
    if not valid_instagram_url(url):
        raise ValueError('Only HTTPS Instagram post and Reel URLs are accepted')
    path = urlsplit(url).path
    match = re.fullmatch(r'/(?:[A-Za-z0-9_.]{1,30}/)?(reel|reels|p)/([A-Za-z0-9_-]{1,64})/?', path)
    if not match:
        raise ValueError('Expected an Instagram post or Reel URL')
    return f'https://www.instagram.com/{match.group(1)}/{match.group(2)}/', match.group(2)


def parse_content_range(value: object) -> tuple[int, int, int]:
    match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', value or '') if isinstance(value, str) else None
    if not match:
        raise MediaUnsupported('The video server did not provide a valid byte range')
    start, end, total = map(int, match.groups())
    if not (0 <= start <= end < total <= MAX_BYTES):
        raise MediaUnsupported('The video range or size is invalid')
    return start, end, total


def _decode_range(item: object, start: int, end: int, total: int | None) -> tuple[bytes, int]:
    if not isinstance(item, dict) or item.get('status') != 206:
        raise MediaUnsupported('The video server does not support the required range requests')
    actual_start, actual_end, actual_total = parse_content_range(item.get('range'))
    if (actual_start, actual_end) != (start, end) or (total is not None and actual_total != total):
        raise MediaUnsupported('The video server returned a mismatched byte range')
    try:
        data = base64.b64decode(item['data'], validate=True)
    except (KeyError, ValueError, TypeError) as exc:
        raise MediaUnsupported('The video server returned invalid binary data') from exc
    if len(data) != end - start + 1:
        raise MediaUnsupported('The video segment length is incorrect')
    return data, actual_total


def _visible_range(client, item: object, url: str, start: int, end: int) -> object:
    if isinstance(item, dict) and item.get('status') == 206 and not item.get('range'):
        # Cross-origin JavaScript may hide Content-Range, while CDP sees the actual response.
        # Use only a raw 206 response for this exact URL and requested interval.
        return {**item, 'range': client.get_cdn_content_range(url, start, end)}
    return item


async def probe_media(path: Path) -> dict:
    try:
        process = await asyncio.create_subprocess_exec('ffprobe', '-v', 'error', '-protocol_whitelist',
            'file,pipe', '-format_whitelist', 'mov,matroska,webm', '-show_entries',
            'format=duration:stream=codec_type', '-of', 'json', str(path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise MediaUnsupported('Media verification timed out') from None
        if process.returncode or len(stdout) > 65536:
            raise MediaUnsupported('The downloaded content is not a supported video')
        parsed = json.loads(stdout)
        duration = float(parsed['format']['duration'])
        kinds = {entry.get('codec_type') for entry in parsed['streams']}
        if 'video' not in kinds or not math.isfinite(duration) or not 0 < duration <= 7200:
            raise MediaUnsupported('The downloaded content is not a supported video')
        return {'duration': duration, 'has_audio': 'audio' in kinds}
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MediaUnsupported('Media verification failed') from exc


def _candidate_expression(shortcode: str) -> str:
    # JSON scripts are examined inside the page; only correlated media URLs leave it.
    code = json.dumps(shortcode)
    return r'''(() => {
      const target = SHORTCODE; const found=[];
      const add = x => {if(typeof x==='string' && found.length<16) found.push(x)};
      let walked=0;
      for(const script of document.querySelectorAll('script[type="application/json"],script[type="application/ld+json"]')) {
        if(!script.textContent || script.textContent.length>2000000) continue;
        let data; try {data=JSON.parse(script.textContent)} catch (_) {continue}
        const queue=[data];
        while(queue.length && walked++<100000) {
          const node=queue.pop(); if(!node || typeof node!=='object') continue;
          if(node.code===target || node.shortcode===target) {
            if(Array.isArray(node.video_versions)) for(const item of node.video_versions) add(item.url);
            add(node.video_url);
          }
          for(const value of Object.values(node)) if(value && typeof value==='object') queue.push(value);
        }
      }
      return JSON.stringify({page_url:location.href,candidates:found});
    })()'''.replace('SHORTCODE', code)


def _fetch_expression(url: str, ranges: list[tuple[int, int]], *, single: bool) -> str:
    payload = json.dumps({'url': url, 'ranges': ranges}, ensure_ascii=True)
    # Each response is capped at CHUNK bytes. Request redirects are not followed.
    expression = r'''(async () => {
      const spec = PAYLOAD;
      const fetchPart = async ([first,last]) => {
        const response=await fetch(spec.url,{headers:{Range:`bytes=${first}-${last}`},redirect:'error',credentials:'omit'});
        const range=response.headers.get('content-range');
        if(response.status!==206) return {status:response.status,range,data:''};
        const buffer=await response.arrayBuffer();
        if(buffer.byteLength!==last-first+1) return {status:0,range,data:''};
        const bytes=new Uint8Array(buffer); let binary='';
        for(let i=0;i<bytes.length;i+=8192) binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
        return {status:response.status,range,data:btoa(binary)};
      };
      const results=await Promise.all(spec.ranges.map(fetchPart));
      return JSON.stringify(SINGLE ? results[0] : results);
    })()'''
    return expression.replace('SINGLE', 'true' if single else 'false').replace('PAYLOAD', payload)


async def _evaluate_json(client, expression: str, phase: str):
    try:
        raw = await client._evaluate(expression)
        return json.loads(raw)
    except Exception:
        # Protocol and JS exceptions may contain a signed media URL: do not expose them.
        raise MediaUnsupported(f'Obscura could not inspect or fetch this video (phase: {phase})') from None


async def prepare_obscura_media(client, post_url: str, output: str | Path) -> dict:
    async with client._media_lock:
        return await _prepare_obscura_media(client, post_url, output)


async def _prepare_obscura_media(client, post_url: str, output: str | Path) -> dict:
    canonical, shortcode = post_identity(post_url)
    await client.navigate(canonical)
    discovery = await _evaluate_json(client, _candidate_expression(shortcode), 'discover')
    try:
        _, current_shortcode = post_identity(discovery.get('page_url', ''))
        candidates = discovery.get('candidates', [])
    except (AttributeError, TypeError, ValueError):
        raise MediaUnsupported('The opened page is not the requested Instagram post') from None
    if current_shortcode != shortcode:
        raise MediaUnsupported('The opened page is not the requested Instagram post')
    if not isinstance(candidates, list):
        raise MediaUnsupported('No video was exposed by the requested post')
    candidates = [url for url in candidates if allowed_media_url(url)]
    if not candidates:
        raise MediaUnsupported('Obscura did not expose a usable video URL for this post')
    media_url = candidates[0]
    client.clear_cdn_responses()
    initial = await _evaluate_json(client, _fetch_expression(media_url, [(0, 0)], single=True), 'probe')
    _, total = _decode_range(_visible_range(client, initial, media_url, 0, 0), 0, 0, None)
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    digest = hashlib.sha256()
    try:
        with tempfile.NamedTemporaryFile(prefix='.obscura-media-', suffix='.part', dir=out.parent,
                                         delete=False) as stream:
            temporary = Path(stream.name)
            for group_start in range(0, total, CHUNK * PARALLEL):
                ranges = [(start, min(start + CHUNK, total) - 1)
                          for start in range(group_start, min(total, group_start + CHUNK * PARALLEL), CHUNK)]
                client.clear_cdn_responses()
                results = await _evaluate_json(client, _fetch_expression(media_url, ranges, single=False),
                                               f'batch-{group_start // (CHUNK * PARALLEL) + 1}')
                if not isinstance(results, list) or len(results) != len(ranges):
                    raise MediaUnsupported('Incomplete video segment batch')
                for response, (start, end) in zip(results, ranges):
                    data, _ = _decode_range(_visible_range(client, response, media_url, start, end), start, end, total)
                    stream.write(data)
                    digest.update(data)
        if temporary.stat().st_size != total:
            raise MediaUnsupported('The complete video size is incorrect')
        info = await probe_media(temporary)
        os.replace(temporary, out)
        return {'path': str(out.resolve()), 'sha256': digest.hexdigest(), 'size': total,
                'duration': info['duration'], 'has_audio': info['has_audio']}
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


async def wait_settled_snapshot(client, *, timeout: float = 15, interval: float = 0.5) -> dict:
    """Wait briefly for a nonempty stable DOM; empty or still-changing remains inconclusive."""
    deadline = asyncio.get_running_loop().time() + timeout
    previous = None
    latest = {}
    while True:
        latest = await client.snapshot()
        signature = (latest.get('text', ''), json.dumps(latest.get('links', []), ensure_ascii=False))
        if (signature[0] or latest.get('links')) and signature == previous:
            return {**latest, 'settled': True}
        previous = signature
        if asyncio.get_running_loop().time() >= deadline:
            return {**latest, 'settled': False}
        await asyncio.sleep(interval)
