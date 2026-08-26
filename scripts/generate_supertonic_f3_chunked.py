#!/usr/bin/env python3
"""Generate Daily/Live Supertonic F3 audio in small record batches.

Each story is already split into semantic speech units by generate_supertonic_f3.
This wrapper adds an outer record-batch layer so a large edition is not handled
as one long undifferentiated queue. The batch size is configurable with
F3_RECORD_BATCH_SIZE (default: 3).

This file is also a production F3 workflow trigger. Keep the input-state log
below: it makes a stale/no-op voice run diagnosable from GitHub Actions without
having to infer freshness from the audio manifest alone.
"""
import gc
import json
import os

import generate_supertonic_f3 as base

BATCH_SIZE = max(1, int(os.getenv("F3_RECORD_BATCH_SIZE", "3")))


def write_manifest(manifest, wanted):
    base.MANIFEST.write_text(
        json.dumps(
            {k: manifest[k] for k in sorted(manifest) if k in wanted},
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def main():
    base.AUDIO_ROOT.mkdir(exist_ok=True)
    base.TIMING_ROOT.mkdir(parents=True, exist_ok=True)
    manifest = base.load_manifest()
    records, wanted, datasets = base.collect_records(manifest)
    base.remove_stale(manifest, wanted)
    jobs = [record for record in records if record[6]]

    dataset_state = []
    for data_path, data, _changed in datasets:
        dataset_state.append(
            {
                "path": str(data_path),
                "date": data.get("date"),
                "lastUpdated": data.get("lastUpdated") or data.get("generatedAt"),
            }
        )
    print(
        "F3_INPUT_STATE",
        json.dumps(
            {
                "records": len(records),
                "pending": len(jobs),
                "manifestEntries": len(manifest),
                "datasets": dataset_state,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
    )

    if jobs:
        tts = base.TTS(auto_download=True)
        style = tts.get_voice_style(voice_name=base.VOICE)
        total_batches = (len(jobs) + BATCH_SIZE - 1) // BATCH_SIZE
        for batch_no, start in enumerate(range(0, len(jobs), BATCH_SIZE), 1):
            batch = jobs[start:start + BATCH_SIZE]
            print(
                f"F3_RECORD_BATCH daily-live {batch_no}/{total_batches} "
                f"records={len(batch)} batch_size={BATCH_SIZE}"
            )
            for key, group, segments, digest, out, timing, _ in batch:
                payload = base.synthesize_record(tts, style, group, segments, out, timing)
                manifest[key] = digest
                print(
                    "generated",
                    out,
                    "cpm",
                    payload.get("charactersPerMinute"),
                    "profile",
                    base.DELIVERY_PROFILE,
                )
            # Local checkpoint between batches. On a persistent server clone this
            # also makes current progress explicit before the next batch begins.
            write_manifest(manifest, wanted)
            gc.collect()
    else:
        print("F3 semantic-paced Daily/Live audio is already current")

    for key, group, _segments, digest, out, timing, _ in records:
        if not out.exists():
            raise RuntimeError(f"missing audio after generation: {out}")
        if not base.timing_current(timing, group):
            raise RuntimeError(f"missing/current timing metadata: {timing}")
        manifest[key] = digest

    for data_path, data, changed in datasets:
        if changed:
            data_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    write_manifest(manifest, wanted)
    print(
        f"F3_CHUNKED_OK daily-live records={len(records)} generated={len(jobs)} "
        f"batch_size={BATCH_SIZE}; semantic max_chunk={base.MAX_CHUNK}"
    )


if __name__ == "__main__":
    main()
