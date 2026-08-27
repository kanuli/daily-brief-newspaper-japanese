#!/usr/bin/env python3
"""Sync the upstream teacher-audited daily vocabulary into the Japanese edition."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests
from deep_translator import GoogleTranslator

SOURCE = "https://raw.githubusercontent.com/kanuli/daily-brief-newspaper/main/data/vocab/latest.json"
OUT = Path("data/vocab/latest.json")
LEVELS = ("N1", "N2", "N3", "N4", "N5")
HAN = re.compile(r"[\u3400-\u9fff]")
KANA = re.compile(r"[\u3040-\u30ff]")
DATE_RE = re.compile(r"^20\d\d-\d\d-\d\d$")

POS = {
    "noun": "名詞", "n": "名詞", "verb": "動詞", "v": "動詞",
    "adj": "形容詞", "adjective": "形容詞", "adv": "副詞", "adverb": "副詞",
    "particle": "助詞", "conjunction": "接続詞", "conj": "接続詞",
    "pronoun": "代名詞", "pron": "代名詞", "interjection": "感動詞", "int": "感動詞",
    "auxiliary": "助動詞", "aux": "助動詞", "determiner": "連体詞",
    "prefix": "接頭語", "suffix": "接尾語", "counter": "助数詞", "numeral": "数詞",
    "expression": "表現", "phrase": "慣用表現", "unclassified": "未分類",
}


def looks_chinese(text):
    text = str(text or "")
    return bool(HAN.search(text)) and not bool(KANA.search(text))


def gtx(text):
    r = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": "zh-TW" if looks_chinese(text) else "auto", "tl": "ja", "dt": "t", "q": text},
        headers={"User-Agent": "daily-brief-newspaper-japanese"}, timeout=25,
    )
    r.raise_for_status()
    payload = r.json()
    segments = payload[0] if isinstance(payload, list) and payload else []
    value = "".join(str(x[0]) for x in segments if isinstance(x, list) and x and x[0])
    if not value.strip():
        raise RuntimeError("empty GTX translation")
    return value


def translate(text):
    text = str(text or "").strip()
    if not text or not looks_chinese(text):
        return text
    try:
        return gtx(text)
    except Exception:
        for source in ("zh-TW", "auto", "zh-CN"):
            try:
                value = GoogleTranslator(source=source, target="ja").translate(text)
                if value:
                    return value
            except Exception:
                time.sleep(0.5)
    raise RuntimeError(f"vocab translation failed: {text!r}")


def validate_source(src):
    date = str(src.get("date") or "").strip()
    if not DATE_RE.fullmatch(date):
        raise RuntimeError(f"upstream vocab has invalid date: {date!r}")
    policy = str(src.get("selectionPolicy") or "")
    if "teacher-core" not in policy:
        raise RuntimeError(f"upstream vocab is not teacher-core gated: {policy!r}")
    words = src.get("words") or []
    if len(words) != 10:
        raise RuntimeError(f"upstream vocab expected 10 words, got {len(words)}")
    seen = set()
    for word in words:
        reading = str(word.get("reading") or "").strip()
        kanji = str(word.get("kanji") or "").strip()
        key = (reading, kanji)
        if not reading or key in seen:
            raise RuntimeError(f"upstream vocab invalid/duplicate exact key: {key}")
        seen.add(key)
        if word.get("teacherGrade") not in {"A", "B"}:
            raise RuntimeError(f"upstream vocab non A/B teacher grade: {key}")
        if word.get("teacherStatus") != "direct":
            raise RuntimeError(f"upstream vocab non-direct teacher status: {key}")
        if word.get("teacherCommon") is not True:
            raise RuntimeError(f"upstream vocab non-common teaching word: {key}")
        if word.get("selectionClass") != "teacher-core-common-direct":
            raise RuntimeError(f"upstream vocab wrong selection class: {key}")
    for level in LEVELS:
        count = sum(1 for word in words if word.get("level") == level)
        if count != 2:
            raise RuntimeError(f"upstream vocab {level}: expected 2, got {count}")
    return date, words


def normalize_word(word):
    reading = str(word.get("reading") or "").strip()
    kanji = str(word.get("kanji") or "").strip()
    pos_raw = str(word.get("partOfSpeech") or "").strip()
    return {
        "level": str(word.get("level") or "").strip(),
        "reading": reading,
        "kanji": kanji,
        "meaning": translate(word.get("meaning", "")),
        "partOfSpeech": POS.get(pos_raw.lower(), pos_raw or "未分類"),
        "teacherGrade": word.get("teacherGrade"),
        "teacherStatus": word.get("teacherStatus"),
        "teacherBasis": word.get("teacherBasis"),
        "teacherCommon": word.get("teacherCommon"),
        "selectionClass": word.get("selectionClass"),
    }


def main():
    r = requests.get(SOURCE, timeout=30, headers={"User-Agent": "daily-brief-newspaper-japanese"})
    r.raise_for_status()
    src = r.json()
    date, source_words = validate_source(src)
    words = [normalize_word(word) for word in source_words]
    out = {
        "date": date,
        "sourceRepo": "kanuli/daily-brief-newspaper",
        "sourceFile": "data/vocab/latest.json",
        "sourceUrl": src.get("sourceUrl") or "https://github.com/kanuli/japanese-vocab-game",
        "sourceSelectionPolicy": src.get("selectionPolicy"),
        "language": "ja",
        "levelNote": "JLPTレベルは教師監査済みの学習用分類です。現行JLPTには公式の網羅的な語彙表はありません。",
        "levelMethod": "upstream-teacher-core-exact-audit-common-direct-grade-A-B",
        "words": words,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(out, ensure_ascii=False, indent=2) + "\n"
    OUT.write_text(body, encoding="utf-8")
    archive = OUT.parent / f"{date}.json"
    archive.write_text(body, encoding="utf-8")
    print(f"JAPANESE_VOCAB_SYNC_OK {len(words)} words date={date} archive={archive}")


if __name__ == "__main__":
    main()
