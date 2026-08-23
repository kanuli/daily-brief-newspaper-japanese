#!/usr/bin/env python3
import argparse,json,re
from html.parser import HTMLParser
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HTML_PAGES=['index.html','live.html','world.html','asia.html','hong-kong.html','japan.html','finance.html','stocks.html','technology.html','manga-anime.html','manchester-united.html','football.html','archive.html']
NAV_HREFS=['live.html','index.html','world.html','asia.html','hong-kong.html','japan.html','finance.html','stocks.html','technology.html','manga-anime.html','manchester-united.html','football.html','archive.html']
SUSPICIOUS_UI=('載入','亞洲','財經','廣東話','頭版','歷史日報','個 人 化 電 子 報','新聞分版','關閉')
KANA=re.compile(r'[\u3040-\u30ff]')

class LocalRefParser(HTMLParser):
    def __init__(self):super().__init__();self.refs=[]
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        for key in ('href','src'):
            value=d.get(key)
            if value:self.refs.append(value)

def fail(msg):raise SystemExit('SITE_QA_FAIL: '+msg)
def load_json(rel):
    path=ROOT/rel
    if not path.is_file():fail(f'missing {rel}')
    try:return json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:fail(f'invalid JSON {rel}: {exc}')

def validate_html():
    system_js=ROOT/'assets/js/system-ja.js';system_css=ROOT/'assets/css/system-ja.css';newspaper_css=ROOT/'assets/css/newspaper.css'
    for path in (system_js,system_css,newspaper_css):
        if not path.is_file():fail(f'missing {path.relative_to(ROOT)}')
    css=newspaper_css.read_text(encoding='utf-8')
    if 'white-space:nowrap' not in css:fail('masthead title is not protected from wrapping')
    nav_js=system_js.read_text(encoding='utf-8')
    for href in NAV_HREFS:
        if href not in nav_js:fail(f'unified navigation missing {href}')
    for rel in HTML_PAGES:
        path=ROOT/rel
        if not path.is_file():fail(f'missing page {rel}')
        text=path.read_text(encoding='utf-8')
        if '<html lang="ja"' not in text:fail(f'{rel}: lang is not ja')
        if 'assets/js/system-ja.js' not in text:fail(f'{rel}: system controller missing')
        if 'assets/css/newspaper.css' not in text:fail(f'{rel}: newspaper stylesheet missing')
        if 'assets/css/system-ja.css' not in text:fail(f'{rel}: system stylesheet missing')
        if 'class="section-nav"' not in text:fail(f'{rel}: navigation container missing')
        for phrase in SUSPICIOUS_UI:
            if phrase in text:fail(f'{rel}: old Traditional Chinese UI remains: {phrase}')
        parser=LocalRefParser();parser.feed(text)
        for ref in parser.refs:
            if re.match(r'^(?:https?:|mailto:|tel:|#|javascript:)',ref):continue
            clean=ref.split('?',1)[0].split('#',1)[0]
            if clean and not (ROOT/clean).exists():fail(f'{rel}: broken local reference {ref}')
    print(f'HTML_OK {len(HTML_PAGES)} pages; unified navigation {len(NAV_HREFS)} links')

def japanese_copy_ok(item):
    visible=' '.join(str(item.get(k,'') or '') for k in ('title','dek','summary','body','context','why','watchNext'))
    return len(visible.strip())>=10 and bool(KANA.search(visible))

def validate_news_and_audio():
    latest=load_json('data/latest.json');live=load_json('data/live.json');archive=load_json('data/archive.json')
    if latest.get('language')!='ja':fail('data/latest.json language != ja')
    if live.get('language')!='ja':fail('data/live.json language != ja')
    if isinstance(archive,dict) and archive.get('language') not in (None,'ja'):fail('data/archive.json language is not ja')
    manifest=load_json('audio/manifest.json');expected=set();checked=0
    groups=(('daily',latest.get('articles',[])),('live',live.get('items',[])))
    if not groups[0][1]:fail('Daily articles are empty')
    if not groups[1][1]:fail('Live items are empty')
    for group,items in groups:
        for item in items:
            aid=str(item.get('id','')).strip()
            if not aid:fail(f'{group}: missing id')
            if not str(item.get('title','')).strip():fail(f'{group}:{aid}: missing title')
            if not japanese_copy_ok(item):fail(f'{group}:{aid}: visible copy does not look Japanese')
            expected_path=f'audio/{group}/{aid}.mp3'
            if item.get('audio')!=expected_path:fail(f'{group}:{aid}: audio path mismatch')
            audio_path=ROOT/expected_path
            if not audio_path.is_file():fail(f'{group}:{aid}: audio file missing')
            if audio_path.stat().st_size<=1024:fail(f'{group}:{aid}: audio file too small')
            key=f'{group}:{aid}'
            if key not in manifest:fail(f'{group}:{aid}: manifest entry missing')
            expected.add(key);checked+=1
    manifest_keys=set(manifest)
    if expected-manifest_keys:fail(f'manifest missing keys: {sorted(expected-manifest_keys)}')
    if manifest_keys-expected:fail(f'manifest has stale keys: {sorted(manifest_keys-expected)}')
    print(f'DATA_AUDIO_OK {checked} Japanese Daily/Live items with F3 audio')

def main():
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group();g.add_argument('--static-only',action='store_true');g.add_argument('--data-only',action='store_true');args=p.parse_args()
    if args.static_only:validate_html();print('STATIC_QA_OK');return
    if args.data_only:validate_news_and_audio();print('DATA_QA_OK');return
    validate_html();validate_news_and_audio();print('SITE_QA_OK')

if __name__=='__main__':main()
