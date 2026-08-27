#!/usr/bin/env python3
"""Independent Editor-in-Chief review for automatic production maintenance.

This is deliberately downstream of translation. It judges already-generated
Japanese instead of asking the translator to validate itself. The review is
lightweight enough to run every maintenance cycle and can be scoped to core
Daily/Live or rolling/category layers so recovery remains precise.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

import newsroom_quality

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCE_DIR = (
    Path(os.environ.get("CANTONESE_SNAPSHOT_DIR", "")).resolve()
    if os.environ.get("CANTONESE_SNAPSHOT_DIR")
    else None
)
PROSE_FIELDS = ("title", "dek", "summary", "body", "context", "why", "watchNext")
EXPECTED_FURIGANA_ENGINE = "sudachi-core-mode-c+context"
MIN_NEWSROOM_QUALITY_VERSION = 1
VALID_SCOPES = {"core", "rolling", "all"}
TOPIC_RENDERER = ROOT / "assets/js/topic-ja-rolling.js"
TOPIC_FRESHNESS_GUARD_MARKERS = (
    "GEO_FOOTBALL_CROSSPLACEMENT_MAX_AGE_DAYS",
    "ROLLING_LAYER_MAX_AGE_DAYS",
    "STALE_GEO_FOOTBALL_CROSSPLACEMENT_SUPPRESSED",
    "STALE_ROLLING_LAYER_SUPPRESSED",
)

# Strong evidence of learner-harmful or newsroom-unacceptable Japanese already
# observed in production. Keep this list conservative: stylistic preferences
# belong in warnings, not hard publication failures.
HARD_TEXT_PATTERNS = (
    (re.compile(r"バプテスマを受けたコミュニティ"), "flooded/submerged community mistranslated as a baptised community"),
    (re.compile(r"洪水制御圧力"), "literal Chinese flood-control-pressure compound is not normal Japanese newsroom copy"),
    (re.compile(r"(?:洪水|豪雨)[^。\n]{0,70}(?:移動|シフト)を悪化"), "evacuation/relocation role is mistranslated as worsening movement"),
    (re.compile(r"(?:洪水|豪雨)[^。\n]{0,90}大規模なシフト"), "literal 大規模なシフト in disaster copy is semantically unsafe"),
    (re.compile(r"セカンドサークル"), "cup round mistranslated as セカンドサークル"),
    (re.compile(r"サブリング試合"), "cup-round fixture mistranslated as サブリング試合"),
    (re.compile(r"マルチライン戦闘"), "multi-competition schedule mistranslated as military-style マルチライン戦闘"),
    (re.compile(r"ポジティブな選択とフィジカルディストリビューション"), "squad selection/load-management phrase is machine translation"),
    (re.compile(r"フォローアップの試合や犠牲者"), "football follow-up/injuries mistranslated with casualty wording"),
    (re.compile(r"完全なラップ結果"), "round results mistranslated as 完全なラップ結果"),
)

# Learner-facing ruby defects that can survive otherwise valid HTML.
HARD_RUBY_PATTERNS = (
    (re.compile(r"<ruby>人以上<rt>ひといじょう</rt></ruby>"), "人以上 after a numeric counter must not read ひといじょう"),
    (re.compile(r"<ruby>崇<rt>すう</rt></ruby><ruby>左<rt>ひだり</rt></ruby>"), "崇左 is incorrectly decomposed into character readings"),
)

SOURCE_UKRAINE_WAR_RE = re.compile(r"烏克蘭戰爭")
SOURCE_UKRAINE_CIVIL_RE = re.compile(r"烏克蘭內戰|烏克蘭内戰")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def iter_story_dicts(value):
    if isinstance(value, dict):
        if value.get("id") and any(isinstance(value.get(k), str) and value.get(k).strip() for k in PROSE_FIELDS):
            yield value
        for child in value.values():
            yield from iter_story_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_story_dicts(child)


def source_map_for(name: str) -> dict[str, dict]:
    if SOURCE_DIR is None:
        return {}
    path = SOURCE_DIR / name
    if not path.is_file():
        return {}
    try:
        data = load_json(path)
    except Exception:
        return {}
    return {str(item.get("id")): item for item in iter_story_dicts(data) if item.get("id")}


def check_metadata(name: str, data: dict, issues: list[str]) -> None:
    if name not in {"latest.json", "live.json"}:
        return
    engine = str(data.get("furiganaEngineVersion") or "")
    if engine != EXPECTED_FURIGANA_ENGINE:
        issues.append(
            f"{name}: furiganaEngineVersion={engine!r}; expected {EXPECTED_FURIGANA_ENGINE!r}"
        )
    try:
        quality_version = int(data.get("newsroomQualityVersion") or 0)
    except Exception:
        quality_version = 0
    if quality_version < MIN_NEWSROOM_QUALITY_VERSION:
        issues.append(
            f"{name}: newsroomQualityVersion={quality_version}; expected >= {MIN_NEWSROOM_QUALITY_VERSION}"
        )


def check_story(
    name: str,
    story: dict,
    source_story: dict | None,
    issues: list[str],
    warnings: list[str],
) -> None:
    sid = str(story.get("id") or "unknown")
    source_story = source_story or {}

    for field in PROSE_FIELDS:
        target = str(story.get(field) or "")
        if not target:
            continue
        source = str(source_story.get(field) or "")

        reason = newsroom_quality.hard_reason(source, target, field)
        if reason:
            issues.append(f"{name}:{sid}:{field}: {reason}")

        for pattern, message in HARD_TEXT_PATTERNS:
            if pattern.search(target):
                issues.append(f"{name}:{sid}:{field}: {message}")

        if source and SOURCE_UKRAINE_WAR_RE.search(source) and not SOURCE_UKRAINE_CIVIL_RE.search(source):
            if "ウクライナ内戦" in target:
                issues.append(
                    f"{name}:{sid}:{field}: source says Ukraine war but Japanese changes it to ウクライナ内戦"
                )

        for warning in newsroom_quality.warning_reasons(target, field):
            warnings.append(f"{name}:{sid}:{field}: {warning}")

    raw_furigana = json.dumps(story.get("furigana") or {}, ensure_ascii=False)
    for pattern, message in HARD_RUBY_PATTERNS:
        if pattern.search(raw_furigana):
            issues.append(f"{name}:{sid}:furigana: {message}")


def check_sections(data: dict, warnings: list[str]) -> None:
    counts = ((data.get("collectionAudit") or {}).get("deskLatestStoryCounts") or {})
    for section in data.get("sections", []) or []:
        slug = str(section.get("slug") or "")
        available = int(counts.get(slug, 0) or 0)
        published = len(section.get("articleIds") or [])
        if available > 0 and published == 0:
            warnings.append(
                f"latest.json:section:{slug}: {available} collected candidates but zero published stories; "
                "Editor-in-Chief review required to distinguish editorial rejection from pipeline loss"
            )


def _parse_iso_day(value: str) -> date | None:
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except Exception:
        return None


def _story_day(story: dict, current: date | None) -> date | None:
    for key in ("updatedAt", "publishedAt", "generatedAt", "date"):
        parsed = _parse_iso_day(story.get(key))
        if parsed:
            return parsed
    matches = list(re.finditer(r"(20\d{2})(\d{2})(\d{2})", str(story.get("id") or "")))
    if matches:
        match = matches[-1]
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except Exception:
            pass
    if current:
        label = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", str(story.get("timeLabel") or ""))
        if label:
            try:
                return date(current.year, int(label.group(1)), int(label.group(2)))
            except Exception:
                pass
    return None


def check_topic_freshness_delivery(issues: list[str], warnings: list[str]) -> None:
    if not TOPIC_RENDERER.is_file():
        issues.append("topic renderer missing; Editor-in-Chief cannot guarantee geographic-page freshness")
        return
    renderer = TOPIC_RENDERER.read_text(encoding="utf-8")
    missing = [marker for marker in TOPIC_FRESHNESS_GUARD_MARKERS if marker not in renderer]
    if missing:
        issues.append(
            "topic renderer is missing Editor-in-Chief freshness guards: " + ", ".join(missing)
        )
        return

    latest_path = DATA / "latest.json"
    rolling_path = DATA / "desk-latest.json"
    if not latest_path.is_file() or not rolling_path.is_file():
        return
    try:
        current_payload = load_json(latest_path)
        rolling_payload = load_json(rolling_path)
    except Exception:
        return
    current = _parse_iso_day(current_payload.get("date"))
    rolling_day = _parse_iso_day(rolling_payload.get("date") or rolling_payload.get("generatedAt"))
    if current and rolling_day:
        age = (current - rolling_day).days
        if age > 1:
            warnings.append(
                f"desk-latest.json is {age} days behind Daily; topic renderer must suppress it rather than label it 最新"
            )

    stale_geo_football: list[str] = []
    for story in iter_story_dicts(rolling_payload):
        slugs = {str(x) for x in (story.get("deskSlugs") or [])}
        if "football" not in slugs or not slugs.intersection({"hong-kong", "japan"}):
            continue
        story_day = _story_day(story, current)
        if current and story_day and (current - story_day).days > 1:
            stale_geo_football.append(str(story.get("id") or "unknown"))
    if stale_geo_football:
        warnings.append(
            "stale football cross-placement present upstream but suppressed on Hong Kong/Japan pages: "
            + ", ".join(stale_geo_football[:12])
        )


def rolling_files() -> list[str]:
    names = ["desk-latest.json", "stocks-latest.json"]
    latest_path = DATA / "latest.json"
    if latest_path.is_file():
        try:
            date_value = str(load_json(latest_path).get("date") or "")
        except Exception:
            date_value = ""
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_value):
            names.append(f"topic-more/{date_value}.json")
    return names


def files_for_scope(scope: str) -> list[str]:
    if scope == "core":
        return ["latest.json", "live.json"]
    if scope == "rolling":
        return rolling_files()
    return ["latest.json", "live.json", *rolling_files()]


def _pull_request_advisory_mode() -> bool:
    """Report existing corpus defects on PRs without blocking the fixer PR itself."""
    return str(os.environ.get("GITHUB_EVENT_NAME") or "").strip().lower() == "pull_request"


def review(scope: str = "all") -> int:
    scope = str(scope or "all").strip().lower()
    if scope not in VALID_SCOPES:
        print(f"EDITOR_IN_CHIEF_REJECT invalid_scope={scope!r}")
        return 2

    issues: list[str] = []
    warnings: list[str] = []
    reviewed = 0

    if scope in {"rolling", "all"}:
        check_topic_freshness_delivery(issues, warnings)

    for name in files_for_scope(scope):
        path = DATA / name
        if not path.is_file():
            if name in {"latest.json", "live.json"}:
                issues.append(f"{name}: missing core publication file")
            continue
        try:
            data = load_json(path)
        except Exception as exc:
            issues.append(f"{name}: unreadable JSON: {type(exc).__name__}: {exc}")
            continue

        check_metadata(name, data, issues)
        source_map = source_map_for(name)
        for story in iter_story_dicts(data):
            reviewed += 1
            sid = str(story.get("id") or "")
            check_story(name, story, source_map.get(sid), issues, warnings)
        if name == "latest.json":
            check_sections(data, warnings)

    for warning in warnings[:100]:
        print("EDITOR_IN_CHIEF_WARNING -", warning)
    if len(warnings) > 100:
        print(f"EDITOR_IN_CHIEF_WARNING - ... and {len(warnings) - 100} more")

    if issues:
        label = "EDITOR_IN_CHIEF_ADVISORY_REJECT" if _pull_request_advisory_mode() else "EDITOR_IN_CHIEF_REJECT"
        print(
            label,
            f"scope={scope}",
            f"reviewed_stories={reviewed}",
            f"issues={len(issues)}",
            f"warnings={len(warnings)}",
        )
        for issue in issues[:100]:
            print(" -", issue)
        if len(issues) > 100:
            print(f" - ... and {len(issues) - 100} more")
        if _pull_request_advisory_mode():
            print("EDITOR_IN_CHIEF_PR_ADVISORY_ONLY production_enforcement=true")
            return 0
        return 1

    print(
        "EDITOR_IN_CHIEF_APPROVED",
        f"scope={scope}",
        f"reviewed_stories={reviewed}",
        f"warnings={len(warnings)}",
        "independent_downstream_review=true",
    )
    return 0


def main() -> int:
    return review(os.environ.get("EDITOR_IN_CHIEF_SCOPE", "all"))


if __name__ == "__main__":
    raise SystemExit(main())
