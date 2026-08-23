#!/usr/bin/env python3
import hashlib,json,re,shutil,subprocess,tempfile
from pathlib import Path
import numpy as np
from supertonic import TTS

DATASETS=((Path("data/latest.json"),"articles","daily"),(Path("data/live.json"),"items","live"))
AUDIO_ROOT=Path("audio")
TIMING_ROOT=AUDIO_ROOT/"timing"
MANIFEST=AUDIO_ROOT/"manifest.json"
VOICE="F3"
LANG="ja"
TOTAL_STEPS=8
SPEED=0.72
MAX_CHUNK=160
SYNTH_SILENCE=0.12
SAMPLE_RATE=44100
TIMING_VERSION=3
DELIVERY_PROFILE="jp-tv-news-semantic-v4"
TARGET_CPM={"daily":340.0,"live":360.0}
PAUSES={
    "daily":{"micro":0.18,"comma":0.28,"semantic":0.34,"sentence":0.62,"paragraph":0.78,"section":0.86},
    "live":{"micro":0.14,"comma":0.23,"semantic":0.28,"sentence":0.50,"paragraph":0.62,"section":0.70},
}
PUNCT_KIND={"、":"comma","，":"comma",",":"comma","；":"semantic",";":"semantic","：":"semantic",":":"semantic","。":"sentence","！":"sentence","？":"sentence","!":"sentence","?":"sentence"}
NUMBER_RE=re.compile(
    r"(?:[0-9０-９]{4}年(?:[0-9０-９]{1,2}月(?:[0-9０-９]{1,2}日)?)?|"
    r"[0-9０-９]{1,2}月[0-9０-９]{1,2}日|"
    r"[0-9０-９]+(?:[\.．,，][0-9０-９]+)?(?:兆|億|万)?(?:％|%|円|ドル|ユーロ|人|件|戸|台|社|キロ|km|キロメートル|メートル|度|時|分|秒|日間|週間|か月|ヶ月|年))"
)


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
    for i,p in enumerate(body_paragraphs(a)):parts.append({"key":f"body-{i}","spoken":p,"text":p})
    if why:parts.append({"key":"why","spoken":f"このニュースの重要なポイントです。{why}","text":why})
    if watch:parts.append({"key":"watch","spoken":f"今後は、{watch}","text":watch})
    return parts


def narration_text(segments):return "\n".join(s["spoken"] for s in segments)


def reading_chars(text):
    return sum(1 for ch in clean(text) if not ch.isspace() and ch not in "。！？!?、，,.;；:：・（）()[]【】『』「」\"'—–-")


def content_hash(text,group):
    pause_sig=json.dumps(PAUSES[group],sort_keys=True,separators=(",",":"))
    settings=f"{DELIVERY_PROFILE}|{VOICE}|{LANG}|{TOTAL_STEPS}|{SPEED}|{MAX_CHUNK}|{SYNTH_SILENCE}|{TARGET_CPM[group]}|{pause_sig}|{text}"
    return hashlib.sha256(settings.encode("utf-8")).hexdigest()


def load_manifest():
    if MANIFEST.exists():
        try:return json.loads(MANIFEST.read_text(encoding="utf-8"))
        except Exception:return {}
    return {}


def punctuation_pieces(text):
    text=clean(text)
    if not text:return []
    out=[];start=0
    for m in re.finditer(r"[。！？!?、，,；;：:]",text):out.append(text[start:m.end()]);start=m.end()
    if start<len(text):out.append(text[start:])
    return [p for p in out if p]


def natural_boundary(core):
    if len(core)<28:return None
    patterns=(
        r"^(.{12,30}?(?:については|によると|では|には|は|が))(.{10,})$",
        r"^(.{14,32}?(?:ため|ことから|により|によって|として|について|を受けて|を受け))(.{10,})$",
        r"^(.{16,34}?を)(.{10,})$",
    )
    for pattern in patterns:
        m=re.match(pattern,core)
        if m:return (m.group(1),m.group(2),"semantic")
    return None


def number_boundary(core):
    if len(core)<24:return None
    for m in NUMBER_RE.finditer(core):
        left=core[:m.start()];num=m.group(0);right=core[m.end():]
        if len(left)>=9 and len(right)>=8:return (left,num,right)
    return None


def semantic_chunks(core):
    if not core:return []
    first=natural_boundary(core)
    if first:
        left,right,kind=first
        chunks=[{"text":left,"pause_kind":kind,"reason":"semantic-boundary"},{"text":right,"pause_kind":None,"reason":"continuation"}]
    else:chunks=[{"text":core,"pause_kind":None,"reason":"clause"}]
    refined=[]
    for chunk in chunks:
        numeric=number_boundary(chunk["text"])
        if not numeric:refined.append(chunk);continue
        left,num,right=numeric
        if left:refined.append({"text":left,"pause_kind":"micro","reason":"before-key-number"})
        refined.append({"text":num,"pause_kind":"micro","reason":"key-number"})
        if right:refined.append({"text":right,"pause_kind":chunk.get("pause_kind"),"reason":"after-key-number"})
    return refined


def delivery_units(segments,group):
    units=[]
    for seg in segments:
        local=[]
        for piece in punctuation_pieces(seg["spoken"]):
            mark=piece[-1] if piece and piece[-1] in PUNCT_KIND else "";core=piece[:-1] if mark else piece
            chunks=semantic_chunks(core)
            if not chunks:continue
            if mark:chunks[-1]["text"]+=mark
            final_kind=PUNCT_KIND.get(mark)
            if final_kind:chunks[-1]["pause_kind"]=final_kind;chunks[-1]["reason"]=f"punctuation-{final_kind}"
            local.extend(chunks)
        if not local:continue
        boundary="paragraph" if seg["key"].startswith("body-") else "section"
        boundary_pause=PAUSES[group][boundary]
        last_kind=local[-1].get("pause_kind");last_pause=PAUSES[group].get(last_kind,0.0) if last_kind else 0.0
        local[-1]["forced_pause"]=max(last_pause,boundary_pause)
        for u in local:
            kind=u.get("pause_kind");pause=u.pop("forced_pause",None)
            if pause is None:pause=PAUSES[group].get(kind,0.0) if kind else 0.0
            text=clean(u["text"])
            if text:units.append({"parentKey":seg["key"],"text":text,"pause":round(float(pause),3),"reason":u.get("reason") or kind or "clause","parentText":seg["text"]})
    return units


def audio_duration(path):
    p=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],check=True,capture_output=True,text=True)
    return float(p.stdout.strip())


def mp3_from_wav(wav_path,mp3_path):
    subprocess.run(["ffmpeg","-y","-hide_banner","-loglevel","error","-i",str(wav_path),"-codec:a","libmp3lame","-b:a","96k","-ar",str(SAMPLE_RATE),"-ac","1",str(mp3_path)],check=True)


def atempo_chain(factor):
    factor=float(factor);parts=[]
    while factor<0.5:parts.append(0.5);factor/=0.5
    while factor>2.0:parts.append(2.0);factor/=2.0
    parts.append(factor)
    return ",".join(f"atempo={v:.6f}" for v in parts)


def rate_plan(waves,units,text,target_cpm):
    raw_speech=sum(w.shape[1] for w in waves)/SAMPLE_RATE
    desired_pauses=sum(float(u["pause"]) for u in units)
    chars=reading_chars(text)
    target_total=(chars*60.0/target_cpm) if chars else raw_speech+desired_pauses
    desired_speech=max(raw_speech,target_total-desired_pauses)
    factor=max(0.20,min(1.0,raw_speech/desired_speech if desired_speech>0 else 1.0))
    return {"chars":chars,"rawSpeech":raw_speech,"desiredPause":desired_pauses,"targetTotal":target_total,"factor":factor}


def build_raw_audio(waves,units,factor):
    pieces=[];rows=[];cursor=0
    for wav,u in zip(waves,units):
        start=cursor/SAMPLE_RATE;pieces.append(wav);cursor+=wav.shape[1];speech_end=cursor/SAMPLE_RATE
        pre_pause=float(u["pause"])*factor
        if pre_pause>0:
            silence=np.zeros((1,max(1,int(round(SAMPLE_RATE*pre_pause)))),dtype=wav.dtype);pieces.append(silence);cursor+=silence.shape[1]
        end=cursor/SAMPLE_RATE
        rows.append({**u,"start":start,"speechEnd":speech_end,"end":end,"prePause":pre_pause})
    return np.concatenate(pieces,axis=1),rows


def pace_wav(src,dst,factor):
    if factor>=0.999:
        shutil.copyfile(src,dst);return
    subprocess.run(["ffmpeg","-y","-hide_banner","-loglevel","error","-i",str(src),"-filter:a",atempo_chain(factor),"-ar",str(SAMPLE_RATE),"-ac","1",str(dst)],check=True)


def timing_payload(out,segments,rows,raw_duration,plan,group):
    mp3_duration=audio_duration(out);scale=(mp3_duration/raw_duration) if raw_duration>0 else 1.0
    semantic=[]
    for row in rows:
        semantic.append({"parentKey":row["parentKey"],"start":round(row["start"]*scale,3),"speechEnd":round(row["speechEnd"]*scale,3),"end":round(row["end"]*scale,3),"pause":round(row["prePause"]*scale,3),"intendedPause":row["pause"],"reason":row["reason"],"text":row["text"]})
    timeline=[]
    for seg in segments:
        items=[r for r in semantic if r["parentKey"]==seg["key"]]
        if items:timeline.append({"key":seg["key"],"start":items[0]["start"],"end":items[-1]["end"],"text":seg["text"]})
    if timeline:timeline[-1]["end"]=round(mp3_duration,3)
    if semantic:semantic[-1]["end"]=round(mp3_duration,3)
    chars=plan["chars"]
    return {"version":TIMING_VERSION,"duration":round(mp3_duration,3),"voice":VOICE,"language":LANG,"speed":SPEED,"deliveryProfile":DELIVERY_PROFILE,"targetMaxCharactersPerMinute":TARGET_CPM[group],"characters":chars,"charactersPerMinute":round(chars*60.0/mp3_duration,1) if mp3_duration>0 else 0.0,"tempoCalibrationFactor":round(plan["factor"],4),"pauseProfile":PAUSES[group],"segments":timeline,"semanticUnits":semantic}


def timing_current(path,group):
    if not path.exists():return False
    try:
        t=json.loads(path.read_text(encoding="utf-8"))
        return t.get("version")==TIMING_VERSION and t.get("deliveryProfile")==DELIVERY_PROFILE and abs(float(t.get("speed",0))-SPEED)<0.001 and float(t.get("targetMaxCharactersPerMinute",0))==TARGET_CPM[group]
    except Exception:return False


def collect_records(manifest):
    records=[];wanted=set();datasets=[]
    for data_path,list_key,group in DATASETS:
        if not data_path.exists():continue
        data=json.loads(data_path.read_text(encoding="utf-8"));changed=False
        out_dir=AUDIO_ROOT/group;out_dir.mkdir(parents=True,exist_ok=True);timing_dir=TIMING_ROOT/group;timing_dir.mkdir(parents=True,exist_ok=True)
        for a in data.get(list_key,[]):
            aid=a.get("id");segments=narration_segments(a)
            if not aid or not segments:continue
            text=narration_text(segments);key=f"{group}:{aid}";wanted.add(key);digest=content_hash(text,group);out=out_dir/f"{aid}.mp3";timing=timing_dir/f"{aid}.json"
            expected_audio=f"audio/{group}/{aid}.mp3";expected_timing=f"audio/timing/{group}/{aid}.json"
            if a.get("audio")!=expected_audio:a["audio"]=expected_audio;changed=True
            if a.get("timing")!=expected_timing:a["timing"]=expected_timing;changed=True
            if a.get("audioSpeed")!=SPEED:a["audioSpeed"]=SPEED;changed=True
            if a.get("audioDeliveryProfile")!=DELIVERY_PROFILE:a["audioDeliveryProfile"]=DELIVERY_PROFILE;changed=True
            needs_audio=not out.exists() or manifest.get(key)!=digest or not timing_current(timing,group)
            records.append((key,group,segments,digest,out,timing,needs_audio))
        datasets.append((data_path,data,changed))
    return records,wanted,datasets


def remove_stale(manifest,wanted):
    for group in ("daily","live"):
        folder=AUDIO_ROOT/group
        if folder.exists():
            for old in folder.glob("*.mp3"):
                key=f"{group}:{old.stem}"
                if key not in wanted:old.unlink();manifest.pop(key,None)
        tfolder=TIMING_ROOT/group
        if tfolder.exists():
            for old in tfolder.glob("*.json"):
                if f"{group}:{old.stem}" not in wanted:old.unlink()


def synthesize_record(tts,style,group,segments,out,timing):
    units=delivery_units(segments,group)
    if not units:raise RuntimeError("empty delivery units")
    waves=[]
    for u in units:
        wav,_=tts.synthesize(text=u["text"],voice_style=style,total_steps=TOTAL_STEPS,speed=SPEED,max_chunk_length=MAX_CHUNK,silence_duration=SYNTH_SILENCE,lang=LANG,verbose=False)
        if wav.ndim==1:wav=wav.reshape(1,-1)
        waves.append(wav)
    text=narration_text(segments);plan=rate_plan(waves,units,text,TARGET_CPM[group]);combined,rows=build_raw_audio(waves,units,plan["factor"]);raw_duration=combined.shape[1]/SAMPLE_RATE
    with tempfile.TemporaryDirectory() as td:
        raw_wav=Path(td)/"raw.wav";paced_wav=Path(td)/"paced.wav";tts.save_audio(combined,str(raw_wav));pace_wav(raw_wav,paced_wav,plan["factor"]);mp3_from_wav(paced_wav,out)
    payload=timing_payload(out,segments,rows,raw_duration,plan,group);timing.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");return payload


def main():
    AUDIO_ROOT.mkdir(exist_ok=True);TIMING_ROOT.mkdir(parents=True,exist_ok=True);manifest=load_manifest();records,wanted,datasets=collect_records(manifest);remove_stale(manifest,wanted);jobs=[r for r in records if r[6]]
    if jobs:
        tts=TTS(auto_download=True);style=tts.get_voice_style(voice_name=VOICE)
        for key,group,segments,digest,out,timing,_ in jobs:
            payload=synthesize_record(tts,style,group,segments,out,timing);manifest[key]=digest;print("generated",out,"cpm",payload.get("charactersPerMinute"),"profile",DELIVERY_PROFILE)
    else:print("F3 semantic-paced audio is already current")
    for key,group,segments,digest,out,timing,_ in records:
        if not out.exists():raise RuntimeError(f"missing audio after generation: {out}")
        if not timing_current(timing,group):raise RuntimeError(f"missing/current timing metadata: {timing}")
    for data_path,data,changed in datasets:
        if changed:data_path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    MANIFEST.write_text(json.dumps({k:manifest[k] for k in sorted(manifest) if k in wanted},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"F3 delivery profile {DELIVERY_PROFILE}; base speed {SPEED:.2f}; Daily <= {TARGET_CPM['daily']:.0f} cpm; Live <= {TARGET_CPM['live']:.0f} cpm")

if __name__=="__main__":main()
