#!/usr/bin/env python3
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
HTML_PAGES=[
    'index.html','live.html','world.html','asia.html','hong-kong.html','japan.html',
    'finance.html','stocks.html','technology.html','manga-anime.html',
    'manchester-united.html','football.html','archive.html'
]
TOPIC_PAGES={
    'world.html','asia.html','hong-kong.html','japan.html','finance.html','technology.html',
    'manga-anime.html','manchester-united.html','football.html'
}
NAV_HREFS=[
    'live.html','index.html','world.html','asia.html','hong-kong.html','japan.html',
    'finance.html','stocks.html','technology.html','manga-anime.html',
    'manchester-united.html','football.html','archive.html'
]

def fail(message):
    raise SystemExit('LAYOUT_PARITY_FAIL: '+message)

def nav_block(text,rel):
    match=re.search(r'<nav[^>]*class="section-nav"[^>]*>(.*?)</nav>',text,re.I|re.S)
    if not match:fail(f'{rel}: section-nav missing')
    return match.group(1)

def main():
    css=(ROOT/'assets/css/system-ja.css').read_text(encoding='utf-8')
    required_css=(
        'background:#111!important',
        'color:#fff!important',
        '.section-nav a[aria-current="page"]',
        'background:#b00016!important'
    )
    for token in required_css:
        if token not in css:fail(f'system-ja.css missing navigation parity token: {token}')

    for rel in HTML_PAGES:
        path=ROOT/rel
        if not path.is_file():fail(f'missing page {rel}')
        text=path.read_text(encoding='utf-8')
        nav=nav_block(text,rel)
        for href in NAV_HREFS:
            if f'href="{href}"' not in nav:fail(f'{rel}: navigation missing {href}')
        current=re.findall(r'<a[^>]*aria-current="page"[^>]*href="([^"]+)"|<a[^>]*href="([^"]+)"[^>]*aria-current="page"',nav,re.I)
        current_hrefs=[a or b for a,b in current]
        if current_hrefs!=[rel]:fail(f'{rel}: active navigation must be exactly {rel}, got {current_hrefs}')
        if rel in TOPIC_PAGES:
            for token in ('class="topic-page-meta"','id="topic-date"','id="topic-count"','assets/css/topic-ja-rolling.css','assets/js/topic-ja-rolling.js'):
                if token not in text:fail(f'{rel}: topic parity element missing: {token}')

    renderer=(ROOT/'assets/js/topic-ja-rolling.js').read_text(encoding='utf-8')
    for token in ('formatEditionDate','topic-date','topic-count','stories · Daily + Rolling Desk + 速報'):
        if token not in renderer:fail(f'topic renderer missing metadata parity token: {token}')

    print(f'LAYOUT_PARITY_OK {len(HTML_PAGES)} pages; black/white nav, exact red active tab, {len(TOPIC_PAGES)} topic metadata bars')

if __name__=='__main__':main()
