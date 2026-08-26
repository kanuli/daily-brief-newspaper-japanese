#!/usr/bin/env python3
"""Remote-only self-healing rebuild for Daily/Live/Archive Japanese publication.

This path stays independent of torch/transformers/OPUS-MT. If a remote
translation backend fails for one story, that owner is quarantined while clean
current stories continue to publish. The degraded owner is retried on later
sync/maintenance cycles and is never allowed to poison Japanese publication.
"""
from __future__ import annotations

import cantonese_snapshot as snapshot
import fast_safe_sync as fast
import furigana_safe_runtime
import self_healing_runtime
import sync_and_translate as base


def snapshot_fetch(name: str):
    return snapshot.load_json(name)


def main():
    # Freeze all base.fetch() calls to the snapshot created by this workflow run
    # so source parity cannot move underneath a recovery already in progress.
    base.fetch = snapshot_fetch
    self_healing_runtime.install()
    furigana_safe_runtime.install()
    fast.main()
    print(
        "EMERGENCY_REMOTE_CORE_SYNC_OK",
        f"snapshot={snapshot.snapshot_commit()}",
        "owner_quarantine=true",
    )


if __name__ == "__main__":
    main()
