#!/usr/bin/env python3
"""Ensure a prewarm miss never becomes a published fallback by itself.

Prewarming is only an optimization. A story marked deferred during prewarm must
still receive the normal per-story translation attempt. Only that real attempt
may determine whether recovery fails.
"""
from __future__ import annotations


CURRENT_FILES = {"latest.json", "live.json"}


def install(self_healing_module) -> None:
    if getattr(self_healing_module, "_prewarm_retry_runtime_installed", False):
        return

    original = self_healing_module.resilient_prewarm

    def prewarm_then_retry(source, label):
        result = original(source, label)
        if label in CURRENT_FILES:
            deferred = set(self_healing_module._DEFERRED.get(label, set()))
            if deferred:
                # Do not let an optimization failure bypass the actual
                # per-story translation attempt in _convert_story_list().
                self_healing_module._DEFERRED[label].clear()
                print(
                    "PREWARM_DEFERRED_RETRY_FORCED",
                    f"file={label}",
                    f"owners={len(deferred)}",
                    "fallback_from_prewarm=false",
                )
        return result

    self_healing_module.resilient_prewarm = prewarm_then_retry
    # Keep fast_safe_sync's public hook aligned with the module-global function.
    self_healing_module.fast.prewarm_translations = prewarm_then_retry
    self_healing_module._prewarm_retry_runtime_installed = True
    print("PREWARM_RETRY_RUNTIME_INSTALLED actual_story_translation_required=true")
