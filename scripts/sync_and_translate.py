#!/usr/bin/env python3
import hashlib,json,re,time
from pathlib import Path
import requests
from deep_translator import GoogleTranslator

SOURCE_BASE="https://raw.githubusercontent.com/kanuli/daily-brief-newspaper/main/data"
OUT=Path("data")
CACHE_PATH=OUT/"translation-cache.json"
FILES=("latest.json","live.json","archive.json","stocks-latest.json","desk-latest.json")
TRANSLATE_KEYS={"dateLabel","tagline","section","title","dek","summary","body","context","why","watchNext","timeLabel","lastUpdatedLabel","nextUpdateLabel","windowLabel","subtitle","description","label","note","statusLabel"}
KEEP_KEYS={"id","desk","slug","sourceName","sourceUrl","url","image","imageAlt","date","editionNumber","status","leadId","editorialStandardVersion","contentVersion","createdAt","updatedAt","lastUpdated"}
DESK_NAMES={"world":"世界","asia":"アジア","hong-kong":"香港","japan":"日本","market-economy":"経済・世界市場","finance":"経済・世界市場","stocks":"株式ニュース","stock-news":"株式ニュース","ai-tech":"AI・テクノロジー","science-new-tech":"科学・新技術","cybersecurity":"サイバーセキュリティ","software-apps":"ソフトウェア・アプリ・消費者向け技術","manga-anime":"漫画・アニメ","manchester-united":"マンチェスター・ユナイテッド","football":"サッカー","breaking-news":"速報","worth-following":"きょうの注目","upcoming-events":"今後の予定"}

translator=GoogleTranslator(source="auto",target="ja")

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

def translate_text(text):
    if not isinstance(text,str) or not text.strip():return text
    if re.match(r"^https?://",text):return text
    key=hashlib.sha256(text.encode("utf-8")).hexdigest()
    if key in CACHE:return CACHE[key]
    out=[]
    for part in chunks(text):
        if not part.strip():out.append(part);continue
        last=None
        for attempt in range(4):
            try:
                last=translator.translate(part)
                if last:break
            except Exception:
                time.sleep(1.5*(attempt+1))
        if not last:raise RuntimeError(f"Japanese translation failed: {part[:100]!r}")
        out.append(last);time.sleep(0.08)
    value="".join(out)
    if value.strip()==text.strip() and len(text.strip())>18 and re.search(r"[\u3400-\u9fff]",text):
        raise RuntimeError(f"Translator returned source text unchanged: {text[:100]!r}")
    CACHE[key]=value
    return value

def convert(obj,parent_key=""):
    if isinstance(obj,list):return [convert(x,parent_key) for x in obj]
    if isinstance(obj,dict):
        out={}
        for k,v in obj.items():
            if k in KEEP_KEYS:out[k]=v
            elif k=="sections" and isinstance(v,list):out[k]=convert(v,k)
            elif k in TRANSLATE_KEYS:out[k]=translate_text(v) if isinstance(v,str) else convert(v,k)
            else:out[k]=convert(v,k)
        if isinstance(out.get("slug"),str) and out["slug"] in DESK_NAMES:out["title"]=DESK_NAMES[out["slug"]]
        return out
    if isinstance(obj,str) and parent_key in TRANSLATE_KEYS:return translate_text(obj)
    return obj

def fetch(name):
    r=requests.get(f"{SOURCE_BASE}/{name}",timeout=40,headers={"User-Agent":"daily-brief-newspaper-japanese"})
    if r.status_code==404:return None
    r.raise_for_status();return r.json()

def attach_daily_audio(data):
    if not isinstance(data,dict):return data
    for a in data.get("articles",[]):
        if a.get("id"):a["audio"]=f"audio/daily/{a['id']}.mp3"
    return data

def attach_live_audio(data):
    if not isinstance(data,dict):return data
    for a in data.get("items",[]):
        if a.get("id"):a["audio"]=f"audio/live/{a['id']}.mp3"
    return data

def main():
    OUT.mkdir(exist_ok=True);done=[]
    for name in FILES:
        src=fetch(name)
        if src is None:continue
        translated=convert(src)
        if name=="latest.json":translated=attach_daily_audio(translated)
        if name=="live.json":translated=attach_live_audio(translated)
        if isinstance(translated,dict):
            translated["language"]="ja"
            translated["translationSource"]="kanuli/daily-brief-newspaper"
        (OUT/name).write_text(json.dumps(translated,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        done.append(name)
    CACHE_PATH.write_text(json.dumps(CACHE,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("Japanese data updated:",", ".join(done))

if __name__=="__main__":main()
