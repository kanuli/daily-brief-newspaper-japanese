#!/usr/bin/env python3
"""Generate Rolling/Topic Supertonic F3 audio in small record batches."""
import gc
import json
import os

import generate_supertonic_f3_rolling as rolling

base = rolling.base
BATCH_SIZE = max(1, int(os.getenv("F3_RECORD_BATCH_SIZE", "3")))


def write_manifest(manifest, wanted):
    rolling.MANIFEST.write_text(
        json.dumps(
            {k: manifest[k] for k in sorted(wanted) if k in manifest},
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def main():
    paths = rolling.data_paths()
    if not paths:
        raise RuntimeError("No rolling/topic Japanese data found; run sync_cantonese_layers.py first")

    rolling.AUDIO_ROOT.mkdir(parents=True, exist_ok=True)
    rolling.TIMING_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = rolling.load_manifest()
    datasets = []
    records = {}
    wanted = set()

    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for story in rolling.iter_stories(data):
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
            digest = rolling.current_digest(segments)
            out = rolling.AUDIO_ROOT / f"{aid}.mp3"
            timing = rolling.TIMING_ROOT / f"{aid}.json"
            wanted.add(aid)
            records[aid] = (segments, digest, out, timing)
        datasets.append((path, data, changed))

    for old in rolling.AUDIO_ROOT.glob("*.mp3"):
        if old.stem not in wanted:
            old.unlink()
            manifest.pop(old.stem, None)
    for old in rolling.TIMING_ROOT.glob("*.json"):
        if old.stem not in wanted:
            old.unlink()

    jobs = []
    for aid, (segments, digest, out, timing) in records.items():
        if not out.exists() or manifest.get(aid) != digest or not base.timing_current(timing, rolling.GROUP):
            jobs.append((aid, segments, digest, out, timing))

    if jobs:
        tts = base.TTS(auto_download=True)
        style = tts.get_voice_style(voice_name=base.VOICE)
        total_batches = (len(jobs) + BATCH_SIZE - 1) // BATCH_SIZE
        for batch_no, start in enumerate(range(0, len(jobs), BATCH_SIZE), 1):
            batch = jobs[start:start + BATCH_SIZE]
            print(
                f"F3_RECORD_BATCH rolling {batch_no}/{total_batches} "
                f"records={len(batch)} batch_size={BATCH_SIZE}"
            )
            for aid, segments, digest, out, timing in batch:
                payload = base.synthesize_record(tts, style, rolling.GROUP, segments, out, timing)
                manifest[aid] = digest
                print("generated rolling", out, "cpm", payload.get("charactersPerMinute"))
            write_manifest(manifest, wanted)
            gc.collect()
    else:
        print("Rolling F3 audio is already current")

    for aid, (_segments, digest, out, timing) in records.items():
        if not out.exists():
            raise RuntimeError(f"missing rolling audio after generation: {out}")
        if not base.timing_current(timing, rolling.GROUP):
            raise RuntimeError(f"missing/current rolling timing metadata: {timing}")
        manifest[aid] = digest

    for path, data, changed in datasets:
        if changed:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    write_manifest(manifest, wanted)
    print(
        f"ROLLING_F3_CHUNKED_OK stories={len(records)} generated={len(jobs)} "
        f"batch_size={BATCH_SIZE}; semantic max_chunk={base.MAX_CHUNK}"
    )


if __name__ == "__main__":
    main()
