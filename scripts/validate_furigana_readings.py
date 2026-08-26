#!/usr/bin/env python3
"""Validate context-sensitive furigana without allowing visible-copy mutation."""
import json
import re
import sys
from pathlib import Path

import furigana_safe_runtime as safety
import sync_and_translate as base

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = base.TRANSLATION_SCHEMA
safety.install()

CASES = {
    "9月8日":"<ruby>9月<rt>くがつ</rt></ruby><ruby>8日<rt>ようか</rt></ruby>",
    "4月1日":"<ruby>4月<rt>しがつ</rt></ruby><ruby>1日<rt>ついたち</rt></ruby>",
    "7月14日":"<ruby>7月<rt>しちがつ</rt></ruby><ruby>14日<rt>じゅうよっか</rt></ruby>",
    "9月20日":"<ruby>9月<rt>くがつ</rt></ruby><ruby>20日<rt>はつか</rt></ruby>",
    "8日間":"<ruby>8日間<rt>ようかかん</rt></ruby>",
    "1日間":"<ruby>1日間<rt>いちにちかん</rt></ruby>",
    "4時":"<ruby>4時<rt>よじ</rt></ruby>",
    "7時":"<ruby>7時<rt>しちじ</rt></ruby>",
    "9時":"<ruby>9時<rt>くじ</rt></ruby>",
    "1分":"<ruby>1分<rt>いっぷん</rt></ruby>",
    "8分":"<ruby>8分<rt>はっぷん</rt></ruby>",
    "1人":"<ruby>1人<rt>ひとり</rt></ruby>",
    "2人":"<ruby>2人<rt>ふたり</rt></ruby>",
    "4人":"<ruby>4人<rt>よにん</rt></ruby>",
    "22人":"<ruby>22人<rt>にじゅうににん</rt></ruby>",
    "3本":"<ruby>3本<rt>さんぼん</rt></ruby>",
    "6匹":"<ruby>6匹<rt>ろっぴき</rt></ruby>",
    "3杯":"<ruby>3杯<rt>さんばい</rt></ruby>",
    "3階":"<ruby>3階<rt>さんがい</rt></ruby>",
    "6回":"<ruby>6回<rt>ろっかい</rt></ruby>",
    "8冊":"<ruby>8冊<rt>はっさつ</rt></ruby>",
    "3軒":"<ruby>3軒<rt>さんげん</rt></ruby>",
    "1件":"<ruby>1件<rt>いっけん</rt></ruby>",
    "8個":"<ruby>8個<rt>はっこ</rt></ruby>",
    "1社":"<ruby>1社<rt>いっしゃ</rt></ruby>",
    "1発":"<ruby>1発<rt>いっぱつ</rt></ruby>",
    "20歳":"<ruby>20歳<rt>はたち</rt></ruby>",
    "75歳":"<ruby>75歳<rt>ななじゅうごさい</rt></ruby>",
    "1節":"<ruby>1節<rt>いっせつ</rt></ruby>",
    "13話":"<ruby>13話<rt>じゅうさんわ</rt></ruby>",
    "日本":"<ruby>日本<rt>にほん</rt></ruby>",
    # Editorially protected newsroom vocabulary. These cases are explicit golden
    # readings, not expectations generated from pykakasi itself.
    "麻しん":"<ruby>麻<rt>ま</rt></ruby>しん",
    "麻疹":"<ruby>麻疹<rt>ましん</rt></ruby>",
    "氷河湖":"<ruby>氷河湖<rt>ひょうがこ</rt></ruby>",
    "土砂崩れ":"<ruby>土砂崩れ<rt>どしゃくずれ</rt></ruby>",
}


def load(name):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def check_unit_cases(issues):
    for text, expected in CASES.items():
        actual = base.ruby_html(text)
        if expected not in actual:
            issues.append(f"unit:{text}: expected {expected!r}, got {actual!r}")
        if safety.visible_text(actual) != text:
            issues.append(f"unit:{text}: ruby changed visible Japanese")

    cases = {
        "マンチェスター・ユナイテッドは0対2で敗れた":"<ruby>対<rt>たい</rt></ruby>",
        "対イラン制裁":"<ruby>対<rt>たい</rt></ruby>イラン",
        "発表した後の対応":"た<ruby>後<rt>あと</rt></ruby>の",
        "発表した後も対応":"た<ruby>後<rt>あと</rt></ruby>も",
        "その後の対応":"その<ruby>後<rt>ご</rt></ruby>の",
        "22名の行方は不明だ":"<ruby>行方<rt>ゆくえ</rt></ruby>",
        "102億米ドル":"<ruby>米<rt>べい</rt></ruby>ドル",
    }
    for text, expected in cases.items():
        actual = base.ruby_html(text)
        if expected not in actual:
            issues.append(f"unit:{text}: missing contextual reading {expected!r}; got {actual!r}")
        if safety.visible_text(actual) != text:
            issues.append(f"unit:{text}: contextual ruby changed visible Japanese")


def check_item(name, item, issues):
    aid = str(item.get("id") or "unknown")
    furigana = item.get("furigana") or {}
    for field in base.RUBY_FIELDS:
        source = item.get(field)
        if not isinstance(source, str) or not source.strip():
            continue
        actual = furigana.get(field)
        expected = base.ruby_html(source)
        if actual != expected:
            issues.append(f"{name}:{aid}:{field}: stored furigana differs from safe context engine")
        if safety.visible_text(actual) != source:
            issues.append(f"{name}:{aid}:{field}: ruby base text differs from source Japanese")

    paragraphs = base.body_paragraphs(item)
    actual_paragraphs = furigana.get("bodyParagraphs") or []
    expected_paragraphs = [base.ruby_html(p) for p in paragraphs]
    if actual_paragraphs != expected_paragraphs:
        issues.append(f"{name}:{aid}:bodyParagraphs: stored furigana differs from safe context engine")
    if len(actual_paragraphs) != len(paragraphs):
        issues.append(f"{name}:{aid}:bodyParagraphs: paragraph count differs")
    for index, source in enumerate(paragraphs):
        actual = actual_paragraphs[index] if index < len(actual_paragraphs) else ""
        if safety.visible_text(actual) != source:
            issues.append(f"{name}:{aid}:bodyParagraphs[{index}]: ruby base text differs from source Japanese")


def check_corpus(issues):
    for name, key in (("latest.json", "articles"), ("live.json", "items")):
        data = load(name)
        if data.get("translationSchemaVersion") != SCHEMA:
            issues.append(f"{name}: stale furigana schema {data.get('translationSchemaVersion')!r}; expected {SCHEMA!r}")
        for item in data.get(key, []):
            check_item(name, item, issues)

    archive = load("archive.json")
    if archive.get("translationSchemaVersion") != SCHEMA:
        issues.append(f"archive.json: stale furigana schema {archive.get('translationSchemaVersion')!r}; expected {SCHEMA!r}")
    for index, edition in enumerate(archive.get("editions", [])):
        headline = str(edition.get("headline") or "")
        actual = str(edition.get("furiganaHeadline") or "")
        if headline and actual != base.ruby_html(headline):
            issues.append(f"archive.json:editions[{index}]:headline furigana differs from safe engine")
        if headline and safety.visible_text(actual) != headline:
            issues.append(f"archive.json:editions[{index}]:headline ruby base differs from source")
        topics = edition.get("topics") or []
        ruby_topics = edition.get("furiganaTopics") or []
        if ruby_topics != [base.ruby_html(x) for x in topics]:
            issues.append(f"archive.json:editions[{index}]:topic furigana differs from safe engine")
        for topic_index, topic in enumerate(topics):
            actual_topic = ruby_topics[topic_index] if topic_index < len(ruby_topics) else ""
            if safety.visible_text(actual_topic) != topic:
                issues.append(f"archive.json:editions[{index}]:topics[{topic_index}]: ruby base differs")


def check_forbidden(issues):
    for name in ("latest.json", "live.json", "archive.json"):
        raw = (ROOT / "data" / name).read_text(encoding="utf-8")
        forbidden = (
            (r"\d<ruby>対<rt>つい</rt></ruby>\d", "numeric score/ratio still contains 対=つい"),
            (r"<ruby>対<rt>つい</rt></ruby>(?:[ァ-ヶーA-Za-z]|<ruby>)", "対-prefix still contains つい"),
            (r"た<ruby>後<rt>のち</rt></ruby>", "past-event 後 still contains のち instead of あと"),
            (r"その<ruby>後<rt>のち</rt></ruby>", "その後 still contains のち instead of ご"),
            (r"\d{1,2}<ruby>月<rt>がつ</rt></ruby>\d{1,2}<ruby>日<rt>にち</rt></ruby>", "uncorrected numeric calendar date ruby remains"),
            (r"<ruby>行方<rt>なめがた</rt></ruby>は", "whereabouts 行方 still uses なめがた"),
            (r"<ruby>米<rt>こめ</rt></ruby>ドル", "米ドル still uses こめ"),
            (r"<ruby>麻<rt>あさ</rt></ruby>しん", "麻しん still uses あさ instead of ましん"),
            (r"<ruby>氷河<rt>ひょうが</rt></ruby><ruby>湖<rt>みずうみ</rt></ruby>", "氷河湖 still uses 湖=みずうみ instead of lexical ひょうがこ"),
            (r"<ruby>土砂崩<rt>どしゃくづ</rt></ruby>れ", "土砂崩れ still uses どしゃくづれ instead of どしゃくずれ"),
        )
        for pattern, message in forbidden:
            if re.search(pattern, raw):
                issues.append(f"{name}: {message}")


def main():
    issues = []
    check_unit_cases(issues)
    try:
        check_corpus(issues)
        check_forbidden(issues)
    except Exception as exc:
        issues.append(f"corpus validation failed: {exc}")
    if issues:
        print("FURIGANA_CONTEXT_FAIL")
        for issue in issues[:100]:
            print(" -", issue)
        if len(issues) > 100:
            print(f" - ... and {len(issues)-100} more")
        return 1
    print("FURIGANA_CONTEXT_OK all published Japanese fields preserve source text and match safe context readings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
