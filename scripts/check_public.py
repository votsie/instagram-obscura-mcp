"""Offline integrity checks for public documentation, assets and release archives."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote
import json
import argparse
import re
import tarfile
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.git', '.venv', '__pycache__', '.pytest_cache', 'build', 'dist', 'graphify-out'}
errors = []
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--dist', type=Path, default=ROOT/'dist', help='Release archives to inspect')
args = parser.parse_args()
site_pages = {}
analytics_tokens = set()
SITE_BASE = 'https://votsie.github.io/instagram-obscura-mcp/'

class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.h1=0; self.meta={}; self.canonical=[]; self.languages={}; self.lang=None; self.analytics=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='html':self.lang=a.get('lang')
        if tag=='h1':self.h1+=1
        if tag=='meta':self.meta[a.get('name',a.get('property',''))]=a.get('content','')
        if tag=='link' and a.get('rel')=='canonical':self.canonical.append(a.get('href'))
        if tag=='link' and a.get('rel')=='alternate':self.languages[a.get('hreflang')]=a.get('href')
        if tag=='script' and a.get('src','').split('?')[0].endswith('/analytics.js'):self.analytics.append(a.get('data-cf-token'))
        if tag=='img' and ('alt' not in a or 'width' not in a or 'height' not in a):errors.append('Image dimensions/alt missing')
        for k in ('href','src'):
            if k in a:self.links.append(a[k])

def local_link(origin,value):
    if value.startswith(('#','mailto:','data:')):return
    url=urlsplit(value)
    if url.scheme or url.netloc:return
    path=unquote(url.path)
    if not path:return
    target=(origin.parent/path).resolve()
    if not target.is_relative_to(ROOT):errors.append(f'Link escapes project: {origin.relative_to(ROOT)}')
    elif not target.exists():errors.append(f'Missing link {origin.relative_to(ROOT)} -> {path}')

for path in ROOT.rglob('*'):
    relative=path.relative_to(ROOT)
    if any(part in SKIP for part in relative.parts) or not path.is_file():continue
    if path.suffix in ('.md','.txt','.json','.toml','.html','.yml','.yaml','.py','.sh','.ps1','.svg'):
        body=path.read_text(encoding='utf-8')
        if re.search(r'C:[/\\]Users[/\\]',body,re.I):errors.append(f'Personal absolute path: {relative}')
        if re.search(r'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY',body):errors.append(f'Credential pattern: {relative}')
    if path.suffix=='.md':
        for value in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',body):
            local_link(path,value.split(' "')[0].strip('<>'))
        for value in re.findall(r'(?:src|href)="([^"]+)"',body):local_link(path,value)
    if path.suffix=='.html':
        # Search Console verification is a plain-text Google ownership token,
        # not a content page; accept only exact root-level filename/content.
        if path.parent == ROOT/'site' and re.fullmatch(r'google[0-9a-f]{16}\.html', path.name):
            if body.strip() != 'google-site-verification: ' + path.name:
                errors.append(f'Invalid Google verification file: {relative}')
            continue
        page=Page();page.feed(body)
        if page.h1!=1 or page.lang not in ('en','ru'):errors.append(f'Invalid language/H1: {relative}')
        if len(page.canonical)!=1 or set(page.languages)!={'en','ru','x-default'}:errors.append(f'Missing canonical/hreflang: {relative}')
        for name in ('description','og:title','og:description','og:image','twitter:card'):
            if not page.meta.get(name):errors.append(f'Missing {name}: {relative}')
        for value in page.links:local_link(path,value)
        for data in re.findall(r'<script type="application/ld\+json">(.*?)</script>',body,re.S):
            if json.loads(data).get('@type')!='SoftwareSourceCode':errors.append('Invalid software schema')
        if path.is_relative_to(ROOT/'site'):
            parts=path.relative_to(ROOT/'site').parts
            if parts[-1]!='index.html':
                errors.append(f'Unexpected non-index site HTML: {relative}')
                continue
            directories=parts[:-1]
            is_ru=bool(directories and directories[0]=='ru')
            route=directories[1:] if is_ru else directories
            suffix='/'.join(route)+('/' if route else '')
            canonical=SITE_BASE+('ru/' if is_ru else '')+suffix
            expected={'en':SITE_BASE+suffix,'ru':SITE_BASE+'ru/'+suffix,'x-default':SITE_BASE+suffix}
            if page.canonical != [canonical] or page.lang != ('ru' if is_ru else 'en'):
                errors.append(f'Invalid canonical or language: {relative}')
            if page.languages != expected:
                errors.append(f'Invalid reciprocal hreflang: {relative}')
            if len(page.analytics)!=1 or not isinstance(page.analytics[0], str) or not re.fullmatch(r'[0-9a-fA-F]{32}',page.analytics[0]):
                errors.append(f'Invalid or duplicate analytics loader: {relative}')
            else:
                analytics_tokens.add(page.analytics[0])
            site_pages[canonical]=relative

if site_pages:
    if len(analytics_tokens)!=1:
        errors.append('Website analytics configuration is inconsistent')
    try:
        root=ET.parse(ROOT/'site'/'sitemap.xml').getroot()
        urls=[node.text for node in root.findall('{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
        if len(urls)!=len(set(urls)) or set(urls)!=set(site_pages):
            errors.append('Sitemap URLs do not match the website pages')
    except (OSError, ET.ParseError):
        errors.append('Missing or invalid sitemap')

sdist_allowed = {'src','tests','docs','site','scripts','examples','skills','.github',
                 '.env.example','.gitattributes','.gitignore','AGENTS.md','CHANGELOG.md',
                 'CLAUDE.md','CONTRIBUTING.md','CODE_OF_CONDUCT.md','ACCESSIBILITY.md','LICENSE','README.md','README.ru.md',
                 'SECURITY.md','THIRD_PARTY_NOTICES.md','llms.txt','pyproject.toml','PKG-INFO'}
for path in args.dist.glob('*'):
    if path.suffix=='.whl':
        with zipfile.ZipFile(path) as archive:names=archive.namelist()
    elif path.name.endswith('.tar.gz'):
        with tarfile.open(path) as archive:names=archive.getnames()
    else:continue
    for name in names:
        parts=Path(name).parts
        if path.name.endswith('.tar.gz') and len(parts)>1 and parts[1] not in sdist_allowed:
            errors.append(f'Unexpected source archive entry: {parts[1]}')
        if any(x in parts for x in ('.work','.runtime','.venv','profile','profiles','jobs','uploads','models','__pycache__','.pytest_cache','.git','graphify-out','dist','build','.coverage')) or name.endswith(('.mp4','.wav','.log','.pyc')):
            errors.append(f'Private/runtime artifact in {path.name}: {name}')

if errors:
    raise SystemExit('Public checks failed:\n'+'\n'.join(sorted(set(errors))))
print('Public docs, local links, SEO metadata and release archive checks passed.')
