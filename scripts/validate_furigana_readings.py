#!/usr/bin/env python3
"""Validate context-sensitive furigana across the full published corpus."""
import html
import json
import re
import sys
from pathlib import Path

import sync_and_translate as base

ROOT=Path(__file__).resolve().parents[1]
SCHEMA=base.TRANSLATION_SCHEMA

CASES={
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
}


def visible_text(ruby_html):
    value=re.sub(r"<rt>.*?</rt>","",str(ruby_html or ""))
    value=value.replace("<ruby>","").replace("</ruby>","")
    return html.unescape(value)


def load(name):
    return json.loads((ROOT/"data"/name).read_text(encoding="utf-8"))


def check_unit_cases(issues):
    for text,expected in CASES.items():
        actual=base.ruby_html(text)
        if expected not in actual:
            issues.append(f"unit:{text}: expected {expected!r}, got {actual!r}")
    score=base.ruby_html("マンチェスター・ユナイテッドは0対2で敗れた")
    if "<ruby>対<rt>たい</rt></ruby>" not in score or "<rt>つい</rt>" in score:
        issues.append(f"unit:score 対 must be たい, got {score!r}")
    sanctions=base.ruby_html("対イラン制裁")
    if "<ruby>対<rt>たい</rt></ruby>イラン" not in sanctions:
        issues.append(f"unit:対イラン must use たい, got {sanctions!r}")
    after=base.ruby_html("発表した後の対応")
    if "た<ruby>後<rt>あと</rt></ruby>の" not in after:
        issues.append(f"unit:した後 must be あと, got {after!r}")
    sono_go=base.ruby_html("その後の対応")
    if "その<ruby>後<rt>ご</rt></ruby>の" not in sono_go:
        issues.append(f"unit:その後 must be ご, got {sono_go!r}")
    retirement=base.ruby_html("監督退任後の試合")
    if "<ruby>後<rt>ご</rt></ruby>" not in retirement and "<rt>たいにんご</rt>" not in retirement:
        issues.append(f"unit:退任後 must use ご, got {retirement!r}")
    yukue=base.ruby_html("22名の行方は不明だ")
    if "<ruby>行方<rt>ゆくえ</rt></ruby>" not in yukue:
        issues.append(f"unit:行方 must use ゆくえ in whereabouts context, got {yukue!r}")
    usd=base.ruby_html("102億米ドル")
    if "<ruby>米<rt>べい</rt></ruby>ドル" not in usd and "<rt>べいどる</rt>" not in usd:
        issues.append(f"unit:米ドル must use べい, got {usd!r}")


def check_item(name,item,issues):
    aid=str(item.get("id") or "unknown")
    f=item.get("furigana") or {}
    for field in base.RUBY_FIELDS:
        source=item.get(field)
        if not isinstance(source,str) or not source.strip():
            continue
        actual=f.get(field)
        expected=base.ruby_html(source)
        if actual != expected:
            issues.append(f"{name}:{aid}:{field}: stored furigana differs from current context engine")
        if visible_text(actual) != source:
            issues.append(f"{name}:{aid}:{field}: ruby base text differs from source Japanese")
    paras=base.body_paragraphs(item)
    actual_paras=f.get("bodyParagraphs") or []
    expected_paras=[base.ruby_html(p) for p in paras]
    if actual_paras != expected_paras:
        issues.append(f"{name}:{aid}:bodyParagraphs: stored furigana differs from current context engine")
    for i,(source,actual) in enumerate(zip(paras,actual_paras)):
        if visible_text(actual) != source:
            issues.append(f"{name}:{aid}:bodyParagraphs[{i}]: ruby base text differs from source Japanese")


def check_corpus(issues):
    for name,key in (("latest.json","articles"),("live.json","items")):
        data=load(name)
        if data.get("translationSchemaVersion") != SCHEMA:
            issues.append(f"{name}: stale furigana schema {data.get('translationSchemaVersion')!r}; expected {SCHEMA!r}")
        for item in data.get(key,[]):
            check_item(name,item,issues)
    archive=load("archive.json")
    if archive.get("translationSchemaVersion") != SCHEMA:
        issues.append(f"archive.json: stale furigana schema {archive.get('translationSchemaVersion')!r}; expected {SCHEMA!r}")
    for idx,edition in enumerate(archive.get("editions",[])):
        headline=str(edition.get("headline") or "")
        actual=str(edition.get("furiganaHeadline") or "")
        if headline and actual != base.ruby_html(headline):
            issues.append(f"archive.json:editions[{idx}]:headline furigana differs from context engine")
        if headline and visible_text(actual) != headline:
            issues.append(f"archive.json:editions[{idx}]:headline ruby base differs from source")
        topics=edition.get("topics") or []
        ruby_topics=edition.get("furiganaTopics") or []
        expected=[base.ruby_html(x) for x in topics]
        if ruby_topics != expected:
            issues.append(f"archive.json:editions[{idx}]:topic furigana differs from context engine")


def check_forbidden(issues):
    for name in ("latest.json","live.json","archive.json"):
        raw=(ROOT/"data"/name).read_text(encoding="utf-8")
        if re.search(r"\d<ruby>対<rt>つい</rt></ruby>\d",raw):
            issues.append(f"{name}: numeric score/ratio still contains 対=つい")
        if re.search(r"<ruby>対<rt>つい</rt></ruby>(?:[ァ-ヶーA-Za-z]|<ruby>)",raw):
            issues.append(f"{name}: 対-prefix still contains つい")
        if "た<ruby>後<rt>のち</rt></ruby>" in raw:
            issues.append(f"{name}: past-event 後 still contains のち instead of あと")
        if "その<ruby>後<rt>のち</rt></ruby>" in raw:
            issues.append(f"{name}: その後 still contains のち instead of ご")
        if re.search(r"\d{1,2}<ruby>月<rt>がつ</rt></ruby>\d{1,2}<ruby>日<rt>にち</rt></ruby>",raw):
            issues.append(f"{name}: uncorrected numeric calendar date ruby remains")
        if "<ruby>行方<rt>なめがた</rt></ruby>は" in raw:
            issues.append(f"{name}: whereabouts 行方 still uses なめがた")
        if "<ruby>米<rt>こめ</rt></ruby>ドル" in raw:
            issues.append(f"{name}: 米ドル still uses こめ")


def main():
    issues=[]
    check_unit_cases(issues)
    try:
        check_corpus(issues)
        check_forbidden(issues)
    except Exception as exc:
        issues.append(f"corpus validation failed: {exc}")
    if issues:
        print("FURIGANA_CONTEXT_FAIL")
        for issue in issues[:100]:
            print(" -",issue)
        if len(issues)>100:
            print(f" - ... and {len(issues)-100} more")
        return 1
    print("FURIGANA_CONTEXT_OK all published Japanese fields match context-aware reading rules")
    return 0

if __name__=="__main__":
    sys.exit(main())
