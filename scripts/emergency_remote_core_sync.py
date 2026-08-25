#!/usr/bin/env python3
"""Remote-only emergency rebuild for Daily/Live/Archive Japanese publication.

This is deliberately independent of torch/transformers/OPUS-MT. It is used only
when the normal local-model sync job fails. It rebuilds against the run's frozen
Cantonese snapshot using the validated free remote translation chain, preserves
all production quality gates, regenerates furigana/audio metadata paths, and
writes only clean core data plus the validated translation cache.
"""
from __future__ import annotations

import cantonese_snapshot as snapshot
import furigana_safe_runtime
import safe_sync as safe
import sync_and_translate as base


def snapshot_fetch(name: str):
    return snapshot.load_json(name)


def main():
    # Freeze all base.fetch() calls to the snapshot created by this workflow run
    # so source parity cannot move underneath a recovery already in progress.
    base.fetch = snapshot_fetch
    furigana_safe_runtime.install()
    safe.main()
    print(
        "EMERGENCY_REMOTE_CORE_SYNC_OK",
        f"snapshot={snapshot.snapshot_commit()}",
    )


if __name__ == "__main__":
    main()
