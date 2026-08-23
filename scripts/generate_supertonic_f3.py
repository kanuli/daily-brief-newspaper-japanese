#!/usr/bin/env python3
import hashlib,json,re,subprocess,tempfile
from pathlib import Path
from supertonic import TTS

DATASETS=((Path("data/latest.json"),"articles","daily"),(Path("data/live.json"),"items","live"))
AUDIO_ROOT=Path("audio")
TIMING_ROOT=AUDIO_ROOT/"timing"
MANIFEST=AUDIO_ROOT/"manifest.json"
VOICE="F3"
LANG="ja"
TOTAL_STEPS=8
SPEED=0.90
MAX_CHUNK=220
SILENCE=0.45
TIMING_VERSION=1

def clean(text):
    text=re.sub(r"https?://\S+","",str(text or ""))
    return re.sub(r"\s+"," ",text).strip()

def body_paragraphs(a):
    raw=str(a.get("body") or a.get("summary") or "")
    return [clean(p) for p in re.split(r"\n\s*\n",raw) if clean(p)]

def narration_segments(a):
    parts=[]
    title=clean(a.get("title"));dek=clean(a.get("dek"));why=clean(a.get("why"));watch=clean(a.get("watchNext"))
    if title:parts.append({"key":"title","spoken":f"{title}。","text":title})
    if dek:parts.append({"key":"dek","spoken":dek,"text":dek})
    for i,p in enumerate(body_paragraphs(a)):
        parts.append({"key":f"body-{i}","spoken":p,"text":p})
    if why:parts.append({"key":"why","spoken":f"このニュースの重要なポイントです。{why}","text":why})
    if watch:parts.append({"key":"watch","spoken":f"今後は、{watch}","text":watch})
    return parts

def narration_text(segments):
    return "\n".join(s["spoken"] for s in segments)

def content_hash(text):
    settings=f"{VOICE}|{LANG}|{TOTAL_STEPS}|{SPEED}|{MAX_CHUNK}|{SILENCE}|{text}"
    return hashlib.sha256(settings.encode("utf-8")).hexdigest()

def load_manifest():
    if MANIFEST.exists():
        try:return json.loads(MANIFEST.read_text(encoding="utf-8"))
        except Exception:return {}
    return {}

def mp3_from_wav(wav_path,mp3_path):
    subprocess.run(["ffmpeg","-y","-hide_banner","-loglevel","error","-i",str(wav_path),"-codec:a","libmp3lame","-b:a","96k","-ar","44100","-ac","1",str(mp3_path)],check=True)

def audio_duration(path):
    p=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],check=True,capture_output=True,text=True)
    return float(p.stdout.strip())

def speech_weight(text):
    value=clean(text)
    base=sum(1 for ch in value if not ch.isspace() and ch not in "。！？!?、，,.;；:：")
    pauses=(value.count("。")+value.count("！")+value.count("？")+value.count("!")+value.count("?"))*5
    pauses+=(value.count("、")+value.count("，")+value.count(","))*2
    return max(1,base+pauses)

def timing_payload(out,segments):
    duration=audio_duration(out)
    weights=[speech_weight(s["spoken"]) for s in segments]
    total=max(1,sum(weights));cursor=0.0;timeline=[]
    for i,(seg,weight) in enumerate(zip(segments,weights)):
        start=cursor
        end=duration if i==len(segments)-1 else min(duration,cursor+duration*(weight/total))
        timeline.append({"key":seg["key"],"start":round(start,3),"end":round(end,3),"text":seg["text"]})
        cursor=end
    return {"version":TIMING_VERSION,"duration":round(duration,3),"voice":VOICE,"language":LANG,"speed":SPEED,"segments":timeline}

def collect_records(manifest):
    records=[];wanted=set()
    for data_path,list_key,group in DATASETS:
        if not data_path.exists():continue
        data=json.loads(data_path.read_text(encoding="utf-8"));changed=False
        out_dir=AUDIO_ROOT/group;out_dir.mkdir(parents=True,exist_ok=True)
        timing_dir=TIMING_ROOT/group;timing_dir.mkdir(parents=True,exist_ok=True)
        for a in data.get(list_key,[]):
            aid=a.get("id");segments=narration_segments(a)
            if not aid or not segments:continue
            text=narration_text(segments);key=f"{group}:{aid}";wanted.add(key)
            digest=content_hash(text);out=out_dir/f"{aid}.mp3";timing=timing_dir/f"{aid}.json"
            expected_audio=f"audio/{group}/{aid}.mp3";expected_timing=f"audio/timing/{group}/{aid}.json"
            if a.get("audio")!=expected_audio:a["audio"]=expected_audio;changed=True
            if a.get("timing")!=expected_timing:a["timing"]=expected_timing;changed=True
            if a.get("audioSpeed")!=SPEED:a["audioSpeed"]=SPEED;changed=True
            needs_audio=not out.exists() or manifest.get(key)!=digest
            records.append((key,segments,digest,out,timing,needs_audio))
        if changed:
            data_path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return records,wanted

def remove_stale(manifest,wanted):
    for group in ("daily","live"):
        folder=AUDIO_ROOT/group
        if folder.exists():
            for old in folder.glob("*.mp3"):
                key=f"{group}:{old.stem}"
                if key not in wanted:
                    old.unlink();manifest.pop(key,None)
        tfolder=TIMING_ROOT/group
        if tfolder.exists():
            for old in tfolder.glob("*.json"):
                if f"{group}:{old.stem}" not in wanted:old.unlink()

def main():
    AUDIO_ROOT.mkdir(exist_ok=True);TIMING_ROOT.mkdir(parents=True,exist_ok=True)
    manifest=load_manifest();records,wanted=collect_records(manifest);remove_stale(manifest,wanted)
    jobs=[r for r in records if r[5]]
    if jobs:
        tts=TTS(auto_download=True);style=tts.get_voice_style(voice_name=VOICE)
        for key,segments,digest,out,timing,_ in jobs:
            text=narration_text(segments)
            with tempfile.TemporaryDirectory() as td:
                wav_path=Path(td)/"news.wav"
                wav,_=tts.synthesize(text=text,voice_style=style,total_steps=TOTAL_STEPS,speed=SPEED,max_chunk_length=MAX_CHUNK,silence_duration=SILENCE,lang=LANG,verbose=False)
                tts.save_audio(wav,str(wav_path));mp3_from_wav(wav_path,out)
            manifest[key]=digest
            print("generated",out)
    else:
        print("F3 audio is already current")
    for key,segments,digest,out,timing,_ in records:
        if not out.exists():raise RuntimeError(f"missing audio after generation: {out}")
        timing.write_text(json.dumps(timing_payload(out,segments),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    MANIFEST.write_text(json.dumps({k:manifest[k] for k in sorted(manifest) if k in wanted},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"F3 timing metadata updated at speed {SPEED:.2f}")

if __name__=="__main__":main()
