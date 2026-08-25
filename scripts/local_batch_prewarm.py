#!/usr/bin/env python3
"""Prewarm all Cantonese news layers using local OPUS-MT only."""
import batch_prewarm as source_helpers
import local_translation_runtime as runtime
import safe_sync as safe
import sync_and_translate as base


def main():
    base.likely_chinese_source = source_helpers.needs_cantonese_translation
    runtime.install()
    safe.prune_cache()

    files = source_helpers.source_files()
    source_helpers.seed_cache_from_existing(files)
    for name, payload in files:
        runtime.local_prewarm_translations(payload, name)

    runtime.checkpoint_cache("all-layers-complete")
    print(
        "LOCAL_MT_ALL_LAYERS_OK",
        ",".join(name for name, _payload in files),
        f"cache_entries={len(base.CACHE)}",
    )


if __name__ == "__main__":
    main()
