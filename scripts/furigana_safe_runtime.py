#!/usr/bin/env python3
"""Safety wrapper for context-aware, lexical Japanese furigana.

Primary readings come from Sudachi's Japanese morphological dictionary so news
compounds are read as lexical units instead of isolated kanji. pykakasi remains
only as a fallback. The invariant is strict: removing ruby markup must reproduce
the source Japanese exactly; if any reading correction changes visible copy,
the field falls back rather than publishing mutated text.
"""
from __future__ import annotations

import html
import re

import sync_and_translate as base

try:
    from sudachipy import dictionary as sudachi_dictionary
    from sudachipy import tokenizer as sudachi_tokenizer
except Exception:
    sudachi_dictionary = None
    sudachi_tokenizer = None

_RT_RE = re.compile(r"<rt>.*?</rt>")
_PAST_AFTER_RE = re.compile(r"(?<=た)<ruby>後<rt>[^<]+</rt></ruby>")
_ONE_DAY_LESS_RE = re.compile(r"(?:1<ruby>日<rt>[^<]+</rt></ruby>|<ruby>1日<rt>[^<]+</rt></ruby>)(?=足らず)")
_ORIGINAL_RUBY_HTML = base.ruby_html

_SUDACHI = None
_SPLIT_MODE = None
if sudachi_dictionary is not None and sudachi_tokenizer is not None:
    try:
        _SUDACHI = sudachi_dictionary.Dictionary().create()
        _SPLIT_MODE = sudachi_tokenizer.Tokenizer.SplitMode.C
    except Exception as exc:
        print("FURIGANA_SUDACHI_INIT_WARNING", type(exc).__name__, exc)
        _SUDACHI = None
        _SPLIT_MODE = None

_PROTECTED_REPLACEMENTS = (
    # 麻しん / 麻疹 = ましん. Generic character reading often misreads 麻 as あさ.
    (re.compile(r"<ruby>麻<rt>[^<]+</rt></ruby>しん"), "<ruby>麻<rt>ま</rt></ruby>しん"),
    (re.compile(r"<ruby>麻疹<rt>[^<]+</rt></ruby>"), "<ruby>麻疹<rt>ましん</rt></ruby>"),
    # High-value lexical compounds that must never regress even in fallback mode.
    (re.compile(r"<ruby>氷河<rt>[^<]+</rt></ruby><ruby>湖<rt>[^<]+</rt></ruby>"), "<ruby>氷河湖<rt>ひょうがこ</rt></ruby>"),
    (re.compile(r"<ruby>氷河湖<rt>[^<]+</rt></ruby>"), "<ruby>氷河湖<rt>ひょうがこ</rt></ruby>"),
    (re.compile(r"<ruby>土砂崩<rt>[^<]+</rt></ruby>れ"), "<ruby>土砂崩れ<rt>どしゃくずれ</rt></ruby>"),
    (re.compile(r"<ruby>土砂崩れ<rt>[^<]+</rt></ruby>"), "<ruby>土砂崩れ<rt>どしゃくずれ</rt></ruby>"),
    (re.compile(r"<ruby>山火<rt>[^<]+</rt></ruby><ruby>事<rt>[^<]+</rt></ruby>"), "<ruby>山火事<rt>やまかじ</rt></ruby>"),
    (re.compile(r"<ruby>山<rt>[^<]+</rt></ruby><ruby>火事<rt>[^<]+</rt></ruby>"), "<ruby>山火事<rt>やまかじ</rt></ruby>"),
    (re.compile(r"<ruby>山火事<rt>[^<]+</rt></ruby>"), "<ruby>山火事<rt>やまかじ</rt></ruby>"),
)


def visible_text(value: str) -> str:
    text = _RT_RE.sub("", str(value or ""))
    text = text.replace("<ruby>", "").replace("</ruby>", "")
    return html.unescape(text)


def _kata_to_hira(value: str) -> str:
    out = []
    for ch in str(value or ""):
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            out.append(chr(code - 0x60))
        else:
            out.append(ch)
    return "".join(out)


def _pykakasi_ruby(value: str) -> str:
    return "".join(
        base.ruby_piece(token.get("orig", ""), token.get("hira", ""))
        for token in base.KKS.convert(value)
    )


def _sudachi_ruby(value: str) -> str:
    if _SUDACHI is None or _SPLIT_MODE is None:
        raise RuntimeError("Sudachi dictionary unavailable")
    rendered = []
    for morpheme in _SUDACHI.tokenize(value, _SPLIT_MODE):
        surface = morpheme.surface()
        reading = morpheme.reading_form()
        if not reading or reading == "*":
            rendered.append(html.escape(surface, quote=False))
            continue
        rendered.append(base.ruby_piece(surface, _kata_to_hira(reading)))
    return "".join(rendered)


def _fix_past_after(rendered: str) -> str:
    return _PAST_AFTER_RE.sub("<ruby>後<rt>あと</rt></ruby>", rendered)


def _fix_one_day_less(rendered: str) -> str:
    return _ONE_DAY_LESS_RE.sub("<ruby>1日<rt>いちにち</rt></ruby>", rendered)


def _fix_protected_readings(rendered: str) -> str:
    value = str(rendered or "")
    for pattern, replacement in _PROTECTED_REPLACEMENTS:
        value = pattern.sub(replacement, value)
    return value


def _editorial_fix(rendered: str) -> str:
    return _fix_protected_readings(_fix_one_day_less(_fix_past_after(rendered)))


def _contextualize(source: str, rendered: str) -> str:
    # Existing context rules still own dates, counters, 対/後/行方/米ドル, etc.
    value = base.furigana_context.apply_contextual_readings(source, rendered)
    return _editorial_fix(value)


def safe_ruby_html(text) -> str:
    value = str(text or "")
    if not value:
        return ""

    # Lexical dictionary first.
    try:
        lexical = _contextualize(value, _sudachi_ruby(value))
        if visible_text(lexical) == value:
            return lexical
        print("FURIGANA_SUDACHI_VISIBLE_TEXT_MISMATCH", value[:100])
    except Exception as exc:
        print("FURIGANA_SUDACHI_FALLBACK", type(exc).__name__, str(exc)[:120])

    # Keep the previous engine as a per-field fallback, then apply independent
    # protected corrections. This preserves availability during dictionary faults.
    try:
        legacy = _contextualize(value, _pykakasi_ruby(value))
    except Exception:
        legacy = _editorial_fix(_ORIGINAL_RUBY_HTML(value))
    if visible_text(legacy) == value:
        return legacy

    # Last-resort display safety: correct Japanese copy is more important than ruby.
    print("FURIGANA_VISIBLE_TEXT_ESCAPE", value[:100])
    return html.escape(value, quote=False)


def engine_name() -> str:
    return "sudachi-core-mode-c" if _SUDACHI is not None else "pykakasi-protected-fallback"


def install() -> None:
    if base.ruby_html is not safe_ruby_html:
        base.ruby_html = safe_ruby_html
    print(
        "FURIGANA_SAFE_RUNTIME_INSTALLED "
        f"engine={engine_name()} visible_text_must_equal_source=true lexical_compounds=true"
    )
