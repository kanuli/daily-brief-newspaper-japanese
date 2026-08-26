#!/usr/bin/env python3
"""Independent editorial hard gate for learner-facing Japanese news.

This validator intentionally does not ask the translation/furigana generator to
validate itself. It checks high-risk semantic reversals, newsroom-language
failure patterns, protected furigana readings, section-state ambiguity and
source->Japanese invariants when the pinned Cantonese snapshot is available.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCE_DIR = Path(os.environ.get("CANTONESE_SNAPSHOT_DIR", "")).resolve() if os.environ.get("CANTONESE_SNAPSHOT_DIR") else None
PROSE_FIELDS = ("title", "dek", "summary", "body", "context", "why", "watchNext")

DISASTER_RE = re.compile(r"(?:洪水|鉄砲水|地滑り|土砂崩れ|地震|津波|台風|ハリケーン|火災|雪崩|崩落|災害|豪雨|暴風|噴火)")
VIOLENCE_RE = re.compile(r"(?:殺人|殺害|銃撃|槍撃|攻撃|襲撃|爆撃|戦闘|テロ|武装|暴行|刺殺|射殺)")
SOURCE_DEATH_RE = re.compile(r"(?:死亡|死者|喪生|罹難|遇難|身亡)")
SOURCE_VIOLENCE_RE = re.compile(r"(?:殺害|殺死|槍殺|謀殺|攻擊|襲擊|槍擊|刺殺|射殺|恐襲)")
SOURCE_UP_RE = re.compile(r"(?:上升|上漲|增加|增長|擴大|升至)")
SOURCE_DOWN_RE = re.compile(r"(?:下降|下跌|減少|縮小|降至)")
TARGET_UP_RE = re.compile(r"(?:上昇|増加|拡大|伸び|高ま|増え)")
TARGET_DOWN_RE = re.compile(r"(?:低下|下落|減少|縮小|落ち|減り)")

# Independent, editorially-owned expected readings. These must not be derived
# from pykakasi/base.ruby_html, otherwise the validator becomes circular.
FORBIDDEN_RUBY = (
    (re.compile(r"<ruby>麻<rt>あさ</rt></ruby>しん"), "麻しん must read ましん, not あさしん"),
    (re.compile(r"<ruby>麻疹<rt>(?!ましん)[^<]+</rt></ruby>"), "麻疹 must read ましん"),
    (re.compile(r"<ruby>氷河<rt>ひょうが</rt></ruby><ruby>湖<rt>みずうみ</rt></ruby>"), "氷河湖 must read ひょうがこ"),
    (re.compile(r"<ruby>土砂崩<rt>どしゃくづ</rt></ruby>れ"), "土砂崩れ must read どしゃくずれ"),
)

HARD_PATTERNS = (
    (re.compile(r"(?:死亡した|死亡している|死亡したことが確認された)\s*\d+\s*人の麻(?:疹|しん)"), "measles/deceased-person relationship is grammatically reversed"),
    (re.compile(r"\d+\s*人の麻(?:疹|しん)(?:です|でした|となりました|となった)"), "people are incorrectly described as measles"),
)

NATURALNESS_WARNINGS = (
    (re.compile(r"大人数のグループ"), "unnatural newsroom phrase: 大人数のグループ"),
    (re.compile(r"パンデミックの影響を悪化"), "awkward causal phrase: パンデミックの影響を悪化"),
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def story_list(name: str, data: dict) -> list[dict]:
    return list(data.get("articles" if name == "latest.json" else "items", []) or [])


def source_story_map(name: str) -> dict[str, dict]:
    if not SOURCE_DIR:
        return {}
    path = SOURCE_DIR / name
    if not path.exists():
        return {}
    try:
        data = load(path)
    except Exception:
        return {}
    return {str(item.get("id")): item for item in story_list(name, data) if item.get("id")}


def text_blob(item: dict) -> str:
    return "\n".join(str(item.get(field) or "") for field in PROSE_FIELDS)


def check_local_story(name: str, item: dict, issues: list[str], warnings: list[str]) -> None:
    aid = str(item.get("id") or "unknown")
    blob = text_blob(item)
    for pattern, message in HARD_PATTERNS:
        if pattern.search(blob):
            issues.append(f"{name}:{aid}: {message}")

    # In disaster copy, 殺害 changes causal agency. Allow it only when the same
    # story clearly contains a violence/attack context.
    if DISASTER_RE.search(blob) and "殺害" in blob:
        context_without_killing_word = blob.replace("殺害", "")
        if not VIOLENCE_RE.search(context_without_killing_word):
            issues.append(f"{name}:{aid}: disaster casualty translated as 殺害 instead of 死亡/犠牲")

    raw_furigana = json.dumps(item.get("furigana") or {}, ensure_ascii=False)
    for pattern, message in FORBIDDEN_RUBY:
        if pattern.search(raw_furigana):
            issues.append(f"{name}:{aid}: furigana: {message}")

    for pattern, message in NATURALNESS_WARNINGS:
        if pattern.search(blob):
            warnings.append(f"{name}:{aid}: {message}")


def check_source_semantics(name: str, target_item: dict, source_item: dict, issues: list[str]) -> None:
    aid = str(target_item.get("id") or "unknown")
    for field in PROSE_FIELDS:
        source = str(source_item.get(field) or "")
        target = str(target_item.get(field) or "")
        if not source or not target:
            continue

        if SOURCE_DEATH_RE.search(source) and not SOURCE_VIOLENCE_RE.search(source) and "殺害" in target:
            issues.append(f"{name}:{aid}:{field}: source reports death/casualty but Japanese introduces 殺害")

        # Direction reversals are P0 because they invert the news fact. Only fire
        # when source direction is unambiguous and target contains the opposite.
        source_up = bool(SOURCE_UP_RE.search(source))
        source_down = bool(SOURCE_DOWN_RE.search(source))
        if source_up and not source_down and TARGET_DOWN_RE.search(target) and not TARGET_UP_RE.search(target):
            issues.append(f"{name}:{aid}:{field}: source increase/growth appears reversed to decrease in Japanese")
        if source_down and not source_up and TARGET_UP_RE.search(target) and not TARGET_DOWN_RE.search(target):
            issues.append(f"{name}:{aid}:{field}: source decrease/fall appears reversed to increase in Japanese")


def check_section_states(data: dict, warnings: list[str]) -> None:
    counts = ((data.get("collectionAudit") or {}).get("deskLatestStoryCounts") or {})
    for section in data.get("sections", []) or []:
        slug = str(section.get("slug") or "")
        ids = section.get("articleIds") or []
        available = int(counts.get(slug, 0) or 0)
        if not ids and available > 0:
            warnings.append(
                f"latest.json:section:{slug}: 0 published articles despite {available} collected candidates; "
                "UI should distinguish editorial NO_QUALIFYING_STORY from pipeline failure"
            )


def check_audio_refs(name: str, item: dict, warnings: list[str]) -> None:
    aid = str(item.get("id") or "unknown")
    audio = str(item.get("audio") or "").strip()
    timing = str(item.get("timing") or "").strip()
    if audio and not (ROOT / audio).exists():
        warnings.append(f"{name}:{aid}: audio is pending/not present in repository: {audio}")
    if timing and not (ROOT / timing).exists():
        warnings.append(f"{name}:{aid}: timing is pending/not present in repository: {timing}")


def main() -> int:
    issues: list[str] = []
    warnings: list[str] = []

    for name in ("latest.json", "live.json"):
        path = DATA / name
        if not path.exists():
            issues.append(f"{name}: missing publication data")
            continue
        data = load(path)
        source_map = source_story_map(name)
        for item in story_list(name, data):
            check_local_story(name, item, issues, warnings)
            check_audio_refs(name, item, warnings)
            source_item = source_map.get(str(item.get("id")))
            if source_item:
                check_source_semantics(name, item, source_item, issues)
        if name == "latest.json":
            check_section_states(data, warnings)
        if name == "live.json" and issues and (data.get("coverage") or {}).get("publishingGateMet") is True:
            issues.append("live.json: publishingGateMet=true while independent editorial P0 issues exist")

    for warning in warnings[:100]:
        print("EDITORIAL_WARNING -", warning)
    if len(warnings) > 100:
        print(f"EDITORIAL_WARNING - ... and {len(warnings) - 100} more")

    if issues:
        print("EDITORIAL_QUALITY_FAIL")
        for issue in issues[:100]:
            print(" -", issue)
        if len(issues) > 100:
            print(f" - ... and {len(issues) - 100} more")
        return 1

    print(f"EDITORIAL_QUALITY_OK warnings={len(warnings)} independent_semantic_and_furigana_gate=pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
