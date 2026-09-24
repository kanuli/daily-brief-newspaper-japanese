#!/usr/bin/env python3
"""Run current Daily/Live conversion from one frozen Cantonese snapshot.

The previous OPUS-MT bulk path became the publication bottleneck: low-quality
local decodes caused serial repair calls until the workflow timed out. The
existing fast_safe_sync runtime already provides bounded, concurrent remote
translation plus owner-level quarantine, so current news uses that path
instead. Historical archive regeneration is intentionally excluded here;
current Daily/Live publication must recover first and must not backfill old
editions during an outage.
"""
import batch_prewarm as detector
import cantonese_snapshot as snapshot
import current_sync_overrides
import fast_safe_sync as fast
import furigana_safe_runtime as furigana_safe
import newsroom_quality
import safe_sync as safe
import self_healing_runtime as self_healing
import sync_and_translate as base


CURRENT_FILES = ("latest.json", "live.json")


def main():
    base.FILES = CURRENT_FILES
    base.likely_chinese_source = detector.needs_cantonese_translation
    base.fetch = lambda name: snapshot.load_json(name, optional=True)
    current_sync_overrides.install(base, safe)
    newsroom_quality.install(safe)
    self_healing.install()
    furigana_safe.install()
    fast.main()


if __name__ == "__main__":
    main()
