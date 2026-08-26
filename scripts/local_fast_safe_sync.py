#!/usr/bin/env python3
"""Run Daily/Live/Archive conversion from one frozen Cantonese snapshot."""
import batch_prewarm as detector
import cantonese_snapshot as snapshot
import fast_safe_sync as fast
import furigana_safe_runtime as furigana_safe
import local_metadata_overrides as metadata_overrides
import local_translation_runtime as runtime
import newsroom_quality
import safe_sync as safe
import self_healing_runtime as self_healing
import sync_and_translate as base


def main():
    base.likely_chinese_source = detector.needs_cantonese_translation
    base.fetch = lambda name: snapshot.load_json(name, optional=True)
    newsroom_quality.install(safe)
    metadata_overrides.install(runtime)
    runtime.install()
    self_healing.install()
    furigana_safe.install()
    fast.main()


if __name__ == "__main__":
    main()
