#!/usr/bin/env python3
"""Deterministic Japanese localization for short pipeline/status metadata.

This module only handles short operational labels whose meaning is fixed.  It
must never translate article prose.  Keeping these labels local prevents a
single mixed Cantonese/Japanese status string from aborting news publication.
"""
from __future__ import annotations


def install(runtime) -> None:
    original = runtime.deterministic_time_label

    def deterministic_time_label(text: str):
        value = str(text or "").strip()
        if value and len(value) <= 140 and "\n" not in value:
            localized = value.replace("下一輪", "次回").replace("下一次", "次回")
            if localized != value:
                # After 下一輪/下一次 is localized, the remaining tokens in this
                # operational label (Live / 更新 / HKT / time) are already valid
                # Japanese/site metadata. Return it directly; sending it back to
                # the old quality guard would reject an unchanged metadata label.
                print(
                    "LOCAL_MT_METADATA_OVERRIDE",
                    f"source={value!r}",
                    f"target={localized!r}",
                )
                return localized
        return original(text)

    runtime.deterministic_time_label = deterministic_time_label
