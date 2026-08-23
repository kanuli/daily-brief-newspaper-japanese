#!/usr/bin/env python3
import hashlib,html,json,re,time
from pathlib import Path
import requests
from deep_translator import GoogleTranslator
import pykakasi

SOURCE_BASE="https://raw.githubusercontent.com/kanuli/daily-brief-newspaper/main/data"
OUT=Path("data")
CACHE_PATH=OUT/"translation-cache.json"
FILES=("latest.json","live.json","archive.json")
TRANSLATE_KEYS={"dateLabel","tagline","section","title","dek","summary","body","context","why","watchNext","timeLabel","lastUpdatedLabel","nextUpdateLabel","windowLabel","subtitle","description","label","note","statusLabel","headline"}
KEEP_KEYS={"id","desk","slug","sourceName","sourceUrl","url","image","imageAlt","date","editionNumber","status","leadId","editorialStandardVersion","contentVersion","createdAt","updatedAt","lastUpdated"}
DESK_NAMES={"world":"世界","asia":"アジア","hong-kong":"香港","japan":"日本","market-economy":"経済・世界市場","finance":"経済・世界市場","stocks":"株式ニュース","stock-news":"株式ニュース","ai-tech":"AI・テクノロジー","science-new-tech":"科学・新技術","cybersecurity":"サイバーセキュリティ","software-apps":"ソフトウェア・アプリ・消費者向け技術","manga-anime":"漫画・アニメ","manchester-united":"マンチェスター・ユナイテッド","football":"サッカー","breaking-news":"速報","worth-following":"きょうの注目","upcoming-events":"今後の予定"}
ARCHIVE_TOPIC_NAMES={
    "世界":"世界","亞洲":"アジア","香港":"香港","日本":"日本",
    "財經 / 全球市場":"経済・世界市場","市場 / 經濟":"市場・経済","AI / 科技":"AI・テクノロジー",
    "漫畫 / Anime":"漫画・アニメ","Manchester United":"マンチェスター・ユナイテッド","Football":"サッカー",
    "日語學習":"日本語学習","科學 / 新技術":"科学・新技術","網絡安全":"サイバーセキュリティ",
    "軟件 / App":"ソフトウェア・アプリ","今日值得跟進":"きょうの注目","Upcoming events":"今後の予定",
    "香港 / 亞洲":"香港・アジア"
}

HAN_RE=re.compile(r"[\u3400-\u9fff]")
KANA_RE=re.compile(r"[\u3040-\u30ff]")
CACHE_VERSION="ja-v2-explicit-zh-tw"
KKS=pykakasi.kakasi()
RUBY_FIELDS=("section","title","dek","summary","context","why","watchNext")

def source_fingerprint(obj):
    raw=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def load_cache():
    if CACHE_PATH.exists():
        try:return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:return {}
    return {}
CACHE=load_cache()

def chunks(text,limit=3800):
    if len(text)<=limit:return [text]
    parts=[]
    for para in re.split(r"(\n\s*\n)",text):
        if not para:continue
        if len(para)<=limit:parts.append(para);continue
        buf=""
        for sent in re.split(r"(?<=[。！？.!?])",para):
            if len(buf)+len(sent)>limit and buf:
                parts.append(buf);buf=""
            if len(sent)>limit:
                parts.extend(sent[i:i+limit] for i in range(0,len(sent),limit))
            else:buf+=sent
        if buf:parts.append(buf)
    return parts

def likely_chinese_source(text):
    return bool(HAN_RE.search(text)) and not bool(KANA_RE.search(text))

def translate_part(part):
    sources=("zh-TW","auto","zh-CN") if likely_chinese_source(part) else ("auto",)
    last_error=None
    for source in sources:
        for attempt in range(4):
            try:
                value=GoogleTranslator(source=source,target="ja").translate(part)
                if not value:raise RuntimeError("empty translation")
                if value.strip()==part.strip() and likely_chinese_source(part) and len(part.strip())>18:
                    last_error=RuntimeError(f"{source} returned source text unchanged");break
                return value
            except Exception as exc:
                last_error=exc;time.sleep(1.2*(attempt+1))
    raise RuntimeError(f"Japanese translation failed after zh-TW/auto fallbacks: {part[:100]!r}; last={last_error}")

def translate_text(text):
    if not isinstance(text,str) or not text.strip():return text
    if re.match(r"^https?://",text):return text
    key=hashlib.sha256(f"{CACHE_VERSION}|{text}".encode("utf-8")).hexdigest()
    if key in CACHE:return CACHE[key]
    out=[]
    for part in chunks(text):
        if not part.strip():out.append(part);continue
        out.append(translate_part(part));time.sleep(0.08)
    value="".join(out)
    if value.strip()==text.strip() and likely_chinese_source(text) and len(text.strip())>18:
        raise RuntimeError(f"Chinese source remained untranslated after fallback: {text[:100]!r}")
    CACHE[key]=value
    return value

def translate_archive_topic(value):
    text=str(value)
    if text in ARCHIVE_TOPIC_NAMES:return ARCHIVE_TOPIC_NAMES[text]
    return translate_text(text)

def japanese_short_date(value):
    if not isinstance(value,str):return value
    m=re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})",value.strip())
    if not m:return None
    y,mo,d=m.groups();return f"{y}年{int(mo)}月{int(d)}日"

def convert(obj,parent_key=""):
    if isinstance(obj,list):return [convert(x,parent_key) for x in obj]
    if isinstance(obj,dict):
        out={}
        for k,v in obj.items():
            if k in KEEP_KEYS:out[k]=v
            elif k=="topics" and isinstance(v,list):out[k]=[translate_archive_topic(x) for x in v]
            elif k=="shortDate":out[k]=v
            elif k=="sections" and isinstance(v,list):out[k]=convert(v,k)
            elif k in TRANSLATE_KEYS:out[k]=translate_text(v) if isinstance(v,str) else convert(v,k)
            else:out[k]=convert(v,k)
        if isinstance(out.get("slug"),str) and out["slug"] in DESK_NAMES:out["title"]=DESK_NAMES[out["slug"]]
        if "shortDate" in out and isinstance(out.get("date"),str):
            out["shortDate"]=japanese_short_date(out["date"]) or out["shortDate"]
        return out
    if isinstance(obj,str) and parent_key in TRANSLATE_KEYS:return translate_text(obj)
    return obj

def kata_to_hira_char(ch):
    code=ord(ch)
    if 0x30A1<=code<=0x30F6:return chr(code-0x60)
    return ch

def ruby_piece(orig,reading):
    orig=str(orig or "");reading=str(reading or "")
    if not orig:return ""
    if not HAN_RE.search(orig) or not reading:
        return html.escape(orig,quote=False)
    op=hp=0;os=len(orig);hs=len(reading)
    while op<os and hp<hs and not HAN_RE.match(orig[op]) and kata_to_hira_char(orig[op])==reading[hp]:
        op+=1;hp+=1
    while os>op and hs>hp and not HAN_RE.match(orig[os-1]) and kata_to_hira_char(orig[os-1])==reading[hs-1]:
        os-=1;hs-=1
    base=orig[op:os];yomi=reading[hp:hs]
    if not base or not yomi or not HAN_RE.search(base):
        return html.escape(orig,quote=False)
    return (
        html.escape(orig[:op],quote=False)
        +f"<ruby>{html.escape(base,quote=False)}<rt>{html.escape(yomi,quote=False)}</rt></ruby>"
        +html.escape(orig[os:],quote=False)
    )

def ruby_html(text):
    value=str(text or "")
    if not value:return ""
    try:
        parts=[]
        for token in KKS.convert(value):
            parts.append(ruby_piece(token.get("orig",""),token.get("hira","")))
        return "".join(parts)
    except Exception:
        return html.escape(value,quote=False)

def body_paragraphs(item):
    raw=str(item.get("body") or item.get("summary") or "")
    return [p.strip() for p in re.split(r"\n\s*\n",raw) if p.strip()]

def add_furigana(data,list_key):
    if not isinstance(data,dict):return data
    for item in data.get(list_key,[]):
        furigana={}
        for field in RUBY_FIELDS:
            value=item.get(field)
            if isinstance(value,str) and value.strip():furigana[field]=ruby_html(value)
        furigana["bodyParagraphs"]=[ruby_html(p) for p in body_paragraphs(item)]
        item["furigana"]=furigana
    return data

def add_archive_furigana(data):
    if not isinstance(data,dict):return data
    for edition in data.get("editions",[]):
        if edition.get("headline"):edition["furiganaHeadline"]=ruby_html(edition["headline"])
        edition["furiganaTopics"]=[ruby_html(x) for x in edition.get("topics",[])]
    return data

def fetch(name):
    r=requests.get(f"{SOURCE_BASE}/{name}",timeout=40,headers={"User-Agent":"daily-brief-newspaper-japanese"})
    if r.status_code==404:return None
    r.raise_for_status();return r.json()

def attach_daily_audio(data):
    if isinstance(data,dict):
        for a in data.get("articles",[]):
            if a.get("id"):
                a["audio"]=f"audio/daily/{a['id']}.mp3"
                a["timing"]=f"audio/timing/daily/{a['id']}.json"
    return data

def attach_live_audio(data):
    if isinstance(data,dict):
        for a in data.get("items",[]):
            if a.get("id"):
                a["audio"]=f"audio/live/{a['id']}.mp3"
                a["timing"]=f"audio/timing/live/{a['id']}.json"
    return data

def main():
    OUT.mkdir(exist_ok=True);done=[]
    for name in FILES:
        src=fetch(name)
        if src is None:continue
        translated=convert(src)
        if name=="latest.json":translated=add_furigana(attach_daily_audio(translated),"articles")
        if name=="live.json":translated=add_furigana(attach_live_audio(translated),"items")
        if name=="archive.json":translated=add_archive_furigana(translated)
        if isinstance(translated,dict):
            translated["language"]="ja"
            translated["translationSource"]="kanuli/daily-brief-newspaper"
            translated["sourceFile"]=name
            translated["sourceFingerprint"]=source_fingerprint(src)
        (OUT/name).write_text(json.dumps(translated,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        done.append(name)
    CACHE_PATH.write_text(json.dumps(CACHE,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Japanese data updated:",", ".join(done))

if __name__=="__main__":main()
