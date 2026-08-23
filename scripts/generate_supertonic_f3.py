#!/usr/bin/env python3
import json,re,subprocess,tempfile
from pathlib import Path
from supertonic import TTS

DATA=Path("data/latest.json")
AUDIO=Path("audio")
VOICE="F3"
LANG="ja"
TOTAL_STEPS=8
SPEED=1.00
MAX_CHUNK=220
SILENCE=0.34

def clean(text):
    text=re.sub(r"https?://\S+","",str(text or ""))
    text=re.sub(r"\s+"," ",text).strip()
    return text

def narration(a):
    # Japanese TV-news-like cadence: headline, short pause, facts, significance, next watch item.
    parts=[]
    title=clean(a.get("title"));dek=clean(a.get("dek"));body=clean(a.get("body") or a.get("summary"));why=clean(a.get("why"));watch=clean(a.get("watchNext"))
    if title:parts.append(f"{title}。")
    if dek:parts.append(dek)
    if body:parts.append(body)
    if why:parts.append(f"このニュースの重要なポイントです。{why}")
    if watch:parts.append(f"今後は、{watch}")
    return "\n".join(parts)

def mp3_from_wav(wav_path,mp3_path):
    subprocess.run(["ffmpeg","-y","-hide_banner","-loglevel","error","-i",str(wav_path),"-codec:a","libmp3lame","-b:a","96k","-ar","44100","-ac","1",str(mp3_path)],check=True)

def main():
    if not DATA.exists():raise SystemExit("data/latest.json is missing")
    data=json.loads(DATA.read_text(encoding="utf-8"))
    AUDIO.mkdir(exist_ok=True)
    wanted={a.get("id") for a in data.get("articles",[]) if a.get("id")}
    for old in AUDIO.glob("*.mp3"):
        if old.stem not in wanted:old.unlink()
    tts=TTS(auto_download=True)
    style=tts.get_voice_style(voice_name=VOICE)
    for a in data.get("articles",[]):
        aid=a.get("id");text=narration(a)
        if not aid or not text:continue
        out=AUDIO/f"{aid}.mp3"
        # Recreate each cycle only when file is missing; article IDs change for materially new items.
        if out.exists():continue
        with tempfile.TemporaryDirectory() as td:
            wav_path=Path(td)/"news.wav"
            wav,_=tts.synthesize(text=text,voice_style=style,total_steps=TOTAL_STEPS,speed=SPEED,max_chunk_length=MAX_CHUNK,silence_duration=SILENCE,lang=LANG,verbose=False)
            tts.save_audio(wav,str(wav_path))
            mp3_from_wav(wav_path,out)
        print("generated",out)

if __name__=="__main__":main()
