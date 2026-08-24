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
# The Cantonese edition is the set-selection source of truth, but the Japanese
# learning page must not reproduce obvious source metadata/spelling mistakes.
WORD_FIXES={
    ('そうごん','荘厳'):{'meaning':'荘厳で厳かなさま','partOfSpeech':'形容動詞・名詞'},
    ('ちょうきよほう','長期予報'):{'meaning':'長期間を対象とする予報','partOfSpeech':'名詞'},
    ('かざかみ','風上'):{'meaning':'風が吹いてくる方向・側','partOfSpeech':'名詞'},
    ('とみん','都民'):{'meaning':'東京都の住民','partOfSpeech':'名詞'},
    ('あらすじ',''):{'meaning':'物語などの大まかな内容・概要','partOfSpeech':'名詞'},
    ('じょうき','常軌'):{'meaning':'通常の道理や常識的な範囲','partOfSpeech':'名詞'},
    ('せいたい','生体'):{'meaning':'生命をもつ身体・生きた個体','partOfSpeech':'名詞'},
    ('おちる','落る'):{'kanji':'落ちる','meaning':'上から下へ落下する・程度が下がる','partOfSpeech':'動詞'},
    ('ページ','頁'):{'meaning':'本や文書のページ・頁','partOfSpeech':'名詞'},
    ('さつがい','殺害'):{'meaning':'人などを殺すこと','partOfSpeech':'名詞・サ変'},
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

def normalize_word(word):
    reading=str(word.get('reading',''))
    kanji=str(word.get('kanji',''))
    result={
        'level':word.get('level',''),
        'reading':reading,
        'kanji':kanji,
        'meaning':translate(word.get('meaning','')),
        'partOfSpeech':POS.get(str(word.get('partOfSpeech','')).lower(),word.get('partOfSpeech',''))
    }
    fix=WORD_FIXES.get((reading,kanji))
    if fix:result.update(fix)
    return result

def main():
    r=requests.get(SOURCE,timeout=30,headers={'User-Agent':'daily-brief-newspaper-japanese'})
    r.raise_for_status();src=r.json();words=[normalize_word(word) for word in src.get('words') or []]
    out={
        'date':src.get('date'),
        'sourceRepo':'kanuli/daily-brief-newspaper',
        'sourceFile':'data/vocab/latest.json',
        'sourceUrl':src.get('sourceUrl') or 'https://github.com/kanuli/japanese-vocab-game',
        'language':'ja',
        'levelNote':'一部のJLPTレベルは推定であり、公式JLPT語彙表ではありません。',
        'words':words
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'JAPANESE_VOCAB_SYNC_OK {len(words)} words date={out.get("date")}')

if __name__=='__main__':main()
