#!/usr/bin/env python3
import argparse,json,re
from html.parser import HTMLParser
from pathlib import Path
import validate_content_integrity as content_integrity

ROOT=Path(__file__).resolve().parents[1]
HTML_PAGES=['index.html','live.html','world.html','asia.html','hong-kong.html','japan.html','finance.html','stocks.html','technology.html','manga-anime.html','manchester-united.html','football.html','archive.html']
NAV_HREFS=['live.html','index.html','world.html','asia.html','hong-kong.html','japan.html','finance.html','stocks.html','technology.html','manga-anime.html','manchester-united.html','football.html','archive.html']
SUSPICIOUS_UI=('載入','亞洲','財經','廣東話','頭版','歷史日報','個 人 化 電 子 報','新聞分版','關閉')
OLD_ARCHIVE_TOPICS={'亞洲','財經 / 全球市場','市場 / 經濟','AI / 科技','漫畫 / Anime','Manchester United','Football','日語學習','科學 / 新技術','網絡安全','軟件 / App','今日值得跟進','Upcoming events','香港 / 亞洲'}
KANA=re.compile(r'[\u3040-\u30ff]');HAN=re.compile(r'[\u3400-\u9fff]');JP_DATE=re.compile(r'^\d{4}年\d{1,2}月\d{1,2}日$')
EXPECTED_AUDIO_SPEED=0.72
EXPECTED_DELIVERY_PROFILE='jp-tv-news-semantic-v4'
MAX_CPM={'daily':345.0,'live':365.0}

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
    system_js=ROOT/'assets/js/system-ja.js';system_css=ROOT/'assets/css/system-ja.css';newspaper_css=ROOT/'assets/css/newspaper.css';news_js=ROOT/'assets/js/newspaper-ja.js';live_guard=ROOT/'assets/js/live-guard.js'
    for path in (system_js,system_css,newspaper_css,news_js,live_guard):
        if not path.is_file():fail(f'missing {path.relative_to(ROOT)}')
    css=newspaper_css.read_text(encoding='utf-8');renderer=news_js.read_text(encoding='utf-8');nav_js=system_js.read_text(encoding='utf-8');guard=live_guard.read_text(encoding='utf-8')
    if 'white-space:nowrap' not in css:fail('masthead title is not protected from wrapping')
    if '.sync-text.is-speaking' not in css or 'audio-transcript' not in css:fail('playback highlight/transcript styles missing')
    if 'synced-audio' not in renderer or 'data-timing' not in renderer or 'furigana' not in renderer:fail('furigana/playback synchronization renderer missing')
    if 'live-next-update' not in (ROOT/'live.html').read_text(encoding='utf-8'):fail('live page next publication field missing')
    if 'nextPublicationLabel' not in guard or 'Error 500' not in guard:fail('live publication/error quarantine guard missing')
    for href in NAV_HREFS:
        if href not in nav_js:fail(f'unified navigation missing {href}')
    if '<ruby>一面' not in nav_js or '<ruby>速報' not in nav_js:fail('navigation furigana missing')
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
    print(f'HTML_OK {len(HTML_PAGES)} pages; unified navigation {len(NAV_HREFS)} links; furigana/sync UI and Live guard present')

def japanese_copy_ok(item):
    visible=' '.join(str(item.get(k,'') or '') for k in ('title','dek','summary','body','context','why','watchNext'))
    return len(visible.strip())>=10 and bool(KANA.search(visible))

def validate_archive(archive):
    if not isinstance(archive,dict):fail('data/archive.json must be an object')
    if archive.get('language')!='ja':fail('data/archive.json language != ja')
    editions=archive.get('editions') or []
    if not editions:fail('Archive editions are empty')
    for i,edition in enumerate(editions,1):
        headline=str(edition.get('headline','')).strip()
        if not headline:fail(f'archive edition {i}: missing headline')
        if not KANA.search(headline):fail(f'archive edition {i}: headline does not look Japanese')
        if HAN.search(headline) and '<ruby>' not in str(edition.get('furiganaHeadline','')):fail(f'archive edition {i}: headline furigana missing')
        short_date=str(edition.get('shortDate','')).strip()
        if not JP_DATE.fullmatch(short_date):fail(f'archive edition {i}: shortDate is not Japanese: {short_date}')
        topics=edition.get('topics') or [];ruby_topics=edition.get('furiganaTopics') or []
        if not topics:fail(f'archive edition {i}: topics are empty')
        if len(ruby_topics)!=len(topics):fail(f'archive edition {i}: furiganaTopics count mismatch')
        for topic in topics:
            value=str(topic).strip()
            if not value:fail(f'archive edition {i}: empty topic')
            if value in OLD_ARCHIVE_TOPICS:fail(f'archive edition {i}: untranslated archive topic remains: {value}')
    print(f'ARCHIVE_OK {len(editions)} Japanese editions with furigana')

def validate_timing(group,aid,path):
    timing=load_json(path)
    if abs(float(timing.get('speed',0))-EXPECTED_AUDIO_SPEED)>0.001:fail(f'{group}:{aid}: timing speed is not {EXPECTED_AUDIO_SPEED}')
    if timing.get('deliveryProfile')!=EXPECTED_DELIVERY_PROFILE:fail(f'{group}:{aid}: wrong delivery profile')
    cpm=float(timing.get('charactersPerMinute',0));target=float(timing.get('targetMaxCharactersPerMinute',0))
    if cpm<=0:fail(f'{group}:{aid}: charactersPerMinute missing')
    if target<=0 or cpm>MAX_CPM[group]:fail(f'{group}:{aid}: speech still too fast at {cpm:.1f} chars/min')
    duration=float(timing.get('duration',0));segments=timing.get('segments') or [];units=timing.get('semanticUnits') or [];pauses=timing.get('pauseProfile') or {}
    if duration<=0 or not segments:fail(f'{group}:{aid}: timing metadata empty')
    if not units:fail(f'{group}:{aid}: semantic pause units missing')
    for required in ('micro','comma','semantic','sentence','paragraph','section'):
        if float(pauses.get(required,0))<=0:fail(f'{group}:{aid}: pause profile missing {required}')
    reasons={str(u.get('reason','')) for u in units}
    if not any(r.startswith('punctuation-') for r in reasons):fail(f'{group}:{aid}: punctuation pacing evidence missing')
    for u in units:
        pause=float(u.get('pause',0));intended=float(u.get('intendedPause',pause))
        if intended>0 and abs(pause-intended)>0.08:fail(f'{group}:{aid}: semantic pause drifted from intended length')
    prev=0.0
    for seg in segments:
        key=str(seg.get('key','')).strip();start=float(seg.get('start',-1));end=float(seg.get('end',-1))
        if not key:fail(f'{group}:{aid}: timing segment missing key')
        if start+0.03<prev or end<=start:fail(f'{group}:{aid}: invalid timing range for {key}')
        prev=end
    if abs(prev-duration)>0.30:fail(f'{group}:{aid}: timing does not reach audio duration')

def validate_news_and_audio():
    latest=load_json('data/latest.json');live=load_json('data/live.json');archive=load_json('data/archive.json')
    for name,data in (('latest.json',latest),('live.json',live),('archive.json',archive)):
        issues=content_integrity.collect_issues(name,data)
        if issues:fail(f'content integrity {issues[0]}')
    if latest.get('language')!='ja':fail('data/latest.json language != ja')
    if live.get('language')!='ja':fail('data/live.json language != ja')
    validate_archive(archive)
    manifest=load_json('audio/manifest.json');expected=set();checked=0
    groups=(('daily',latest.get('articles',[])),('live',live.get('items',[])))
    if not groups[0][1]:fail('Daily articles are empty')
    if not groups[1][1]:fail('Live items are empty')
    for group,items in groups:
        for item in items:
            aid=str(item.get('id','')).strip()
            if not aid:fail(f'{group}: missing id')
            title=str(item.get('title','')).strip()
            if not title:fail(f'{group}:{aid}: missing title')
            if not japanese_copy_ok(item):fail(f'{group}:{aid}: visible copy does not look Japanese')
            furigana=item.get('furigana') or {}
            if not isinstance(furigana,dict):fail(f'{group}:{aid}: furigana object missing')
            if HAN.search(title) and '<ruby>' not in str(furigana.get('title','')):fail(f'{group}:{aid}: title furigana missing')
            body_paras=[p for p in re.split(r'\n\s*\n',str(item.get('body') or item.get('summary') or '')) if p.strip()]
            if len(furigana.get('bodyParagraphs') or [])!=len(body_paras):fail(f'{group}:{aid}: body furigana paragraph mismatch')
            expected_path=f'audio/{group}/{aid}.mp3';timing_path=f'audio/timing/{group}/{aid}.json'
            if item.get('audio')!=expected_path:fail(f'{group}:{aid}: audio path mismatch')
            if item.get('timing')!=timing_path:fail(f'{group}:{aid}: timing path mismatch')
            if abs(float(item.get('audioSpeed',0))-EXPECTED_AUDIO_SPEED)>0.001:fail(f'{group}:{aid}: audioSpeed mismatch')
            if item.get('audioDeliveryProfile')!=EXPECTED_DELIVERY_PROFILE:fail(f'{group}:{aid}: audioDeliveryProfile mismatch')
            audio_path=ROOT/expected_path
            if not audio_path.is_file():fail(f'{group}:{aid}: audio file missing')
            if audio_path.stat().st_size<=1024:fail(f'{group}:{aid}: audio file too small')
            validate_timing(group,aid,timing_path)
            key=f'{group}:{aid}'
            if key not in manifest:fail(f'{group}:{aid}: manifest entry missing')
            expected.add(key);checked+=1
    manifest_keys=set(manifest)
    if expected-manifest_keys:fail(f'manifest missing keys: {sorted(expected-manifest_keys)}')
    if manifest_keys-expected:fail(f'manifest has stale keys: {sorted(manifest_keys-expected)}')
    print(f'DATA_AUDIO_OK {checked} Japanese Daily/Live items with clean content, furigana, semantic news-anchor pauses and capped speaking rate')

def main():
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group();g.add_argument('--static-only',action='store_true');g.add_argument('--data-only',action='store_true');args=p.parse_args()
    if args.static_only:validate_html();print('STATIC_QA_OK');return
    if args.data_only:validate_news_and_audio();print('DATA_QA_OK');return
    validate_html();validate_news_and_audio();print('SITE_QA_OK')

if __name__=='__main__':main()
