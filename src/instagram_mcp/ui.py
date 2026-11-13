"""Bounded, Instagram-scoped UI controls for an already authenticated browser."""
from __future__ import annotations

import asyncio
import json
import math
import re
import secrets
from pathlib import Path

from .errors import ProtocolError
from .obscura import sanitize_snapshot, valid_instagram_url


class UIError(ProtocolError):
    pass


_KEYS = frozenset(('Enter', 'Escape', 'Tab', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
                   'Backspace', 'Delete', 'Home', 'End', 'Space'))
_EXTENSIONS = frozenset(('.jpg', '.jpeg', '.png', '.webp', '.mp4', '.mov'))


class InstagramUI:
    def __init__(self, client, upload_root: str | Path, verify_account):
        self.client = client
        self.upload_root = Path(upload_root).resolve()
        self.verify_account = verify_account
        self._refs = {}
        self._lock = asyncio.Lock()

    async def _observe(self) -> dict:
        self._refs.clear()
        snapshot = await self.client.snapshot()
        if not valid_instagram_url(snapshot.get('url', '')):
            raise UIError('The active page is not on Instagram')
        nonce = secrets.token_hex(12)
        expression = r'''(() => { /* OBSERVE_CONTROLS */
          for(const n of document.querySelectorAll('[data-instagram-ui-ref]')) n.removeAttribute('data-instagram-ui-ref');
          const controls=[]; const nonce=NONCE;
          for(const n of document.querySelectorAll('a[href],button,input,textarea,[role="button"],[role="textbox"],[contenteditable="true"]')) {
            if(controls.length>=120 || n.disabled) continue;
            const tag=n.tagName, type=(n.getAttribute('type')||'').toLowerCase();
            const fileInput=tag==='INPUT' && type==='file';
            const style=getComputedStyle(n); const r=n.getBoundingClientRect();
            if(!fileInput && (n.getAttribute('aria-hidden')==='true' || style.display==='none' || style.visibility==='hidden' || !r.width || !r.height)) continue;
            if(tag==='INPUT' && ['password','hidden'].includes(type)) continue;
            const marker=nonce+'-'+controls.length; n.setAttribute('data-instagram-ui-ref',marker);
            const label=(n.getAttribute('aria-label')||n.getAttribute('placeholder')||n.innerText||'').trim().slice(0,160);
            controls.push({marker,tag,type,role:(n.getAttribute('role')||'').slice(0,40),label});
          }
          return JSON.stringify(controls);
        })()'''.replace('NONCE', json.dumps(nonce))
        try:
            values = json.loads(await self.client._evaluate(expression))
            if not isinstance(values, list):
                raise ValueError()
            root = (await self.client._command('DOM.getDocument', {'depth': 1}, target=True))['root']['nodeId']
            controls = []
            for item in values[:120]:
                if not isinstance(item, dict) or not isinstance(item.get('marker'), str):
                    continue
                marker = item['marker']
                # Marker syntax is locally generated and cannot inject CSS selectors.
                if not re.fullmatch(re.escape(nonce) + r'-\d{1,3}', marker):
                    continue
                selector = f'[data-instagram-ui-ref="{marker}"]'
                result = await self.client._command('DOM.querySelector', {'nodeId': root, 'selector': selector}, target=True)
                node_id = result.get('nodeId')
                if not isinstance(node_id, int) or node_id <= 0:
                    continue
                ref = secrets.token_urlsafe(18)
                self._refs[ref] = {'selector': selector, 'node_id': node_id, 'url': snapshot['url']}
                safe_label = sanitize_snapshot({'url': snapshot['url'], 'text': item.get('label', ''), 'links': []})['text']
                controls.append({'ref': ref, 'tag': str(item.get('tag', ''))[:20],
                                 'type': str(item.get('type', ''))[:40], 'role': str(item.get('role', ''))[:40],
                                 'label': safe_label[:160]})
            return {'page': snapshot, 'controls': controls}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._refs.clear()
            raise UIError('Could not inspect Instagram controls') from exc

    async def observe(self) -> dict:
        async with self._lock:
            return await self._observe()

    async def _account(self, expected_account: str) -> None:
        if not isinstance(expected_account, str) or not re.fullmatch(r'[A-Za-z0-9._]{1,30}', expected_account):
            raise UIError('Provide the expected Instagram account')
        if not await self.verify_account(expected_account):
            raise UIError('The active account could not be verified')

    async def _target(self, ref: str) -> tuple[dict, dict]:
        entry = self._refs.get(ref)
        if not entry:
            raise UIError('This control reference is stale; inspect the page again')
        selector = entry['selector']
        root = (await self.client._command('DOM.getDocument', {'depth': 1}, target=True))['root']['nodeId']
        node = await self.client._command('DOM.querySelector', {'nodeId': root, 'selector': selector}, target=True)
        if node.get('nodeId') != entry['node_id']:
            raise UIError('The control changed; inspect the page again')
        expression = r'''(() => {
          const n=document.querySelector(SELECTOR); if(!n) return JSON.stringify({connected:false});
          const a=n.closest('a[href]'); const form=n.form||n.closest('form'); const r=n.getBoundingClientRect();
          const x=r.x+r.width/2, y=r.y+r.height/2;
          const visible=r.width>0 && r.height>0 && x>=0 && y>=0 && x<window.innerWidth && y<window.innerHeight;
          const hit=visible ? document.elementFromPoint(x,y) : null;
          return JSON.stringify({url:location.href,connected:n.isConnected,disabled:!!n.disabled,
            tag:n.tagName,type:(n.getAttribute('type')||'').toLowerCase(),role:n.getAttribute('role')||'',
            editable:!!n.isContentEditable || n.getAttribute('contenteditable')==='true',
            name:n.getAttribute('name')||'',autocomplete:n.getAttribute('autocomplete')||'',
            href:a ? a.href : '',action:n.getAttribute('formaction') ? new URL(n.getAttribute('formaction'),location.href).href : (form ? form.action : ''),
            x,y,visible,unobstructed:!!hit && (hit===n || n.contains(hit))});
        })()'''.replace('SELECTOR', json.dumps(selector))
        try:
            meta = json.loads(await self.client._evaluate(expression))
        except (ValueError, TypeError) as exc:
            raise UIError('Could not inspect the selected control') from exc
        if not isinstance(meta, dict) or not meta.get('connected') or meta.get('disabled'):
            raise UIError('The selected control is unavailable')
        if not valid_instagram_url(meta.get('url', '')) or meta['url'].split('?',1)[0].split('#',1)[0] != entry['url'].split('?',1)[0].split('#',1)[0]:
            raise UIError('The page changed; inspect it again')
        for field in ('href', 'action'):
            if meta.get(field) and not valid_instagram_url(meta[field]):
                raise UIError('This control would leave Instagram')
        if self._sensitive(meta):
            raise UIError('Credentials and verification codes must be entered in the login browser')
        return entry, meta

    @staticmethod
    def _sensitive(meta: dict) -> bool:
        if meta.get('type') in ('password', 'hidden'):
            return True
        hint = str(meta.get('name', '')) + ' ' + str(meta.get('autocomplete', ''))
        return bool(re.search(r'password|passwd|one.time.code|(?:^|[_ -])otp(?:$|[_ -])|verification.?code|security.?code', hint, re.I))

    async def _focus(self, selector: str) -> None:
        value = await self.client._evaluate("(() => {const n=document.querySelector(" + json.dumps(selector) +
                    ");if(!n||!n.isConnected)return false;n.focus();return document.activeElement===n})()")
        if value is not True:
            raise UIError('The selected control could not be focused')

    async def _select_text(self, selector: str, meta: dict) -> None:
        if meta.get('tag') in ('INPUT', 'TEXTAREA'):
            script = ("(() => { /* SELECT_TEXT */ const n=document.querySelector(" + json.dumps(selector) +
                      "); try { n.setSelectionRange(0,n.value.length);return n.selectionStart===0 && n.selectionEnd===n.value.length; } catch(e) {return false;} })()")
        elif meta.get('editable'):
            script = ("(() => { /* SELECT_TEXT */ const n=document.querySelector(" + json.dumps(selector) +
                      ");try {const r=document.createRange();r.selectNodeContents(n);const s=window.getSelection();"
                      "s.removeAllRanges();s.addRange(r);return s.rangeCount===1;} catch(e) {return false;} })()")
        else:
            raise UIError('The selected control does not support text selection')
        if await self.client._evaluate(script) is not True:
            raise UIError('The selected control does not support replacing text')

    async def click(self, ref: str, expected_account: str) -> dict:
        async with self._lock:
            try:
                await self._account(expected_account)
                _, meta = await self._target(ref)
                if meta.get('tag') == 'INPUT' and meta.get('type') == 'file':
                    raise UIError('Use upload for a file control')
                if meta.get('visible') is not True or meta.get('unobstructed') is not True:
                    raise UIError('The control is hidden or covered; inspect the page again')
                x, y = meta.get('x'), meta.get('y')
                if any(not isinstance(v, (float, int)) or not math.isfinite(v) or v < 0 for v in (x,y)):
                    raise UIError('The control is outside the visible page')
                for action in ('mousePressed', 'mouseReleased'):
                    await self.client._command('Input.dispatchMouseEvent', {'type': action, 'x': x, 'y': y,
                                               'button': 'left', 'clickCount': 1}, target=True)
            finally:
                self._refs.clear()
            return await self._observe()

    async def fill(self, ref: str, text: str, expected_account: str) -> dict:
        async with self._lock:
            try:
                await self._account(expected_account)
                entry, meta = await self._target(ref)
                if not isinstance(text, str) or len(text) > 10000:
                    raise UIError('Text must contain at most 10000 characters')
                if meta.get('tag') not in ('INPUT','TEXTAREA') and meta.get('role') != 'textbox':
                    raise UIError('The selected control is not editable')
                if meta.get('type') == 'file':
                    raise UIError('Use upload for a file control')
                await self._focus(entry['selector'])
                await self._select_text(entry['selector'], meta)
                await self.client._command('Input.insertText', {'text': text}, target=True)
                actual = ("(() => { /* VERIFY_FILL */ const n=document.querySelector(" + json.dumps(entry['selector']) +
                          ");return !!n && (n.tagName==='INPUT'||n.tagName==='TEXTAREA'?n.value:n.innerText)===" + json.dumps(text) + ";})()")
                if await self.client._evaluate(actual) is not True:
                    raise UIError('The control did not retain the requested text; inspect before retrying')
            finally:
                self._refs.clear()
            return await self._observe()

    async def press(self, ref: str, key: str, expected_account: str) -> dict:
        async with self._lock:
            try:
                await self._account(expected_account)
                entry, _ = await self._target(ref)
                if key not in _KEYS:
                    raise UIError('This key is not supported')
                await self._focus(entry['selector'])
                for event_type in ('keyDown','keyUp'):
                    await self.client._command('Input.dispatchKeyEvent', {'type':event_type,'key':key,'code':key}, target=True)
            finally:
                self._refs.clear()
            return await self._observe()

    async def scroll(self, direction: str, expected_account: str) -> dict:
        async with self._lock:
            try:
                await self._account(expected_account)
                if direction not in ('up','down'):
                    raise UIError('Direction must be up or down')
                state = await self.client.snapshot()
                if not valid_instagram_url(state.get('url','')):
                    raise UIError('The active page is not on Instagram')
                await self.client._command('Input.dispatchMouseEvent', {'type':'mouseWheel', 'x':200,'y':200,
                    'deltaX':0,'deltaY':-600 if direction == 'up' else 600}, target=True)
            finally:
                self._refs.clear()
            return await self._observe()

    async def upload(self, ref: str, files: list[str], expected_account: str) -> dict:
        async with self._lock:
            try:
                await self._account(expected_account)
                entry, meta = await self._target(ref)
                if meta.get('tag') != 'INPUT' or meta.get('type') != 'file':
                    raise UIError('The selected control is not a file input')
                if not isinstance(files,list) or not 1 <= len(files) <= 10 or any(not isinstance(item,str) for item in files):
                    raise UIError('Choose one to ten media files')
                paths = [Path(item).resolve() for item in files]
                if any(not path.is_relative_to(self.upload_root) or not path.is_file()
                       or path.suffix.lower() not in _EXTENSIONS or not 0 < path.stat().st_size <= 100*1024*1024 for path in paths):
                    raise UIError('All files must be supported media within the upload folder')
                if sum(path.stat().st_size for path in paths) > 200*1024*1024:
                    raise UIError('The combined upload is too large')
                if not self.client.allow_file_access:
                    raise UIError('File upload is unsupported without explicit file access')
                await self.client._command('DOM.setFileInputFiles', {'nodeId': entry['node_id'],
                                           'files':[str(path) for path in paths]}, target=True)
                expected = [{'name': path.name, 'size': path.stat().st_size} for path in paths]
                verify = ("(() => { /* VERIFY_UPLOAD */ const n=document.querySelector(" + json.dumps(entry['selector']) +
                          ");const want=" + json.dumps(expected, ensure_ascii=True) +
                          ";return !!n&&!!n.files&&n.files.length===want.length&&want.every((v,i)=>"
                          "n.files[i].name===v.name&&n.files[i].size===v.size)})()")
                if await self.client._evaluate(verify) is not True:
                    raise UIError('File selection was not confirmed; inspect before retrying')
            finally:
                self._refs.clear()
            return await self._observe()
