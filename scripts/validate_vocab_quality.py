#!/usr/bin/env python3
"""Validate learner-facing Japanese vocabulary metadata independently of sync."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "vocab" / "latest.json"
LEVELS = {"N1", "N2", "N3", "N4", "N5"}
KANA_RE = re.compile(r"^[\u3040-\u30ffー・]+$")

# Conservative editorial minimums for words that have already appeared with
# implausibly easy source metadata. These are estimates, not official JLPT lists.
MIN_LEVEL = {
    ("さつがい", "殺害"): "N2",
    ("せいたい", "生体"): "N2",
    ("じょうき", "常軌"): "N1",
}
LEVEL_RANK = {"N5": 1, "N4": 2, "N3": 3, "N2": 4, "N1": 5}


def main() -> int:
    if not PATH.exists():
        print("VOCAB_QUALITY_FAIL\n - data/vocab/latest.json is missing")
        return 1
    data = json.loads(PATH.read_text(encoding="utf-8"))
    issues = []
    seen = set()
    words = data.get("words") or []
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
            issues.append(f"{label}: missing meaning")
        if not pos:
            issues.append(f"{label}: missing part of speech")
        minimum = MIN_LEVEL.get(key)
        if minimum and level in LEVEL_RANK and LEVEL_RANK[level] < LEVEL_RANK[minimum]:
            issues.append(f"{label}: {level} is implausibly easy; editorial minimum is {minimum}")

    if "推定" not in str(data.get("levelNote") or ""):
        issues.append("levelNote must explicitly say JLPT levels are estimates")

    if issues:
        print("VOCAB_QUALITY_FAIL")
        for issue in issues:
            print(" -", issue)
        return 1
    print(f"VOCAB_QUALITY_OK words={len(words)} estimated_levels_validated=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
