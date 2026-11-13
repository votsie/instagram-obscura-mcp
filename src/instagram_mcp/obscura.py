"""Bounded CDP adapter for one local, token-protected Obscura process."""
from __future__ import annotations

import asyncio
import collections
import csv
import io
import json
import os
import re
import secrets
import signal
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from .auth import INSTAGRAM_ORIGINS, instagram_domain
from .errors import ProtocolError


def private_profile(path: Path) -> None:
    """Create a credential directory and remove inherited access before use."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt':
        os.chmod(path, 0o700)
        return
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        who = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], capture_output=True,
                             text=True, timeout=10, check=True, creationflags=flags)
        row = next(csv.reader(io.StringIO(who.stdout)))
        sid = row[1]
        if not re.fullmatch(r'S-1-(?:\d+-)+\d+', sid):
            raise ValueError('Invalid user SID')
        # Set an entirely new protected DACL, retaining only the logged-in user's SID.
        script = ("$p=$env:INSTAGRAM_MCP_PROFILE_PATH;$sid=$env:INSTAGRAM_MCP_PROFILE_SID;"
                  "$s=New-Object System.Security.AccessControl.DirectorySecurity;"
                  "$s.SetAccessRuleProtection($true,$false);"
                  "$s.SetOwner((New-Object System.Security.Principal.SecurityIdentifier($sid)));"
                  "$r=New-Object System.Security.AccessControl.FileSystemAccessRule("
                  "(New-Object System.Security.Principal.SecurityIdentifier($sid)),"
                  "'FullControl','ContainerInherit,ObjectInherit','None','Allow');"
                  "$s.AddAccessRule($r);$d=New-Object System.IO.DirectoryInfo($p);$d.SetAccessControl($s)")
        env = os.environ.copy()
        env['INSTAGRAM_MCP_PROFILE_PATH'] = str(path)
        env['INSTAGRAM_MCP_PROFILE_SID'] = sid
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                       capture_output=True, timeout=15, check=True, creationflags=flags, env=env)
    except (OSError, subprocess.SubprocessError, IndexError, StopIteration, ValueError) as exc:
        raise RuntimeError('Could not restrict the private browser profile') from exc


def valid_instagram_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == 'https' and parsed.hostname in ('instagram.com', 'www.instagram.com')
                and parsed.username is None and parsed.password is None and parsed.port is None)
    except (ValueError, TypeError):
        return False


def _safe_link(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return ''
        host = parsed.hostname.lower()
        path = parsed.path
        if instagram_domain(host) and path.startswith(('/challenge/', '/checkpoint/', '/accounts/password/')):
            path = '/challenge/'
        return f'{parsed.scheme}://{host}{path}'
    except (ValueError, TypeError):
        return ''


def sanitize_snapshot(result: dict) -> dict:
    raw_url = result.get('url', '')
    clean_url = _safe_link(raw_url) if raw_url != 'about:blank' else 'about:blank'
    if clean_url.endswith('/challenge/'):
        return {'url': clean_url, 'title': '', 'text': '', 'links': [], 'status': 'challenge'}
    def scrub(value):
        if not isinstance(value, str):
            return ''
        return re.sub(r'https?://[^\s<>"\']+', lambda match: _safe_link(match.group(0)), value)
    links = []
    for item in result.get('links', []):
        if not isinstance(item, dict):
            continue
        link = _safe_link(item.get('href', ''))
        if link and instagram_domain(urlsplit(link).hostname):
            links.append({'text': scrub(item.get('text', '')), 'href': link})
    return {'url': clean_url, 'title': scrub(result.get('title', '')),
            'text': scrub(result.get('text', '')), 'links': links}


def create_process_job():
    import win32job
    job = win32job.CreateJobObject(None, '')
    try:
        info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        info['BasicLimitInformation']['LimitFlags'] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
        return job
    except Exception:
        job.Close()
        raise


def assign_process_job(job, pid: int) -> None:
    import win32api
    import win32con
    import win32job
    handle = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, pid)
    try:
        win32job.AssignProcessToJobObject(job, handle)
    finally:
        handle.Close()


class ProfileBusy(RuntimeError):
    pass


class ProfileLock:
    """Cross-process exclusive lock for a profile for the full engine lifetime."""

    def __init__(self, path: Path):
        self.path = path
        self._file = None

    def acquire(self) -> None:
        if self._file:
            raise RuntimeError('Profile lock is already held')
        handle = self.path.open('a+b')
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise ProfileBusy('Instagram profile is already in use') from exc
        self._file = handle

    def release(self) -> None:
        if not self._file:
            return
        handle, self._file = self._file, None
        try:
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


class ObscuraClient:
    def __init__(self, binary: str | Path, storage_dir: str | Path, *, timeout: float = 30,
                 diagnostics: bool = False, registration_compat: bool = False, allow_file_access: bool = False):
        self.binary = Path(binary).resolve()
        self.storage_dir = Path(storage_dir).resolve()
        self.timeout = timeout
        self.diagnostics = diagnostics
        self.registration_compat = registration_compat
        if not isinstance(allow_file_access, bool):
            raise ValueError('allow_file_access must be a boolean')
        self.allow_file_access = allow_file_access
        self._token = None
        self._process = self._socket = self._session_id = self._ready_dir = self._job = None
        self._job_assigned = False
        self._profile_lock = None
        self._counter = 0
        self._lock = asyncio.Lock()
        self._media_lock = asyncio.Lock()
        self._media_responses = collections.deque(maxlen=512)

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def start(self) -> None:
        if self._process:
            raise RuntimeError('Obscura already started')
        if not self.binary.is_file():
            raise RuntimeError('Obscura executable is missing')
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            lock = ProfileLock(self.storage_dir / '.session.lock')
            lock.acquire()
            self._profile_lock = lock
            private_profile(self.storage_dir)
            self._ready_dir = tempfile.TemporaryDirectory(prefix='obscura-ready-')
            ready = Path(self._ready_dir.name) / 'ready.json'
            self._token = secrets.token_hex(32)
            env = os.environ.copy()
            env['OBSCURA_CDP_TOKEN'] = self._token
            env.pop('OBSCURA_CDP_ALLOWED_ORIGINS', None)
            options = ({'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
                       if os.name == 'nt' else {'start_new_session': True})
            if os.name == 'nt':
                self._job = create_process_job()
            diagnostic_file = None
            try:
                if self.diagnostics:
                    diagnostic_file = (self.storage_dir / 'engine-errors.log').open('wb')
                self._process = await asyncio.create_subprocess_exec(
                    str(self.binary), 'serve', '--host', '127.0.0.1', '--port', '0', '--workers', '1',
                    '--ready-file', str(ready), '--storage-dir', str(self.storage_dir),
                    *(['--allow-file-access'] if self.allow_file_access else []),
                    stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                    stderr=diagnostic_file if diagnostic_file else asyncio.subprocess.DEVNULL, env=env, **options)
            finally:
                if diagnostic_file:
                    diagnostic_file.close()
            if self._job:
                assign_process_job(self._job, self._process.pid)
                self._job_assigned = True
            deadline = asyncio.get_running_loop().time() + self.timeout
            while not ready.is_file():
                if self._process.returncode is not None:
                    raise RuntimeError('Obscura exited during startup')
                if asyncio.get_running_loop().time() >= deadline:
                    raise RuntimeError('Obscura did not become ready')
                await asyncio.sleep(0.1)
            data = json.loads(ready.read_text(encoding='utf-8'))
            port = data.get('port')
            if (data.get('pid') != self._process.pid or data.get('host') != '127.0.0.1'
                    or not isinstance(port, int) or not 0 < port < 65536
                    or data.get('websocket_path') != '/devtools/browser'):
                raise RuntimeError('Obscura returned invalid readiness metadata')
            from websockets.asyncio.client import connect
            self._socket = await connect(f'ws://127.0.0.1:{port}/devtools/browser',
                                         additional_headers={'Authorization': f'Bearer {self._token}'},
                                         open_timeout=self.timeout, close_timeout=3, max_size=16 * 1024 * 1024)
            target = await self._command('Target.createTarget', {'url': 'about:blank'})
            attached = await self._command('Target.attachToTarget', {'targetId': target['targetId'], 'flatten': True})
            self._session_id = attached['sessionId']
            await self._command('Network.enable', {}, target=True)
            await self._command('Page.enable', {}, target=True)
            await self.install_registration_compat()
            await self.restore_user_agent()
        except BaseException as exc:
            await self.close()
            if isinstance(exc, (ProfileBusy, asyncio.CancelledError)):
                raise
            raise RuntimeError('Could not start the local Obscura browser') from exc

    async def _command(self, method: str, params: dict, *, target: bool = False) -> dict:
        if self._socket is None:
            raise ProtocolError('Obscura connection is unavailable')
        async with self._lock:
            self._counter += 1
            message = {'id': self._counter, 'method': method, 'params': params}
            if target:
                if not self._session_id:
                    raise ProtocolError('Obscura target is unavailable')
                message['sessionId'] = self._session_id
            try:
                async with asyncio.timeout(self.timeout):
                    await self._socket.send(json.dumps(message, ensure_ascii=False))
                    while True:
                        reply = json.loads(await self._socket.recv())
                        if reply.get('id') == self._counter:
                            break
                        self._capture_network_event(reply)
            except Exception as exc:
                sent = getattr(getattr(exc, 'sent', None), 'code', None)
                received = getattr(getattr(exc, 'rcvd', None), 'code', None)
                self._diagnostic({'method': method, 'event': 'transport_error', 'error_type': type(exc).__name__,
                                  'sent_code': sent if isinstance(sent, int) else None,
                                  'received_code': received if isinstance(received, int) else None})
                raise ProtocolError(f'Obscura command {method} failed or timed out') from exc
            if 'error' in reply:
                error = reply.get('error') if isinstance(reply.get('error'), dict) else {}
                code = error.get('code') if isinstance(error.get('code'), int) else None
                self._diagnostic({'method': method, 'event': 'protocol_error', 'code': code})
                raise ProtocolError(f'Obscura rejected {method}')
            return reply.get('result', {})

    def _diagnostic(self, event: dict) -> None:
        if not self.diagnostics:
            return
        try:
            with (self.storage_dir / 'cdp-diagnostics.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(event, ensure_ascii=True) + '\n')
        except OSError:
            pass

    def _capture_network_event(self, event: dict) -> None:
        if (event.get('method') != 'Network.responseReceived'
                or event.get('sessionId', self._session_id) != self._session_id):
            return
        response = event.get('params', {}).get('response', {})
        if not isinstance(response, dict) or response.get('status') != 206:
            return
        url = response.get('url')
        headers = response.get('headers')
        if not isinstance(url, str) or not isinstance(headers, dict):
            return
        try:
            parsed = urlsplit(url)
            host = parsed.hostname or ''
            if (parsed.scheme != 'https' or parsed.username is not None or parsed.password is not None
                    or parsed.port is not None or not (host == 'cdninstagram.com'
                    or host.endswith('.cdninstagram.com') or host == 'fbcdn.net' or host.endswith('.fbcdn.net'))):
                return
        except ValueError:
            return
        content_range = next((value for key, value in headers.items() if isinstance(key, str)
                              and key.lower() == 'content-range'), None)
        if isinstance(content_range, str) and re.fullmatch(r'bytes \d+-\d+/\d+', content_range):
            # Keep the signed URL transiently for exact correlation; retain no other headers.
            self._media_responses.append((url, content_range))

    def get_cdn_content_range(self, url: str, start: int, end: int) -> str | None:
        prefix = f'bytes {start}-{end}/'
        return next((header for candidate, header in reversed(self._media_responses)
                     if candidate == url and header.startswith(prefix)), None)

    def clear_cdn_responses(self) -> None:
        self._media_responses.clear()

    async def _evaluate(self, expression: str):
        response = await self._command('Runtime.evaluate', {'expression': expression,
                                      'returnByValue': True, 'awaitPromise': True}, target=True)
        if 'exceptionDetails' in response or response.get('result', {}).get('subtype') == 'error':
            detail = response.get('exceptionDetails', {})
            exception = detail.get('exception', {}) if isinstance(detail, dict) else {}
            name = exception.get('className', '') if isinstance(exception, dict) else ''
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}', name):
                name = 'unknown'
            self._diagnostic({'method': 'Runtime.evaluate', 'event': 'javascript_exception', 'error_type': name})
            raise ProtocolError('Page evaluation failed')
        return response.get('result', {}).get('value')

    async def install_registration_compat(self) -> None:
        """Expose the missing type for feature checks, without creating service workers."""
        if not self.registration_compat:
            return
        source = ("if (typeof globalThis.ServiceWorkerRegistration === 'undefined') {"
                  " class ServiceWorkerRegistration { constructor() { throw new TypeError('Illegal constructor'); } }"
                  " Object.defineProperty(globalThis, 'ServiceWorkerRegistration',"
                  " {value:ServiceWorkerRegistration,writable:true,configurable:true}); }")
        result = await self._command('Page.addScriptToEvaluateOnNewDocument', {'source': source}, target=True)
        if not result.get('identifier'):
            raise ProtocolError('Could not install the compatibility check')

    @staticmethod
    def _validate_user_agent(value: str) -> None:
        if (not isinstance(value, str) or not value or len(value) > 512
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise ValueError('Invalid browser user agent')

    def save_user_agent(self, value: str) -> None:
        self._validate_user_agent(value)
        target = self.storage_dir / 'user-agent.txt'
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', prefix='.ua-',
                                         dir=self.storage_dir, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(value)
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    async def restore_user_agent(self) -> None:
        path = self.storage_dir / 'user-agent.txt'
        if path.exists():
            if path.stat().st_size > 512:
                raise ValueError('Invalid browser user agent')
            value = path.read_text(encoding='utf-8')
            self._validate_user_agent(value)
            await self._command('Network.setUserAgentOverride', {'userAgent': value}, target=True)

    async def navigate(self, url: str) -> None:
        if not valid_instagram_url(url):
            raise ValueError('Only HTTPS Instagram pages can be opened')
        navigation = await self._command('Page.navigate', {'url': url}, target=True)
        if navigation.get('errorText'):
            raise ProtocolError('Instagram navigation failed')
        try:
            async with asyncio.timeout(self.timeout):
                while True:
                    raw = await self._evaluate('JSON.stringify({url:location.href,ready:document.readyState})')
                    try:
                        document = json.loads(raw)
                    except (ValueError, TypeError):
                        document = {}
                    current = document.get('url', '') if isinstance(document, dict) else ''
                    if current and current != 'about:blank' and not valid_instagram_url(current):
                        raise ProtocolError('Instagram redirected to an unsupported origin')
                    if valid_instagram_url(current) and document.get('ready') in ('interactive', 'complete'):
                        break
                    await asyncio.sleep(0.2)
        except TimeoutError as exc:
            raise ProtocolError('Instagram page did not become ready') from exc

    async def import_instagram_state(self, state: dict) -> None:
        if not isinstance(state, dict) or not isinstance(state.get('cookies'), list):
            raise ValueError('Invalid session state')
        local = state.get('local_storage', {})
        session = state.get('session_storage', {})
        session_origin = state.get('session_origin', 'https://www.instagram.com')
        if (not isinstance(local, dict) or any(origin not in INSTAGRAM_ORIGINS for origin in local)
                or not isinstance(session, dict) or session_origin not in INSTAGRAM_ORIGINS):
            raise ValueError('Session state contains an unsupported origin')
        cookies = state['cookies']
        if any(not isinstance(c, dict) or not instagram_domain(c.get('domain')) for c in cookies):
            raise ValueError('Session state contains an unsupported cookie')
        if not any(c.get('name') == 'sessionid' and c.get('value') for c in cookies):
            raise ValueError('No Instagram login session was provided')
        for origin, entries in local.items():
            if not isinstance(entries, list) or any(not isinstance(item, dict)
                or not isinstance(item.get('name'), str) or not isinstance(item.get('value'), str) for item in entries):
                raise ValueError('Invalid Instagram local storage')
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in session.items()):
            raise ValueError('Invalid Instagram session storage')
        user_agent = state.get('user_agent')
        if user_agent is not None:
            self._validate_user_agent(user_agent)
            await self._command('Network.setUserAgentOverride', {'userAgent': user_agent}, target=True)
        await self._command('Network.setCookies', {'cookies': cookies}, target=True)
        payload = json.dumps({'local': local, 'session': session, 'sessionOrigin': session_origin}, ensure_ascii=True)
        preload = ("(() => { const d = " + payload + "; const l = d.local[location.origin] || [];"
                   " for (const p of l) localStorage.setItem(p.name,p.value);"
                   " if(location.origin===d.sessionOrigin) for (const [k,v] of Object.entries(d.session))"
                   " sessionStorage.setItem(k,v); })();")
        installed = await self._command('Page.addScriptToEvaluateOnNewDocument', {'source': preload}, target=True)
        identifier = installed.get('identifier')
        if not identifier:
            raise ProtocolError('Could not prepare Instagram session storage')
        try:
            for origin in sorted(set(local) | {session_origin}):
                await self.navigate(origin + '/')
        finally:
            await self._command('Page.removeScriptToEvaluateOnNewDocument', {'identifier': identifier}, target=True)
        if user_agent is not None:
            self.save_user_agent(user_agent)

    async def snapshot(self) -> dict:
        expression = ("JSON.stringify({url:location.href,title:document.title,"
                      "text:(document.body?.innerText||'').slice(0,30000),"
                      "links:Array.from(document.querySelectorAll('a[href]')).slice(0,150)"
                      ".map(a=>({text:(a.innerText||'').slice(0,160),href:a.href}))})")
        raw = await self._evaluate(expression)
        try:
            result = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise ProtocolError('Could not read the Instagram page') from exc
        if not isinstance(result, dict):
            raise ProtocolError('Could not read the Instagram page')
        return sanitize_snapshot(result)

    async def close(self) -> None:
        if self._socket:
            try:
                await self._socket.close()
            except Exception:
                pass
            self._socket = None
        process, self._process = self._process, None
        job, self._job = self._job, None
        assigned, self._job_assigned = self._job_assigned, False
        cleanup_failed = False
        try:
            if job:
                try:
                    job.Close()  # Kill-on-close applies even when the original parent has exited.
                except Exception:
                    cleanup_failed = True
            if process and os.name != 'nt':
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                except OSError:
                    cleanup_failed = True
            if process and os.name == 'nt' and not assigned and process.returncode is None:
                try:
                    killer = await asyncio.create_subprocess_exec('taskkill', '/PID', str(process.pid), '/T', '/F',
                                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                                creationflags=subprocess.CREATE_NO_WINDOW)
                    result = await asyncio.wait_for(killer.wait(), timeout=10)
                    if result != 0 and process.returncode is None:
                        cleanup_failed = True
                except (OSError, asyncio.TimeoutError):
                    cleanup_failed = True
            elif process and os.name == 'nt' and not assigned:
                # An exited, never-assigned parent can no longer prove its descendants were reaped.
                cleanup_failed = True
            if process and process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    try:
                        if os.name == 'nt':
                            process.kill()
                        else:
                            os.killpg(process.pid, signal.SIGKILL)
                        await asyncio.wait_for(process.wait(), timeout=5)
                    except (OSError, asyncio.TimeoutError):
                        cleanup_failed = True
            if process and os.name != 'nt':
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError:
                    cleanup_failed = True
        finally:
            if self._ready_dir:
                self._ready_dir.cleanup()
                self._ready_dir = None
            self._token = self._session_id = None
            self._media_responses.clear()
        if cleanup_failed:
            raise RuntimeError('Could not verify Obscura process cleanup')
        if self._profile_lock:
            self._profile_lock.release()
            self._profile_lock = None
