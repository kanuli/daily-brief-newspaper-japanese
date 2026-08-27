#!/usr/bin/env python3
"""Reject poisoned, partially untranslated, garbled, or editorially unsafe Japanese publication data."""
import json
import re
import sys
from pathlib import Path

import editor_in_chief_review as editor_in_chief

ROOT = Path(__file__).resolve().parents[1]
DATA_FILES = ("latest.json", "live.json", "archive.json")
ERROR_RE = re.compile(
    r"(?:error\s*(?:4\d\d|5\d\d)|server error|that[’']s an error|please try again later|"
    r"bad gateway|service unavailable|too many requests|internal server error|<!doctype|<html)",
    re.I,
)
HIRA_RE = re.compile(r"[\u3040-\u309f]")
KATA_RE = re.compile(r"[\u30a0-\u30ff]")
HAN_RE = re.compile(r"[\u3400-\u9fff]")
CHINESE_PROSE_RE = re.compile(
    r"(?:，|；|分鐘|小時|仍然|目前|進一步|將於|已經|對於|相關消息|賽事|球隊|球員|當局|"
    r"兒童|服務|加強|預防|預約|檢查|發現|將會|這些|白禮頓|阿士東|維拉)"
)
PROSE_FIELDS = ("dek", "summary", "body", "context", "why", "watchNext")
STORY_TEXT_FIELDS = ("title",) + PROSE_FIELDS + ("timeLabel", "description", "note", "impactLabel")
NEXT_RE = re.compile(r"^次回発行予定 (?:[01]\d|2[0-4]):[0-5]\d HKT$")
LAST_RE = re.compile(r"^\d{4}年\d{1,2}月\d{1,2}日 (?:[01]\d|2[0-3]):[0-5]\d HKT$")
WINDOW_RE = re.compile(r"^(?:[01]\d|2[0-4]):[0-5]\d HKT 速報版$")

# Translation-corruption signatures. These focus on patterns that valid
# Japanese news copy should not contain; they do not try to score writing style.
CONTROL_RE = re.compile(r"[\uFFFD\u0000-\u0008\u000B\u000C\u000E-\u001F]")
BATCH_MARKER_RE = re.compile(r"<<<\s*DBJ\d{5}\s*>>>", re.I)
LONG_SPACE_RE = re.compile(r"[ \t]{6,}")
BAD_SCRIPT_JOIN_RE = re.compile(r"(?:[\u3400-\u9fff][a-z]{2,}\b|\b[a-z]{2,}[\u3400-\u9fff])")
SPACED_CJK_RE = re.compile(r"(?:[\u3400-\u9fff]\s+){2,}[\u3400-\u9fff]")
REPEATED_OPEN_CLOSE_RE = re.compile(r"(?:「{2,}|『{2,}|（{2,}|\({2,}|」{2,}|』{2,}|）{2,}|\){2,})")
REPEATED_EMPTY_PARENS_RE = re.compile(r"(?:(?:\(\s*\))|(?:（\s*）)){3,}")
PLACEHOLDER_RUN_RE = re.compile(r"[◯○〇●◎□■△▲▽▼◇◆☆★]{6,}")
DECORATIVE_LINE_RE = re.compile(r"[━─═┅┄┈┉＿_~〜]{4,}")
COMBINING_MARK_RUN_RE = re.compile(r"[\u0300-\u036f]{3,}")
EXCESS_PUNCT_RE = re.compile(r"(?:!{4,}|！{4,}|\?{4,}|？{4,})")
KAOMOJI_RE = re.compile(r"(?:[\\/@]\s*[（(]|[（(][^\n]{0,16}[ﾟ゚∀ωДд顔][^\n]{0,16}[）)])")
REPEATED_PARTICLE_RE = re.compile(r"の{5,}")
REPEATED_TOKEN_RE = re.compile(r"(.{2,8})(?:\s+\1){2,}")
CYRILLIC_RE = re.compile(r"[\u0400-\u04ff]")
LOWER_ENGLISH_FUNCTION_RE = re.compile(
    r"\b(?:is|are|was|were|the|and|or|of|to|for|from|with|this|that|ill)\b",
    re.I,
)
LOWER_ASCII_WORD_RE = re.compile(r"(?<![A-Za-z])[a-z]{2,}(?![A-Za-z])")
LOWER_ASCII_ALLOWLIST = {
    "km", "kg", "cm", "mm", "ms", "gb", "tb", "mb", "kb",
    "fps", "bps", "kbps", "mbps", "gbps", "am", "pm", "vs",
    "web", "app", "apps", "email", "live", "online", "alpha", "beta",
    "http", "https", "www", "com", "org", "net",
}


def iter_strings(value, path="$"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from iter_strings(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_strings(child, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def suspicious_lower_ascii_word(text):
    for match in LOWER_ASCII_WORD_RE.finditer(text):
        word = match.group(0)
        if word not in LOWER_ASCII_ALLOWLIST:
            return word
    return None


def symbol_heavy(text):
    """Catch ASCII-art/kaomoji-like payloads without rejecting normal news punctuation."""
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 12:
        return False
    letters = len(HIRA_RE.findall(compact)) + len(KATA_RE.findall(compact)) + len(HAN_RE.findall(compact))
    symbols = sum(1 for ch in compact if not ch.isalnum() and not HIRA_RE.match(ch) and not KATA_RE.match(ch) and not HAN_RE.match(ch))
    return symbols >= 8 and symbols > max(letters, int(len(compact) * 0.34))


def garbled_japanese_reason(value, strict=False):
    """Return a stable reason when text is structurally impossible/unsafe Japanese."""
    text = str(value or "")
    if not text.strip():
        return None
    if CONTROL_RE.search(text):
        return "replacement/control character detected"
    if BATCH_MARKER_RE.search(text):
        return "internal translation batch marker leaked"
    if LONG_SPACE_RE.search(text):
        return "abnormal long whitespace run detected"
    if CYRILLIC_RE.search(text):
        return "unexpected Cyrillic script detected in Japanese copy"
    if REPEATED_PARTICLE_RE.search(text):
        return "impossible repeated Japanese particle run detected"
    if REPEATED_TOKEN_RE.search(text):
        return "repeated placeholder-like phrase detected"
    if BAD_SCRIPT_JOIN_RE.search(text):
        return "impossible Han/lowercase-ASCII token join detected"
    if SPACED_CJK_RE.search(text):
        return "multiple isolated CJK tokens separated by spaces"
    if REPEATED_OPEN_CLOSE_RE.search(text):
        return "repeated unmatched punctuation detected"
    if REPEATED_EMPTY_PARENS_RE.search(text):
        return "repeated empty-parenthesis placeholder detected"
    if PLACEHOLDER_RUN_RE.search(text):
        return "long placeholder-symbol run detected"
    if DECORATIVE_LINE_RE.search(text):
        return "decorative line/ASCII-art run detected"
    if COMBINING_MARK_RUN_RE.search(text):
        return "combining-mark corruption run detected"
    if EXCESS_PUNCT_RE.search(text):
        return "excessive repeated punctuation detected"
    if strict and KAOMOJI_RE.search(text):
        return "kaomoji/ASCII-art payload detected in news prose"
    if strict and symbol_heavy(text):
        return "symbol-heavy non-news payload detected"
    for opening, closing in (("「", "」"), ("『", "』"), ("（", "）"), ("(", ")")):
        imbalance = abs(text.count(opening) - text.count(closing))
        if strict and imbalance >= 1:
            return f"punctuation imbalance {opening}{closing}"
        if imbalance >= 2:
            return f"strong punctuation imbalance {opening}{closing}"
    if LOWER_ENGLISH_FUNCTION_RE.search(text):
        return "unexpected standalone English function word in Japanese copy"
    if strict:
        bad_word = suspicious_lower_ascii_word(text)
        if bad_word:
            return f"unexpected lowercase ASCII fragment {bad_word!r} in Japanese prose"
    if strict and len(text) >= 28:
        han = len(HAN_RE.findall(text))
        kana = len(HIRA_RE.findall(text)) + len(KATA_RE.findall(text))
        if han >= 8 and kana < max(3, int(han * 0.10)):
            return "long prose has implausibly little Japanese kana"
    return None


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


def collect_story_issues(name, item):
    issues = []
    aid = str(item.get("id") or "unknown")
    for field in STORY_TEXT_FIELDS:
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        if field in PROSE_FIELDS and prose_is_mixed(value):
            issues.append(
                f"{name}:{aid}:{field}: partially untranslated Traditional Chinese detected"
            )
        reason = garbled_japanese_reason(value, strict=field in PROSE_FIELDS)
        if reason:
            issues.append(f"{name}:{aid}:{field}: garbled Japanese: {reason}")
    return issues


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
        if isinstance(item, dict):
            issues.extend(collect_story_issues(name, item))

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
        for issue in issues[:120]:
            print(" -", issue)
        if len(issues) > 120:
            print(f" - ... and {len(issues) - 120} more")
        return 1

    # Auto-maintenance already treats this validator as the core publication
    # health authority. Keep the Editor-in-Chief inside the same decision so a
    # newsroom rejection activates the existing core recovery machinery.
    editor_code = editor_in_chief.review("core")
    if editor_code != 0:
        print("CONTENT_INTEGRITY_FAIL - Editor-in-Chief rejected core publication")
        return 1

    print(
        "CONTENT_INTEGRITY_OK latest/live/archive contain no error-page poison, "
        "mixed Traditional Chinese prose, structural translation corruption, or Editor-in-Chief rejection"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
