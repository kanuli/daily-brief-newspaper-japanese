#!/usr/bin/env python3
import hashlib,json,re,subprocess,tempfile
from pathlib import Path
from supertonic import TTS

DATASETS=((Path("data/latest.json"),"articles","daily"),(Path("data/live.json"),"items","live"))
AUDIO_ROOT=Path("audio")
MANIFEST=AUDIO_ROOT/"manifest.json"
VOICE="F3"
LANG="ja"
TOTAL_STEPS=8
SPEED=1.00
MAX_CHUNK=220
SILENCE=0.34

def clean(text):
    text=re.sub(r"https?://\S+","",str(text or ""))
    return re.sub(r"\s+"," ",text).strip()

def narration(a):
    parts=[]
    title=clean(a.get("title"));dek=clean(a.get("dek"));body=clean(a.get("body") or a.get("summary"));why=clean(a.get("why"));watch=clean(a.get("watchNext"))
    if title:parts.append(f"{title}。")
    if dek:parts.append(dek)
    if body:parts.append(body)
    if why:parts.append(f"このニュースの重要なポイントです。{why}")
    if watch:parts.append(f"今後は、{watch}")
    return "\n".join(parts)

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

def collect_jobs(manifest):
    jobs=[];wanted=set()
    for data_path,list_key,group in DATASETS:
        if not data_path.exists():continue
        data=json.loads(data_path.read_text(encoding="utf-8"))
        out_dir=AUDIO_ROOT/group;out_dir.mkdir(parents=True,exist_ok=True)
        for a in data.get(list_key,[]):
            aid=a.get("id");text=narration(a)
            if not aid or not text:continue
            key=f"{group}:{aid}";wanted.add(key)
            digest=content_hash(text);out=out_dir/f"{aid}.mp3"
            if out.exists() and manifest.get(key)==digest:continue
            jobs.append((key,text,digest,out))
    return jobs,wanted

def remove_stale(manifest,wanted):
    for group in ("daily","live"):
        folder=AUDIO_ROOT/group
        if not folder.exists():continue
        for old in folder.glob("*.mp3"):
            key=f"{group}:{old.stem}"
            if key not in wanted:
                old.unlink();manifest.pop(key,None)

def main():
    AUDIO_ROOT.mkdir(exist_ok=True)
    manifest=load_manifest()
    jobs,wanted=collect_jobs(manifest)
    remove_stale(manifest,wanted)
    if jobs:
        tts=TTS(auto_download=True)
        style=tts.get_voice_style(voice_name=VOICE)
        for key,text,digest,out in jobs:
            with tempfile.TemporaryDirectory() as td:
                wav_path=Path(td)/"news.wav"
                wav,_=tts.synthesize(text=text,voice_style=style,total_steps=TOTAL_STEPS,speed=SPEED,max_chunk_length=MAX_CHUNK,silence_duration=SILENCE,lang=LANG,verbose=False)
                tts.save_audio(wav,str(wav_path))
                mp3_from_wav(wav_path,out)
            manifest[key]=digest
            print("generated",out)
    else:
        print("F3 audio is already current")
    MANIFEST.write_text(json.dumps({k:manifest[k] for k in sorted(manifest) if k in wanted},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

if __name__=="__main__":main()
