import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')


@pytest.mark.skipif(NODE is None, reason='Node.js is needed only for this offline browser-script test')
def test_analytics_loader_in_a_synthetic_browser():
    result = subprocess.run([NODE, '--test', str(ROOT / 'tests' / 'site_analytics.test.cjs')],
                            cwd=ROOT, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_public_check_accepts_exact_google_verification_but_rejects_forgery(tmp_path):
    import sys
    from pathlib import Path

    source = (ROOT / 'scripts' / 'check_public.py').read_text(encoding='utf-8')
    script = tmp_path / 'scripts' / 'check_public.py'
    script.parent.mkdir()
    script.write_text(source, encoding='utf-8')
    (tmp_path / 'site').mkdir()
    name = 'google0123456789abcdef.html'
    verify = tmp_path / 'site' / name
    verify.write_text('google-site-verification: ' + name, encoding='utf-8')
    args = [sys.executable, str(script)]
    good = subprocess.run(args, cwd=tmp_path, text=True, capture_output=True)
    assert good.returncode == 0, good.stdout + good.stderr
    verify.write_text('<html>Untrusted</html>', encoding='utf-8')
    bad = subprocess.run(args, cwd=tmp_path, text=True, capture_output=True)
    assert bad.returncode != 0


def _make_public_fixture(root):
    import html
    import json
    from pathlib import Path

    (root / 'scripts').mkdir()
    (root / 'scripts' / 'check_public.py').write_text(
        (ROOT / 'scripts' / 'check_public.py').read_text(encoding='utf-8'), encoding='utf-8')
    (root / 'site' / 'assets').mkdir(parents=True)
    (root / 'site' / 'assets' / 'analytics.js').write_text('// fixture', encoding='utf-8')
    site = root / 'site'
    base = 'https://votsie.github.io/instagram-obscura-mcp/'
    paths = ['', 'ru/', 'installation/', 'ru/installation/', 'reels/', 'ru/reels/']
    token = '0123456789abcdef0123456789abcdef'
    for page in paths:
        relative = page.removeprefix('ru/') if page.startswith('ru/') else page
        alt_en, alt_ru = base + relative, base + 'ru/' + relative
        canonical = base + page
        depth = len(Path(page).parts)
        asset = '../' * depth + 'assets/analytics.js'
        metadata = ''.join(f'<meta name="{key}" content="synthetic">' for key in
                           ('description', 'og:title', 'og:description', 'og:image', 'twitter:card'))
        links = f'<link rel="canonical" href="{canonical}">'
        for lang, url in [('en', alt_en), ('ru', alt_ru), ('x-default', alt_en)]:
            links += f'<link rel="alternate" hreflang="{lang}" href="{url}">'
        schema = json.dumps({'@type': 'SoftwareSourceCode'})
        language = 'ru' if page.startswith('ru/') else 'en'
        body = (f'<html lang="{language}"><head>{metadata}{links}'
                f'<script type="application/ld+json">{schema}</script></head><body>'
                f'<h1>Synthetic content</h1><script src="{asset}" data-cf-token="{token}" defer></script>'
                '</body></html>')
        target = site / page / 'index.html'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding='utf-8')
    sitemap = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    sitemap += ''.join('<url><loc>' + html.escape(base + p) + '</loc></url>' for p in paths)
    (site / 'sitemap.xml').write_text(sitemap + '</urlset>', encoding='utf-8')
    return site


def test_public_checks_require_consistent_language_pairs_and_complete_sitemap(tmp_path):
    import sys
    site = _make_public_fixture(tmp_path)
    args = [sys.executable, str(tmp_path / 'scripts' / 'check_public.py')]
    good = subprocess.run(args, cwd=tmp_path, text=True, capture_output=True)
    assert good.returncode == 0, good.stdout + good.stderr
    ru = site / 'ru' / 'reels' / 'index.html'
    original = ru.read_text(encoding='utf-8')
    ru.write_text(original.replace('hreflang="en" href="https://votsie.github.io/instagram-obscura-mcp/reels/"',
                                   'hreflang="en" href="https://votsie.github.io/instagram-obscura-mcp/"'),
                  encoding='utf-8')
    bad = subprocess.run(args, cwd=tmp_path, text=True, capture_output=True)
    assert bad.returncode != 0 and 'hreflang' in bad.stderr.lower() + bad.stdout.lower()
    ru.write_text(original, encoding='utf-8')
    sitemap = site / 'sitemap.xml'
    sitemap.write_text(sitemap.read_text(encoding='utf-8').replace(
        '<url><loc>https://votsie.github.io/instagram-obscura-mcp/reels/</loc></url>', ''), encoding='utf-8')
    bad = subprocess.run(args, cwd=tmp_path, text=True, capture_output=True)
    assert bad.returncode != 0 and 'sitemap' in bad.stderr.lower() + bad.stdout.lower()


def test_public_checks_reject_missing_or_duplicate_analytics_loaders(tmp_path):
    import sys
    site = _make_public_fixture(tmp_path)
    args = [sys.executable, str(tmp_path / 'scripts' / 'check_public.py')]
    page = site / 'index.html'
    original = page.read_text(encoding='utf-8')
    tag = '<script src="assets/analytics.js" data-cf-token="0123456789abcdef0123456789abcdef" defer></script>'
    page.write_text(original.replace(tag, ''), encoding='utf-8')
    bad = subprocess.run(args, cwd=tmp_path, text=True, capture_output=True)
    assert bad.returncode != 0 and 'analytics' in bad.stderr.lower() + bad.stdout.lower()
    page.write_text(original.replace(tag, tag + tag), encoding='utf-8')
    bad = subprocess.run(args, cwd=tmp_path, text=True, capture_output=True)
    assert bad.returncode != 0 and 'analytics' in bad.stderr.lower() + bad.stdout.lower()


def test_site_works_when_analytics_is_blocked_in_a_real_browser():
    """Use intercepted pages only; never sends a request to Instagram or Cloudflare."""
    from playwright.sync_api import Error, sync_playwright
    public_url = 'https://votsie.github.io/instagram-obscura-mcp/'
    loader = (ROOT / 'site' / 'assets' / 'analytics.js').read_text(encoding='utf-8')
    html = ('''<html><head><script src="assets/analytics.js" '''
            '''data-cf-token="0123456789abcdef0123456789abcdef" defer></script>'''
            '''</head><body><a href="#target">Guide</a><p id="target">Ready</p></body></html>''')
    requests = []
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(channel='chrome', headless=True)
        except Error:
            pytest.skip('System Chrome not installed; synthetic-browser tests still run')
        try:
            page = browser.new_page()
            def intercept(route):
                url = route.request.url
                requests.append(url)
                if url == public_url:
                    route.fulfill(status=200, content_type='text/html', body=html)
                elif url == public_url + 'assets/analytics.js':
                    route.fulfill(status=200, content_type='application/javascript', body=loader)
                else:
                    route.abort('blockedbyclient')
            page.route('**/*', intercept)
            page.goto(public_url, wait_until='load')
            page.get_by_role('link', name='Guide').click()
            assert page.url.endswith('#target')
            assert page.locator('#target').text_content() == 'Ready'
            assert requests.count('https://static.cloudflareinsights.com/beacon.min.js') == 1
            assert all(url.startswith(public_url) or url == 'https://static.cloudflareinsights.com/beacon.min.js'
                       for url in requests)
        finally:
            browser.close()
