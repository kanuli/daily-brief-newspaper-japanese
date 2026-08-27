#!/usr/bin/env python3
"""Editorial Japanese quality rules shared by translation and repair paths.

The rules here are intentionally conservative. They target phrases that are
not merely stylistic preferences but strong evidence of literal Chinese/English
machine translation, unit-role reversal, duplicated copy, or domain terminology
that would mislead a Japanese learner.
"""
from __future__ import annotations

import re

# Clear machine-translation failure signatures observed in published copy.
_HARD_TARGET_PATTERNS = (
    (re.compile(r"前期市場"), "pre-market mistranslated as 前期市場"),
    (re.compile(r"パフォーマンス検証AI"), "missing Japanese relation around AI investment-cycle wording"),
    (re.compile(r"縮小金利リスク"), "unnatural/reversed finance compound 縮小金利リスク"),
    (re.compile(r"営業時間外の業績"), "after-hours earnings mistranslated as 営業時間外の業績"),
    (re.compile(r"エディションは[^。]{0,100}保持されます"), "literal edition-hold wording is not newsroom Japanese"),
    (re.compile(r"高リスクの拡張フェーズ"), "literal expansion-phase wording is not newsroom Japanese"),
    (re.compile(r"コントロールレート"), "wildfire containment mistranslated as コントロールレート"),
    (re.compile(r"レッドフラッグの火災警告"), "Red Flag Warning mistranslated literally"),
    (re.compile(r"わずか\s*\d+(?:\.\d+)?\s*[％%]を(?:制御|コントロール)しました"), "containment percentage attached to object-control grammar"),
    (re.compile(r"少なくとも[^。\n]{0,70}少なくとも"), "duplicated 少なくとも in one sentence"),
    (re.compile(r"バプテスマを受けたコミュニティ"), "flooded/submerged community mistranslated as a baptised community"),
    (re.compile(r"洪水制御圧力"), "literal Chinese flood-control-pressure compound"),
    (re.compile(r"(?:洪水|豪雨)[^。\n]{0,70}(?:移動|シフト)を悪化"), "evacuation/relocation role mistranslated as worsening movement"),
    (re.compile(r"(?:洪水|豪雨)[^。\n]{0,90}大規模なシフト"), "literal 大規模なシフト in disaster copy"),
    (re.compile(r"セカンドサークル"), "cup round mistranslated as セカンドサークル"),
    (re.compile(r"サブリング試合"), "cup-round fixture mistranslated as サブリング試合"),
    (re.compile(r"マルチライン戦闘"), "multi-competition schedule mistranslated as military-style マルチライン戦闘"),
    (re.compile(r"ポジティブな選択とフィジカルディストリビューション"), "squad selection/load-management phrase is machine translation"),
    (re.compile(r"フォローアップの試合や犠牲者"), "football follow-up/injuries mistranslated with casualty wording"),
    (re.compile(r"完全なラップ結果"), "round results mistranslated as 完全なラップ結果"),
)

# Source unit anchors: only flag a reversal when the same number is explicitly
# attached to different human/household units in the same translated field.
_SOURCE_HOUSEHOLD_RE = re.compile(r"(\d[\d,]*)\s*(?:戶|住戶|家庭|戶家庭)")
_SOURCE_PERSON_RE = re.compile(r"(\d[\d,]*)\s*(?:人|名)")

_TITLE_POLITE_END_RE = re.compile(r"(?:です|ます|ました|でした|されています|となりました)[。．]?$" )


def source_unit_reason(source_text: str, target_text: str) -> str | None:
    source = str(source_text or "")
    target = str(target_text or "")
    for number in _SOURCE_HOUSEHOLD_RE.findall(source):
        compact = number.replace(",", "")
        variants = {number, compact, f"{int(compact):,}" if compact.isdigit() else number}
        if any(re.search(rf"{re.escape(v)}\s*(?:人|名)", target) for v in variants):
            return f"source household count {number} became a person count in Japanese"
    for number in _SOURCE_PERSON_RE.findall(source):
        compact = number.replace(",", "")
        variants = {number, compact, f"{int(compact):,}" if compact.isdigit() else number}
        if any(re.search(rf"{re.escape(v)}\s*(?:世帯|戸)", target) for v in variants):
            return f"source person count {number} became a household count in Japanese"
    return None


def hard_reason(source_text: str, target_text: str, field: str = "") -> str | None:
    target = str(target_text or "")
    unit_reason = source_unit_reason(source_text, target)
    if unit_reason:
        return unit_reason
    for pattern, message in _HARD_TARGET_PATTERNS:
        if pattern.search(target):
            return message
    return None


def warning_reasons(target_text: str, field: str = "") -> list[str]:
    text = str(target_text or "").strip()
    warnings: list[str] = []
    if field == "title" and _TITLE_POLITE_END_RE.search(text):
        warnings.append("headline ends in polite です/ます style rather than normal Japanese headline style")
    if field == "title" and len(text) > 90:
        warnings.append(f"headline is unusually long ({len(text)} chars)")
    if "大人数のグループ" in text:
        warnings.append("unnatural phrase 大人数のグループ")
    if "パンデミックの影響を悪化" in text:
        warnings.append("awkward causal phrase パンデミックの影響を悪化")
    return warnings


def deterministic_postedit(source_text: str, target_text: str, field: str = "") -> str:
    """Apply only meaning-preserving newsroom terminology normalizations."""
    source = str(source_text or "")
    value = str(target_text or "")

    replacements = (
        ("前期市場", "取引開始前"),
        ("営業時間外の業績", "時間外取引後に発表される決算"),
        ("3つの主要指数の初期の動き", "主要3指数の序盤の動き"),
        ("狭い綱引き", "方向感に乏しい値動き"),
        ("熱いインフレ", "高止まりするインフレ"),
        ("大規模なクラウドカスタマー", "大手クラウド企業"),
        ("一元的に見直しています", "重点的に見極めています"),
        ("高リスクの拡張フェーズ", "なお拡大する恐れが高い段階"),
        ("レッドフラッグの火災警告", "レッドフラッグ警報"),
    )
    for old, new in replacements:
        value = value.replace(old, new)

    fire_context = bool(re.search(r"(?:山火事|火災|焼失|避難|鎮火|消防)", value)) or bool(
        re.search(r"(?:山火|火災|大火|撤離|疏散)", source)
    )
    if fire_context:
        value = value.replace("コントロールレート", "鎮圧率")
        value = value.replace("コントロール率", "鎮圧率")
        value = value.replace("制御率", "鎮圧率")
        value = value.replace("火災エリア", "焼失面積")

    return value


def install(safe_module) -> None:
    """Extend safe_sync's existing quality reason without rewriting safe_sync."""
    if getattr(safe_module, "_newsroom_quality_installed", False):
        return
    original = safe_module.source_target_quality_reason

    def wrapped(source_text, value, strict=False):
        reason = original(source_text, value, strict=strict)
        if reason:
            return reason
        return hard_reason(source_text, value)

    safe_module.source_target_quality_reason = wrapped
    safe_module._newsroom_quality_installed = True
    print("NEWSROOM_QUALITY_INSTALLED semantic_units=true translationese_gate=true editor_in_chief_rules=true")
