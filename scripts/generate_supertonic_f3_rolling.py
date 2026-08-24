#!/usr/bin/env python3
"""Generate Supertonic 3 F3 audio for Cantonese-derived rolling/topic stories."""
import json
from pathlib import Path

import generate_supertonic_f3 as base

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
AUDIO_ROOT = ROOT / "audio/rolling"
TIMING_ROOT = ROOT / "audio/timing/rolling"
MANIFEST = ROOT / "audio/rolling-manifest.json"
GROUP = "rolling"

base.TARGET_CPM[GROUP] = base.TARGET_CPM["daily"]
base.PAUSES[GROUP] = dict(base.PAUSES["daily"])


def story_like(value):
    return (
        isinstance(value, dict)
        and isinstance(value.get("id"), str)
        and bool(value.get("id"))
        and isinstance(value.get("title"), str)
        and bool(value.get("title"))
        and any(value.get(k) for k in ("dek", "summary", "body"))
    )


def iter_stories(value):
    if story_like(value):
        yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from iter_stories(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_stories(child)


def data_paths():
    out = []
    for name in ("desk-latest.json", "stocks-latest.json"):
        path = DATA_ROOT / name
        if path.is_file():
            out.append(path)
    topic = DATA_ROOT / "topic-more"
    if topic.is_dir():
        out.extend(sorted(topic.glob("*.json")))
    return out


def load_manifest():
    if not MANIFEST.is_file():
        return {}
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return {}


def current_digest(segments):
    text = base.narration_text(segments)
    return base.content_hash(text, GROUP)


def main():
    paths = data_paths()
    if not paths:
        raise RuntimeError("No rolling/topic Japanese data found; run sync_cantonese_layers.py first")

    AUDIO_ROOT.mkdir(parents=True, exist_ok=True)
    TIMING_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    datasets = []
    records = {}
    wanted = set()

    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for story in iter_stories(data):
            aid = story.get("id")
            segments = base.narration_segments(story)
            if not aid or not segments:
                continue
            expected_audio = f"audio/rolling/{aid}.mp3"
            expected_timing = f"audio/timing/rolling/{aid}.json"
            if story.get("audio") != expected_audio:
                story["audio"] = expected_audio
                changed = True
            if story.get("timing") != expected_timing:
                story["timing"] = expected_timing
                changed = True
            if story.get("audioSpeed") != base.SPEED:
                story["audioSpeed"] = base.SPEED
                changed = True
            if story.get("audioDeliveryProfile") != base.DELIVERY_PROFILE:
                story["audioDeliveryProfile"] = base.DELIVERY_PROFILE
                changed = True
            digest = current_digest(segments)
            out = AUDIO_ROOT / f"{aid}.mp3"
            timing = TIMING_ROOT / f"{aid}.json"
            wanted.add(aid)
            records[aid] = (segments, digest, out, timing)
        datasets.append((path, data, changed))

    for old in AUDIO_ROOT.glob("*.mp3"):
        if old.stem not in wanted:
            old.unlink()
            manifest.pop(old.stem, None)
    for old in TIMING_ROOT.glob("*.json"):
        if old.stem not in wanted:
            old.unlink()

    jobs = []
    for aid, (segments, digest, out, timing) in records.items():
        if not out.exists() or manifest.get(aid) != digest or not base.timing_current(timing, GROUP):
            jobs.append((aid, segments, digest, out, timing))

    if jobs:
        tts = base.TTS(auto_download=True)
        style = tts.get_voice_style(voice_name=base.VOICE)
        for aid, segments, digest, out, timing in jobs:
            payload = base.synthesize_record(tts, style, GROUP, segments, out, timing)
            manifest[aid] = digest
            print("generated rolling", out, "cpm", payload.get("charactersPerMinute"))
    else:
        print("Rolling F3 audio is already current")

    for aid, (_, digest, out, timing) in records.items():
        if not out.exists():
            raise RuntimeError(f"missing rolling audio after generation: {out}")
        if not base.timing_current(timing, GROUP):
            raise RuntimeError(f"missing/current rolling timing metadata: {timing}")
        manifest[aid] = digest

    for path, data, changed in datasets:
        if changed:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    MANIFEST.write_text(
        json.dumps({k: manifest[k] for k in sorted(wanted)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"ROLLING_F3_OK {len(records)} stories; generated {len(jobs)}")


if __name__ == "__main__":
    main()
