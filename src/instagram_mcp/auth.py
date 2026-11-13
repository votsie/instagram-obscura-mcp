"""Headed manual login and narrowly scoped in-memory session transfer."""
from __future__ import annotations

from urllib.parse import urlsplit

from .errors import LoginRequired

INSTAGRAM_ORIGINS = frozenset(('https://instagram.com', 'https://www.instagram.com'))


def instagram_domain(domain: object) -> bool:
    if not isinstance(domain, str):
        return False
    domain = domain.lower().lstrip('.')
    return domain == 'instagram.com' or domain.endswith('.instagram.com')


def filter_instagram_state(state: dict, session_storage: dict | None = None,
                           session_origin: str = 'https://www.instagram.com') -> dict:
    cookies = []
    for cookie in state.get('cookies', []):
        if not isinstance(cookie, dict) or not instagram_domain(cookie.get('domain')):
            continue
        if not all(isinstance(cookie.get(key), str) for key in ('name', 'value', 'domain', 'path')):
            continue
        result = {key: cookie[key] for key in ('name', 'value', 'domain', 'path', 'secure', 'httpOnly', 'sameSite')
                  if key in cookie}
        if isinstance(cookie.get('expires'), (float, int)) and cookie['expires'] > 0:
            result['expires'] = cookie['expires']
        cookies.append(result)
    local_storage = {}
    for item in state.get('origins', []):
        if not isinstance(item, dict) or item.get('origin') not in INSTAGRAM_ORIGINS:
            continue
        values = item.get('localStorage', [])
        if isinstance(values, list):
            local_storage[item['origin']] = [entry for entry in values if isinstance(entry, dict)
                                            and isinstance(entry.get('name'), str)
                                            and isinstance(entry.get('value'), str)]
    if session_origin not in INSTAGRAM_ORIGINS or not isinstance(session_storage, dict):
        session_storage = {}
    else:
        session_storage = {key: value for key, value in session_storage.items()
                           if isinstance(key, str) and isinstance(value, str)}
    return {'cookies': cookies, 'local_storage': local_storage, 'session_storage': session_storage,
            'session_origin': session_origin if session_origin in INSTAGRAM_ORIGINS else 'https://www.instagram.com'}


def login_status(cookies: list, url: str) -> dict:
    try:
        parsed = urlsplit(url)
        safe_page = (parsed.scheme == 'https' and parsed.netloc in ('instagram.com', 'www.instagram.com')
                     and not parsed.path.startswith(('/accounts/login', '/accounts/emailsignup',
                         '/accounts/password', '/accounts/two_factor', '/challenge/', '/checkpoint/')))
    except (ValueError, AttributeError):
        safe_page = False
    has_session = any(isinstance(cookie, dict) and cookie.get('name') == 'sessionid'
                      and bool(cookie.get('value')) and instagram_domain(cookie.get('domain')) for cookie in cookies)
    return {'authenticated': bool(safe_page and has_session), 'account': None}


class AuthSession:
    """A short-lived separate Chrome session. Passwords and OTPs are entered by the user."""

    def __init__(self, timeout_ms: int = 60000):
        self.timeout_ms = timeout_ms
        self._playwright = self._browser = self._context = self._page = None

    async def start(self) -> None:
        if self._browser:
            raise RuntimeError('Login session is already active')
        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(channel='chrome', headless=False)
            self._context = await self._browser.new_context()
            self._page = await self._context.new_page()
            await self._page.goto('https://www.instagram.com/', wait_until='domcontentloaded', timeout=self.timeout_ms)
        except Exception as exc:
            await self.close()
            raise RuntimeError('Could not open the Instagram login browser') from exc

    async def status(self) -> dict:
        if not self._context or not self._page:
            raise RuntimeError('Login session is not active')
        cookies = await self._context.cookies(['https://instagram.com/', 'https://www.instagram.com/'])
        return login_status(cookies, self._page.url)

    async def finish(self) -> dict:
        if not (await self.status())['authenticated']:
            raise LoginRequired('Complete Instagram login in the open browser first')
        try:
            state = await self._context.storage_state()
            parsed = urlsplit(self._page.url)
            origin = f'{parsed.scheme}://{parsed.netloc}'
            session = await self._page.evaluate('() => Object.fromEntries(Object.entries(sessionStorage))')
            result = filter_instagram_state(state, session, origin)
            result['user_agent'] = await self._page.evaluate('() => navigator.userAgent')
            return result
        finally:
            await self.close()

    async def close(self) -> None:
        browser, playwright = self._browser, self._playwright
        self._page = self._context = self._browser = self._playwright = None
        try:
            if browser:
                await browser.close()
        finally:
            if playwright:
                await playwright.stop()
