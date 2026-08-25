#!/usr/bin/env python3
"""Safety wrapper for context-aware furigana.

The invariant is strict: furigana markup may change readings, but removing ruby
markup must reproduce the source Japanese byte-for-byte (after HTML unescape).
If a contextual correction ever changes the visible base text, fall back to the
generic pykakasi ruby for that field rather than publishing corrupted copy.
"""
from __future__ import annotations

import html
import re

import sync_and_translate as base

_RT_RE = re.compile(r"<rt>.*?</rt>")
_PAST_AFTER_RE = re.compile(r"(?<=た)<ruby>後<rt>[^<]+</rt></ruby>")
_ORIGINAL_RUBY_HTML = base.ruby_html


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


def safe_ruby_html(text) -> str:
    value = str(text or "")
    if not value:
        return ""

    contextual = _fix_past_after(_ORIGINAL_RUBY_HTML(value))
    if visible_text(contextual) == value:
        return contextual

    # Context substitutions must never be allowed to rewrite the visible copy.
    # Fall back only for this field; keep ruby rather than dropping furigana.
    try:
        generic = _fix_past_after(_generic_ruby(value))
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
    print("FURIGANA_SAFE_RUNTIME_INSTALLED visible_text_must_equal_source=true")
