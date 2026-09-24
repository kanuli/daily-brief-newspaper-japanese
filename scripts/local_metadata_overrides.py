#!/usr/bin/env python3
"""Deterministic Japanese localization for short pipeline/status metadata.

This module only handles short operational labels whose meaning is fixed. It
must never translate article prose. Keeping these labels local prevents a
single mixed Cantonese/Japanese status string from aborting news publication.
"""
from __future__ import annotations

import re

_TIMEZONE_HINT_RE = re.compile(r"(?:HKT|UTC|JST|\bET\b)", re.I)


def install(runtime) -> None:
    original = runtime.deterministic_time_label

    def deterministic_time_label(text: str):
        value = str(text or "").strip()

        # Article sentences often contain a calendar date plus words such as
        # 截至/公布/更新.  The old runtime treated those sentences as operational
        # labels and replaced isolated tokens inside Cantonese prose.  Long
        # date-only text is prose; only explicit timezone labels may be longer.
        if len(value) > 60 and not _TIMEZONE_HINT_RE.search(value):
            return None

        if value and len(value) <= 140 and "\n" not in value:
            localized = value.replace("下一輪", "次回").replace("下一次", "次回")
            if localized != value:
                print(
                    "LOCAL_MT_METADATA_OVERRIDE",
                    f"source={value!r}",
                    f"target={localized!r}",
                )
                return localized
        return original(text)

    runtime.deterministic_time_label = deterministic_time_label
