#!/usr/bin/env python3
"""Prewarm selected Cantonese news layers using one frozen snapshot + local MT.

PREWARM_FILES may contain a comma-separated allow-list. Keeping the hourly
Daily/Live publication on a small file group prevents a large rolling backlog
from blocking current-news publication.

If the currently published Japanese field is already known-bad under the
production quality gate, repair that exact source field with the validated free
remote fallback chain before bulk local prewarm. This keeps a poisoned OPUS-MT
decode from consuming the whole hourly recovery window again.
"""
import json
import os
from pathlib import Path

import batch_prewarm as source_helpers
import cantonese_snapshot as snapshot
import local_metadata_overrides as metadata_overrides
import local_translation_runtime as runtime
import safe_sync as safe
import sync_and_translate as base


def selected_files(files):
    raw = str(os.environ.get("PREWARM_FILES") or "").strip()
    if not raw:
        return files
    wanted = {item.strip() for item in raw.split(",") if item.strip()}
    chosen = [(name, payload) for name, payload in files if name in wanted]
    missing = sorted(wanted - {name for name, _payload in chosen})
    if missing:
        raise RuntimeError(f"Requested PREWARM_FILES missing from frozen snapshot: {','.join(missing)}")
    return chosen


def repair_bad_existing_to_cache(files):
    """Remote-repair only fields that are already published and fail quality."""
    repaired = 0
    deferred = 0
    for name, source in files:
        local_path = Path("data") / name
        if not local_path.is_file():
            continue
        try:
            existing = json.loads(local_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print("REMOTE_REPAIR_EXISTING_SKIP", name, type(exc).__name__, exc)
            continue

        src_index = source_helpers.indexed_items(source)
        dst_index = source_helpers.indexed_items(existing)
        for item_id, src_item in src_index.items():
            dst_item = dst_index.get(item_id)
            if not isinstance(dst_item, dict):
                continue
            for key, source_text in src_item.items():
                if (
                    key not in base.TRANSLATE_KEYS
                    or not isinstance(source_text, str)
                    or not source_text.strip()
                ):
                    continue
                current = dst_item.get(key)
                if not isinstance(current, str) or not current.strip():
                    continue
                strict = key in safe.STRICT_PROSE_KEYS
                if safe.target_quality_ok(source_text, current, strict=strict):
                    continue

                print(
                    "REMOTE_REPAIR_EXISTING_FIELD",
                    f"file={name}",
                    f"id={item_id}",
                    f"field={key}",
                    f"old={current[:90]!r}",
                )
                try:
                    value = runtime._remote_quality_fallback(source_text, strict=strict)
                    if not safe.target_quality_ok(source_text, value, strict=strict):
                        raise RuntimeError("remote fallback returned quality-rejected text")
                    base.CACHE[runtime.cache_key(source_text)] = value
                    repaired += 1
                except Exception as exc:
                    # Do not abort the whole edition here. Normal local prewarm
                    # still gets one chance and retains its own validated fallback.
                    base.CACHE.pop(runtime.cache_key(source_text), None)
                    deferred += 1
                    print(
                        "REMOTE_REPAIR_EXISTING_DEFER",
                        f"file={name}",
                        f"id={item_id}",
                        f"field={key}",
                        f"error={type(exc).__name__}:{exc}",
                    )

    runtime.checkpoint_cache("remote-repair-existing")
    print(
        "REMOTE_REPAIR_EXISTING_RESULT",
        f"repaired={repaired}",
        f"deferred={deferred}",
    )
    return repaired


def main():
    base.likely_chinese_source = source_helpers.needs_cantonese_translation
    source_helpers.fetch_json = snapshot.load_json
    metadata_overrides.install(runtime)
    runtime.install()
    safe.prune_cache()

    all_files = source_helpers.source_files()
    files = selected_files(all_files)

    # First recover fields we already know are bad. Then reuse all remaining
    # good rendered Japanese before translating genuinely missing text.
    repair_bad_existing_to_cache(files)
    source_helpers.seed_cache_from_existing(files)

    print("LOCAL_MT_PREWARM_SCOPE", ",".join(name for name, _payload in files))
    for name, payload in files:
        runtime.local_prewarm_translations(payload, name)

    runtime.checkpoint_cache("selected-layers-complete")
    print(
        "LOCAL_MT_SELECTED_LAYERS_OK",
        f"snapshot={snapshot.snapshot_commit()}",
        ",".join(name for name, _payload in files),
        f"cache_entries={len(base.CACHE)}",
    )


if __name__ == "__main__":
    main()
