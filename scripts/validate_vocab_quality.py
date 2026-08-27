#!/usr/bin/env python3
"""Validate the Japanese edition's learner-facing daily vocabulary."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "vocab" / "latest.json"
LEVELS = ("N1", "N2", "N3", "N4", "N5")
KANA_RE = re.compile(r"^[\u3040-\u30ffー・ヽヾゝゞ]+$")
ASCII_DISPLAY_RE = re.compile(r"[A-Za-z0-9@:/\\]")
BLOCKED = {("コム", "COM"), ("のこったぶん", "残った分"), ("アロハ", "アロハ"), ("ビア", "ビア")}


def main() -> int:
    if not PATH.exists():
        print("VOCAB_QUALITY_FAIL\n - data/vocab/latest.json is missing")
        return 1
    data = json.loads(PATH.read_text(encoding="utf-8"))
    issues = []
    seen = set()
    words = data.get("words") or []

    if len(words) != 10:
        issues.append(f"expected exactly 10 words, got {len(words)}")
    if "teacher-core" not in str(data.get("sourceSelectionPolicy") or ""):
        issues.append("sourceSelectionPolicy is not teacher-core gated")
    if data.get("levelMethod") != "upstream-teacher-core-exact-audit-common-direct-grade-A-B":
        issues.append(f"unexpected levelMethod: {data.get('levelMethod')!r}")

    for index, word in enumerate(words):
        reading = str(word.get("reading") or "").strip()
        kanji = str(word.get("kanji") or "").strip()
        level = str(word.get("level") or "").strip()
        meaning = str(word.get("meaning") or "").strip()
        pos = str(word.get("partOfSpeech") or "").strip()
        key = (reading, kanji)
        label = f"words[{index}] {reading}/{kanji or '∅'}"
        if key in seen:
            issues.append(f"{label}: duplicate entry")
        seen.add(key)
        if not reading or not KANA_RE.fullmatch(reading):
            issues.append(f"{label}: reading must be kana")
        if level not in LEVELS:
            issues.append(f"{label}: invalid level {level!r}")
        if not meaning:
            issues.append(f"{label}: missing Japanese meaning")
        if not pos:
            issues.append(f"{label}: missing part-of-speech status")
        if key in BLOCKED:
            issues.append(f"{label}: known unsuitable daily-teaching regression")
        if ASCII_DISPLAY_RE.search(kanji):
            issues.append(f"{label}: ASCII/code-like display is not allowed in JLPT teaching pool")
        if word.get("teacherGrade") not in {"A", "B"}:
            issues.append(f"{label}: teacherGrade must be A/B")
        if word.get("teacherStatus") != "direct":
            issues.append(f"{label}: teacherStatus must be direct")
        if word.get("teacherCommon") is not True:
            issues.append(f"{label}: word must be marked common")
        if word.get("selectionClass") != "teacher-core-common-direct":
            issues.append(f"{label}: wrong selectionClass")

    for level in LEVELS:
        count = sum(1 for word in words if word.get("level") == level)
        if count != 2:
            issues.append(f"{level}: expected 2 words, got {count}")

    date = str(data.get("date") or "")
    archive = PATH.parent / f"{date}.json"
    if not date or not archive.exists():
        issues.append(f"dated archive missing for {date!r}")
    elif json.loads(archive.read_text(encoding="utf-8")) != data:
        issues.append("dated archive does not exactly match latest.json")

    if issues:
        print("VOCAB_QUALITY_FAIL")
        for issue in issues:
            print(" -", issue)
        return 1
    print(f"VOCAB_QUALITY_OK words={len(words)} date={date} teacher_quality_gate=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
