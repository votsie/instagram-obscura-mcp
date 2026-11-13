"""Offline integrity checks for public documentation, assets and release archives."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote
import json
import argparse
import re
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.git', '.venv', '__pycache__', '.pytest_cache', 'build', 'dist', 'graphify-out'}
errors = []
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--dist', type=Path, default=ROOT/'dist', help='Release archives to inspect')
args = parser.parse_args()

class Page(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.h1=0; self.meta={}; self.canonical=[]; self.languages={}; self.lang=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='html':self.lang=a.get('lang')
        if tag=='h1':self.h1+=1
        if tag=='meta':self.meta[a.get('name',a.get('property',''))]=a.get('content','')
        if tag=='link' and a.get('rel')=='canonical':self.canonical.append(a.get('href'))
        if tag=='link' and a.get('rel')=='alternate':self.languages[a.get('hreflang')]=a.get('href')
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
        page=Page();page.feed(body)
        if page.h1!=1 or page.lang not in ('en','ru'):errors.append(f'Invalid language/H1: {relative}')
        if len(page.canonical)!=1 or set(page.languages)!={'en','ru','x-default'}:errors.append(f'Missing canonical/hreflang: {relative}')
        for name in ('description','og:title','og:description','og:image','twitter:card'):
            if not page.meta.get(name):errors.append(f'Missing {name}: {relative}')
        for value in page.links:local_link(path,value)
        for data in re.findall(r'<script type="application/ld\+json">(.*?)</script>',body,re.S):
            if json.loads(data).get('@type')!='SoftwareSourceCode':errors.append('Invalid software schema')

sdist_allowed = {'src','tests','docs','site','scripts','examples','skills','.github',
                 '.env.example','.gitattributes','.gitignore','AGENTS.md','CHANGELOG.md',
                 'CLAUDE.md','CONTRIBUTING.md','LICENSE','README.md','README.ru.md',
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
