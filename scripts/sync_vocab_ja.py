#!/usr/bin/env python3
import json, re, time
from pathlib import Path
import requests
from deep_translator import GoogleTranslator

SOURCE='https://raw.githubusercontent.com/kanuli/daily-brief-newspaper/main/data/vocab/latest.json'
OUT=Path('data/vocab/latest.json')
HAN=re.compile(r'[\u3400-\u9fff]')
KANA=re.compile(r'[\u3040-\u30ff]')

POS={
    'noun':'名詞','n':'名詞','verb':'動詞','v':'動詞','adj':'形容詞','adjective':'形容詞',
    'adv':'副詞','adverb':'副詞','particle':'助詞','conjunction':'接続詞','conj':'接続詞',
    'pronoun':'代名詞','pron':'代名詞','interjection':'感動詞','int':'感動詞','auxiliary':'助動詞',
    'aux':'助動詞','determiner':'連体詞','prefix':'接頭語','suffix':'接尾語','counter':'助数詞',
    'numeral':'数詞','expression':'表現','phrase':'慣用表現'
}

def looks_chinese(text):
    text=str(text or '')
    return bool(HAN.search(text)) and not bool(KANA.search(text))

def gtx(text):
    r=requests.get('https://translate.googleapis.com/translate_a/single',params={
        'client':'gtx','sl':'zh-TW' if looks_chinese(text) else 'auto','tl':'ja','dt':'t','q':text
    },headers={'User-Agent':'daily-brief-newspaper-japanese'},timeout=25)
    r.raise_for_status();payload=r.json();segments=payload[0] if isinstance(payload,list) and payload else []
    value=''.join(str(x[0]) for x in segments if isinstance(x,list) and x and x[0])
    if not value.strip():raise RuntimeError('empty GTX translation')
    return value

def translate(text):
    text=str(text or '').strip()
    if not text:return text
    if not looks_chinese(text):return text
    try:return gtx(text)
    except Exception:
        for source in ('zh-TW','auto','zh-CN'):
            try:
                value=GoogleTranslator(source=source,target='ja').translate(text)
                if value:return value
            except Exception:time.sleep(.5)
    raise RuntimeError(f'vocab translation failed: {text!r}')

def main():
    r=requests.get(SOURCE,timeout=30,headers={'User-Agent':'daily-brief-newspaper-japanese'})
    r.raise_for_status();src=r.json();words=[]
    for word in src.get('words') or []:
        words.append({
            'level':word.get('level',''),
            'reading':word.get('reading',''),
            'kanji':word.get('kanji',''),
            'meaning':translate(word.get('meaning','')),
            'partOfSpeech':POS.get(str(word.get('partOfSpeech','')).lower(),word.get('partOfSpeech',''))
        })
    out={
        'date':src.get('date'),
        'sourceRepo':'kanuli/daily-brief-newspaper',
        'sourceFile':'data/vocab/latest.json',
        'sourceUrl':'https://github.com/kanuli/daily-brief-newspaper',
        'language':'ja',
        'levelNote':'一部のJLPTレベルは推定であり、公式JLPT語彙表ではありません。',
        'words':words
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'JAPANESE_VOCAB_SYNC_OK {len(words)} words date={out.get("date")}')

if __name__=='__main__':main()
