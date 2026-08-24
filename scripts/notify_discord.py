#!/usr/bin/env python3
"""Send Japanese Daily/Live publication notifications to Discord.

Discord notifications deliberately link only to the Japanese newspaper website.
Original/source news URLs are never exposed in Discord.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import urllib.request

SITE = "https://kanuli.github.io/daily-brief-newspaper-japanese/"
LIVE_PAGE = f"{SITE}live.html"
BAD_MARKERS = (
    "Error 500 (Server Error)",
    "That’s an error",
    "That's an error",
    "Please try again later",
)


def load(path: str) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def previous_json(path: str) -> dict:
    try:
        raw = subprocess.check_output(["git", "show", f"HEAD^:{path}"], text=True)
        return json.loads(raw)
    except Exception:
        return {}


def corrupt(value: object) -> bool:
    text = str(value or "")
    return any(marker in text for marker in BAD_MARKERS)


def post(content: str) -> None:
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        raise RuntimeError("DISCORD_WEBHOOK_URL is not configured")

    content = content.strip()
    if len(content) > 1950:
        content = content[:1947] + "…"

    body = json.dumps(
        {"content": content, "allowed_mentions": {"parse": []}},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        webhook,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "JapaneseDailyBriefGitHubActions/2.1",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.status not in (200, 204):
            raise RuntimeError(f"Discord webhook returned HTTP {response.status}")
        print(f"Discord accepted notification: HTTP {response.status}")


def send_daily() -> None:
    data = load("data/latest.json")
    articles = {a.get("id"): a for a in data.get("articles", [])}
    top: list[str] = []

    for article_id in data.get("topFive", [])[:3]:
        article = articles.get(article_id)
        if not article:
            continue
        title = str(article.get("title") or "").strip()
        if title and not corrupt(title):
            top.append(title)

    if not top:
        print("No safe Daily headlines available; Discord Daily notification suppressed.")
        return

    lines = [
        f"🗞️ **日本語デイリーニュース｜{data.get('dateLabel') or data.get('date') or '本日'}**",
        "",
    ]
    for index, title in enumerate(top, 1):
        lines.append(f"{index}. **{title}**")
    lines += [
        "",
        f"📰 ニュースを読む：{SITE}",
        f"🔴 最新ニュース速報：{LIVE_PAGE}",
    ]
    post("\n".join(lines))
    print("Daily Japanese Discord notification sent with website-only links.")


def send_live() -> None:
    current = load("data/live.json")
    previous = previous_json("data/live.json")

    def fingerprint(item: dict) -> tuple:
        return (
            item.get("id"),
            item.get("status"),
            item.get("section"),
            item.get("title"),
            item.get("summary"),
            item.get("sourceUrl"),
        )

    old = {item.get("id"): fingerprint(item) for item in previous.get("items", [])}
    material: list[dict] = []
    blocked = 0

    for item in current.get("items", []):
        item_id = item.get("id")
        changed_item = not item_id or old.get(item_id) != fingerprint(item)
        if not changed_item:
            continue
        if corrupt(item.get("title")) or corrupt(item.get("summary")):
            blocked += 1
            continue
        material.append(item)

    update_label = current.get("lastUpdatedLabel") or current.get("lastUpdated") or "最新更新"
    if corrupt(update_label):
        update_label = current.get("lastUpdated") or "最新更新"

    if not material:
        if blocked:
            post(
                "⚠️ **日本語ニュース配信ガード**\n\n"
                f"破損したニュース項目を {blocked} 件検出したため、記事配信を停止しました。\n"
                "Error 500 等の内容は配信していません。\n\n"
                f"🔗 最新ニュース速報：{LIVE_PAGE}"
            )
            print(f"Blocked {blocked} corrupted Live item(s).")
        else:
            print("No material Live update; Discord Live notification suppressed.")
        return

    lines = [f"🔴 **最新ニュース速報｜{update_label}**", ""]
    for item in material[:4]:
        status = item.get("status", "UPDATED")
        title = item.get("title", "更新")
        lines.append(f"**{status}** · **{title}**")
    if len(material) > 4:
        lines.append(f"＋ほか {len(material) - 4} 件の更新")
    if blocked:
        lines += ["", f"⚠️ 破損項目 {blocked} 件は配信から除外しました。"]
    lines += ["", f"🔴 続きを読む：{LIVE_PAGE}"]
    post("\n".join(lines))
    print("Live Japanese Discord notification sent with website-only links.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    if not args.daily and not args.live:
        raise SystemExit("Specify --daily and/or --live")
    if args.daily:
        send_daily()
    if args.live:
        send_live()


if __name__ == "__main__":
    main()
