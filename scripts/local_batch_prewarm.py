#!/usr/bin/env python3
"""Prewarm selected Cantonese news layers using one frozen snapshot + local MT.

PREWARM_FILES may contain a comma-separated allow-list.  Keeping the hourly
Daily/Live publication on a small file group prevents a large rolling backlog
from blocking current-news publication.
"""
import os

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


def main():
    base.likely_chinese_source = source_helpers.needs_cantonese_translation
    source_helpers.fetch_json = snapshot.load_json
    metadata_overrides.install(runtime)
    runtime.install()
    safe.prune_cache()

    all_files = source_helpers.source_files()
    files = selected_files(all_files)
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
