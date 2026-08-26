#!/usr/bin/env python3
"""Remote-only self-healing rebuild for Daily/Live/Archive Japanese publication.

This path stays independent of torch/transformers/OPUS-MT. It ensures the small
lexical furigana dependencies are present even when the emergency GitHub job was
started with the legacy minimal dependency set, then applies the same newsroom
and furigana standards as the normal publication path.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys


def ensure_lexical_furigana_dependencies() -> None:
    if importlib.util.find_spec("sudachipy") is not None:
        return
    print("EMERGENCY_INSTALL_SUDACHI lexical_furigana_required=true")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--quiet",
            "SudachiPy==0.6.11",
            "SudachiDict-core==20260723",
        ],
        check=True,
    )


ensure_lexical_furigana_dependencies()

import cantonese_snapshot as snapshot
import fast_safe_sync as fast
import furigana_safe_runtime
import newsroom_postedit_core
import newsroom_quality
import safe_sync as safe
import self_healing_runtime
import sync_and_translate as base


def snapshot_fetch(name: str):
    return snapshot.load_json(name)


def main():
    base.fetch = snapshot_fetch
    newsroom_quality.install(safe)
    self_healing_runtime.install()
    furigana_safe_runtime.install()
    fast.main()
    newsroom_postedit_core.main()
    print(
        "EMERGENCY_REMOTE_CORE_SYNC_OK",
        f"snapshot={snapshot.snapshot_commit()}",
        "owner_quarantine=true",
        f"furigana_engine={furigana_safe_runtime.engine_name()}",
        "newsroom_quality=true",
    )


if __name__ == "__main__":
    main()
