#!/usr/bin/env python3
import hashlib,re,subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HTML_PAGES=[
    'index.html','live.html','world.html','asia.html','hong-kong.html','japan.html',
    'finance.html','stocks.html','technology.html','manga-anime.html',
    'manchester-united.html','football.html','archive.html'
]
STATIC_CRITICAL=HTML_PAGES+[
    'assets/css/newspaper.css','assets/css/system-ja.css','assets/css/live-ja.css','assets/css/topic-ja-rolling.css',
    'assets/js/newspaper-ja.js','assets/js/system-ja.js','assets/js/live-guard.js','assets/js/live-article-ja.js','assets/js/topic-ja-rolling.js',
    'scripts/validate_site.py'
]
VERSIONED_ASSETS=[
    'assets/css/newspaper.css','assets/css/system-ja.css','assets/css/live-ja.css','assets/css/topic-ja-rolling.css',
    'assets/js/newspaper-ja.js','assets/js/system-ja.js','assets/js/live-guard.js','assets/js/live-article-ja.js','assets/js/topic-ja-rolling.js'
]
REPLACEMENTS={
    '載入中…':'読み込み中…','亞洲':'アジア','財經':'経済','廣東話':'広東語',
    '頭版':'一面トップ','歷史日報':'アーカイブ','新聞分版':'ニュース分野','關閉':'閉じる'
}

def write_if_changed(path,text):
    old=path.read_text(encoding='utf-8') if path.exists() else ''
    if text!=old:
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8');return True
    return False

def asset_version(rel):
    path=ROOT/rel
    if not path.is_file():return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:10]

def normalize_asset_versions(text):
    for rel in VERSIONED_ASSETS:
        version=asset_version(rel)
        if not version:continue
        pattern=re.escape(rel)+r'(?:\?v=[^"\']*)?'
        text=re.sub(pattern,f'{rel}?v={version}',text)
    return text

def normalize_html(rel):
    path=ROOT/rel
    if not path.exists():return False
    text=path.read_text(encoding='utf-8')
    text=re.sub(r'<html\s+lang="[^"]*"','<html lang="ja"',text,count=1,flags=re.I)
    if re.search(r'<html(?:\s|>)',text,re.I) and 'lang="ja"' not in text[:200]:
        text=re.sub(r'<html>', '<html lang="ja">', text, count=1, flags=re.I)
    if 'assets/css/newspaper.css' not in text:
        text=text.replace('</head>','<link rel="stylesheet" href="assets/css/newspaper.css">\n</head>',1)
    if 'assets/css/system-ja.css' not in text:
        text=text.replace('</head>','<link rel="stylesheet" href="assets/css/system-ja.css">\n</head>',1)
    nav='<nav class="section-nav" aria-label="ニュース分野"></nav>'
    if re.search(r'<nav[^>]*class="section-nav"[^>]*>.*?</nav>',text,re.I|re.S):
        text=re.sub(r'<nav[^>]*class="section-nav"[^>]*>.*?</nav>',nav,text,count=1,flags=re.I|re.S)
    elif '</header>' in text:
        text=text.replace('</header>','</header>'+nav,1)
    if 'assets/js/system-ja.js' not in text:
        text=text.replace('</body>','<script src="assets/js/system-ja.js" defer></script>\n</body>',1)
    for old,new in REPLACEMENTS.items():text=text.replace(old,new)
    text=normalize_asset_versions(text)
    return write_if_changed(path,text)

def repair_css():
    """Only protect the masthead from wrapping; never resize/replace the approved layout."""
    path=ROOT/'assets/css/newspaper.css'
    if not path.exists():return False
    text=path.read_text(encoding='utf-8')
    if not re.search(r'white-space\s*:\s*nowrap',text,re.I):
        text+='\n/* Auto-maintenance: preserve the approved masthead without changing its scale. */\n.brand h1{white-space:nowrap}\n'
    return write_if_changed(path,text)

def restore_from_golden(ref='origin/maintenance-known-good'):
    restored=[]
    for rel in STATIC_CRITICAL:
        p=subprocess.run(['git','show',f'{ref}:{rel}'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        if p.returncode:continue
        target=ROOT/rel
        current=target.read_bytes() if target.exists() else b''
        if current!=p.stdout:
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(p.stdout);restored.append(rel)
    print('GOLDEN_STATIC_RESTORED',','.join(restored) if restored else 'none')
    return restored

def restore_missing_from_golden(ref='origin/maintenance-known-good'):
    restored=[]
    for rel in STATIC_CRITICAL:
        target=ROOT/rel
        if target.exists():continue
        p=subprocess.run(['git','show',f'{ref}:{rel}'],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        if p.returncode:continue
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(p.stdout);restored.append(rel)
    print('GOLDEN_MISSING_RESTORED',','.join(restored) if restored else 'none')
    return restored

def main():
    changed=restore_missing_from_golden()
    if repair_css():changed.append('assets/css/newspaper.css')
    for rel in HTML_PAGES:
        if normalize_html(rel):changed.append(rel)
    print('STATIC_REPAIR_CHANGED',','.join(dict.fromkeys(changed)) if changed else 'none')

if __name__=='__main__':main()
