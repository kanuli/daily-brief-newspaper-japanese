#!/usr/bin/env python3
"""Safety wrapper for context-aware furigana.

The invariant is strict: furigana markup may change readings, but removing ruby
markup must reproduce the source Japanese byte-for-byte (after HTML unescape).
If a contextual correction ever changes the visible base text, fall back to the
generic pykakasi ruby for that field rather than publishing corrupted copy.

This module also owns a small protected newsroom lexicon. These corrections are
editorially specified and deliberately independent from pykakasi so common news
compounds cannot validate their own incorrect readings.
"""
from __future__ import annotations

import html
import re

import sync_and_translate as base

_RT_RE = re.compile(r"<rt>.*?</rt>")
_PAST_AFTER_RE = re.compile(r"(?<=た)<ruby>後<rt>[^<]+</rt></ruby>")
_ORIGINAL_RUBY_HTML = base.ruby_html

_PROTECTED_REPLACEMENTS = (
    # 麻しん / 麻疹 = ましん. Generic character reading often misreads 麻 as あさ.
    (re.compile(r"<ruby>麻<rt>[^<]+</rt></ruby>しん"), "<ruby>麻<rt>ま</rt></ruby>しん"),
    (re.compile(r"<ruby>麻疹<rt>[^<]+</rt></ruby>"), "<ruby>麻疹<rt>ましん</rt></ruby>"),
    # Compound readings must be validated as lexical units, not isolated nouns.
    (re.compile(r"<ruby>氷河<rt>[^<]+</rt></ruby><ruby>湖<rt>[^<]+</rt></ruby>"), "<ruby>氷河湖<rt>ひょうがこ</rt></ruby>"),
    (re.compile(r"<ruby>氷河湖<rt>[^<]+</rt></ruby>"), "<ruby>氷河湖<rt>ひょうがこ</rt></ruby>"),
    (re.compile(r"<ruby>土砂崩<rt>[^<]+</rt></ruby>れ"), "<ruby>土砂崩れ<rt>どしゃくずれ</rt></ruby>"),
    (re.compile(r"<ruby>土砂崩れ<rt>[^<]+</rt></ruby>"), "<ruby>土砂崩れ<rt>どしゃくずれ</rt></ruby>"),
)


def visible_text(value: str) -> str:
    text = _RT_RE.sub("", str(value or ""))
    text = text.replace("<ruby>", "").replace("</ruby>", "")
    return html.unescape(text)


def _generic_ruby(value: str) -> str:
    return "".join(
        base.ruby_piece(token.get("orig", ""), token.get("hira", ""))
        for token in base.KKS.convert(value)
    )


def _fix_past_after(rendered: str) -> str:
    # When 後 is a separate token immediately after a Vた form, the news reading
    # is あと. No look-ahead is needed; restricting the following particle caused
    # valid corpus cases such as ...た後も/...た後と... to remain のち.
    return _PAST_AFTER_RE.sub("<ruby>後<rt>あと</rt></ruby>", rendered)


def _fix_protected_readings(rendered: str) -> str:
    value = str(rendered or "")
    for pattern, replacement in _PROTECTED_REPLACEMENTS:
        value = pattern.sub(replacement, value)
    return value


def _editorial_fix(rendered: str) -> str:
    return _fix_protected_readings(_fix_past_after(rendered))


def safe_ruby_html(text) -> str:
    value = str(text or "")
    if not value:
        return ""

    contextual = _editorial_fix(_ORIGINAL_RUBY_HTML(value))
    if visible_text(contextual) == value:
        return contextual

    # Context substitutions must never be allowed to rewrite the visible copy.
    # Fall back only for this field; keep ruby rather than dropping furigana.
    try:
        generic = _editorial_fix(_generic_ruby(value))
    except Exception:
        generic = html.escape(value, quote=False)
    if visible_text(generic) == value:
        print("FURIGANA_VISIBLE_TEXT_FALLBACK", value[:100])
        return generic

    # Last-resort display safety: the source copy is more important than ruby.
    print("FURIGANA_VISIBLE_TEXT_ESCAPE", value[:100])
    return html.escape(value, quote=False)


def install() -> None:
    if base.ruby_html is not safe_ruby_html:
        base.ruby_html = safe_ruby_html
    print(
        "FURIGANA_SAFE_RUNTIME_INSTALLED "
        "visible_text_must_equal_source=true protected_newsroom_lexicon=true"
    )
