#!/usr/bin/env python3
"""Reject poisoned or partially untranslated Japanese publication data."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_FILES = ("latest.json", "live.json", "archive.json")
ERROR_RE = re.compile(
    r"(?:error\s*(?:4\d\d|5\d\d)|server error|that[’']s an error|please try again later|"
    r"bad gateway|service unavailable|too many requests|internal server error|<!doctype|<html)",
    re.I,
)
HIRA_RE = re.compile(r"[\u3040-\u309f]")
HAN_RE = re.compile(r"[\u3400-\u9fff]")
CHINESE_PROSE_RE = re.compile(
    r"(?:，|；|分鐘|小時|仍然|目前|進一步|將於|已經|對於|相關消息|賽事|球隊|球員|當局|"
    r"白禮頓|阿士東|維拉)"
)
PROSE_FIELDS = ("dek", "summary", "body", "context", "why", "watchNext")
NEXT_RE = re.compile(r"^次回発行予定 (?:[01]\d|2[0-4]):[0-5]\d HKT$")
LAST_RE = re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日 (?:[01]\d|2[0-3]):[0-5]\d HKT$")
WINDOW_RE = re.compile(r"^(?:[01]\d|2[0-4]):[0-5]\d HKT 速報版$")


def iter_strings(value, path="$"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from iter_strings(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_strings(child, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def prose_is_mixed(value):
    text = str(value or "").strip()
    if not text:
        return False
    if CHINESE_PROSE_RE.search(text):
        return True
    if len(text) >= 28:
        han = len(HAN_RE.findall(text))
        hira = len(HIRA_RE.findall(text))
        if han >= 8 and hira < max(2, int(han * 0.06)):
            return True
    return False


def collect_issues(name, data):
    issues = []
    if not isinstance(data, dict):
        return [f"{name}: root is not an object"]
    if data.get("language") != "ja":
        issues.append(f"{name}: language != ja")

    for path, value in iter_strings(data):
        if ERROR_RE.search(value):
            issues.append(f"{name}:{path}: translator/server error payload detected")

    if name == "live.json":
        next_label = str(data.get("nextUpdateLabel") or "")
        last_label = str(data.get("lastUpdatedLabel") or "")
        window_label = str(data.get("windowLabel") or "")
        if not NEXT_RE.fullmatch(next_label):
            issues.append(f"live.json: invalid deterministic nextUpdateLabel: {next_label!r}")
        if not LAST_RE.fullmatch(last_label):
            issues.append(f"live.json: invalid deterministic lastUpdatedLabel: {last_label!r}")
        if not WINDOW_RE.fullmatch(window_label):
            issues.append(f"live.json: invalid deterministic windowLabel: {window_label!r}")

    groups = []
    if name == "latest.json":
        groups = data.get("articles") or []
    elif name == "live.json":
        groups = data.get("items") or []

    for item in groups:
        aid = str(item.get("id") or "unknown")
        for field in PROSE_FIELDS:
            value = item.get(field)
            if isinstance(value, str) and value.strip() and prose_is_mixed(value):
                issues.append(f"{name}:{aid}:{field}: partially untranslated Traditional Chinese detected")

    return issues


def load(name):
    path = ROOT / "data" / name
    if not path.is_file():
        raise RuntimeError(f"missing data/{name}")
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    issues = []
    for name in DATA_FILES:
        try:
            data = load(name)
        except Exception as exc:
            issues.append(f"{name}: {exc}")
            continue
        issues.extend(collect_issues(name, data))

    if issues:
        print("CONTENT_INTEGRITY_FAIL")
        for issue in issues[:80]:
            print(" -", issue)
        if len(issues) > 80:
            print(f" - ... and {len(issues) - 80} more")
        return 1

    print("CONTENT_INTEGRITY_OK latest/live/archive contain no error-page poison or mixed Traditional Chinese prose")
    return 0


if __name__ == "__main__":
    sys.exit(main())
