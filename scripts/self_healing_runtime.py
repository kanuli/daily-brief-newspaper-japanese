#!/usr/bin/env python3
"""Self-healing publication layer for Japanese Daily/Live/Archive sync.

A translation failure is quarantined at its owning story/edition instead of
aborting the whole newspaper. Clean items continue to publish against the
current frozen Cantonese source. Degraded files are never accepted by the
fingerprint fast-path, so later sync/maintenance cycles automatically retry the
quarantined owners until they translate successfully.
"""
from __future__ import annotations

import json
from collections import defaultdict

import fast_safe_sync as fast
import sync_and_translate as base

_DEFERRED = defaultdict(set)
_ORIGINAL_PREWARM = None


def _owner_id(name, item, index):
    if isinstance(item, dict):
        if item.get("id"):
            return str(item["id"])
        if item.get("date"):
            return f"date:{item['date']}"
        if item.get("editionNumber"):
            return f"edition:{item['editionNumber']}"
    return f"index:{index}"


def _remember_deferred(name, owner, exc):
    _DEFERRED[name].add(str(owner))
    print(
        "SELF_HEAL_TRANSLATION_QUARANTINED",
        f"file={name}",
        f"owner={owner}",
        f"error={type(exc).__name__}:{str(exc)[:220]}",
    )


def resilient_prewarm(source, label):
    """Prewarm each owner independently so one bad story cannot stop the batch."""
    _DEFERRED[label].clear()
    if not isinstance(source, dict):
        try:
            return _ORIGINAL_PREWARM(source, label)
        except Exception as exc:
            _remember_deferred(label, "root", exc)
            return

    list_key = None
    if label == "latest.json" and isinstance(source.get("articles"), list):
        list_key = "articles"
    elif label == "live.json" and isinstance(source.get("items"), list):
        list_key = "items"
    elif label == "archive.json" and isinstance(source.get("editions"), list):
        list_key = "editions"

    if not list_key:
        try:
            return _ORIGINAL_PREWARM(source, label)
        except Exception as exc:
            _remember_deferred(label, "root", exc)
            return

    shell = dict(source)
    owners = shell.pop(list_key)
    try:
        _ORIGINAL_PREWARM(shell, f"{label}:shell")
    except Exception as exc:
        print(
            "SELF_HEAL_SHELL_PREWARM_FAILED",
            f"file={label}",
            f"error={type(exc).__name__}:{str(exc)[:220]}",
        )

    for index, owner in enumerate(owners):
        owner_name = _owner_id(label, owner, index)
        try:
            _ORIGINAL_PREWARM({list_key: [owner]}, f"{label}:{owner_name}")
        except Exception as exc:
            _remember_deferred(label, owner_name, exc)

    print(
        "SELF_HEAL_PREWARM_COMPLETE",
        f"file={label}",
        f"owners={len(owners)}",
        f"deferred={len(_DEFERRED[label])}",
    )


def _mark_degraded(translated, name, deferred):
    if not isinstance(translated, dict):
        return translated
    ids = sorted(str(x) for x in deferred)
    translated["translationDegraded"] = bool(ids)
    translated["translationDeferredCount"] = len(ids)
    translated["translationDeferredIds"] = ids
    translated["translationRecoveryMode"] = "owner-quarantine-v1"
    if ids:
        print(
            "SELF_HEAL_DEGRADED_PUBLICATION",
            f"file={name}",
            f"deferred={len(ids)}",
            f"owners={','.join(ids[:12])}",
        )
    else:
        print("SELF_HEAL_FULL_PUBLICATION", f"file={name}")
    return translated


def _normalize_daily_references(translated, output):
    """Remove every reference to an owner that was quarantined from this edition."""
    if not isinstance(translated, dict):
        return
    valid_ids = [str(item.get("id")) for item in output if isinstance(item, dict) and item.get("id")]
    valid_set = set(valid_ids)

    top = [str(x) for x in (translated.get("topFive") or []) if str(x) in valid_set]
    for item_id in valid_ids:
        if item_id not in top:
            top.append(item_id)
        if len(top) >= 5:
            break
    translated["topFive"] = top[:5]
    if str(translated.get("leadId") or "") not in valid_set:
        translated["leadId"] = top[0] if top else (valid_ids[0] if valid_ids else None)

    # Sections are navigation/index metadata. Leaving a quarantined article ID
    # here creates a broken card/link even though the bad story itself is safely
    # withheld, so all section references must be pruned in the same transaction.
    for section in translated.get("sections") or []:
        if not isinstance(section, dict) or not isinstance(section.get("articleIds"), list):
            continue
        before = [str(x) for x in section.get("articleIds") or []]
        after = [item_id for item_id in before if item_id in valid_set]
        section["articleIds"] = after
        if before != after:
            print(
                "SELF_HEAL_SECTION_REFERENCES_PRUNED",
                f"slug={section.get('slug') or 'unknown'}",
                f"removed={len(before) - len(after)}",
            )


def _convert_story_list(name, source, existing, list_key):
    shell = dict(source)
    source_items = shell.pop(list_key)
    translated = base.convert(shell)
    old_items = {
        item.get("id"): item
        for item in (existing or {}).get(list_key, [])
        if isinstance(item, dict) and item.get("id")
    }

    output = []
    reused = 0
    changed = 0
    deferred = set(_DEFERRED.get(name, set()))

    for index, source_item in enumerate(source_items):
        owner = _owner_id(name, source_item, index)
        if not isinstance(source_item, dict):
            if owner in deferred:
                continue
            try:
                output.append(base.convert(source_item))
                changed += 1
            except Exception as exc:
                deferred.add(owner)
                _remember_deferred(name, owner, exc)
            continue

        item_id = source_item.get("id")
        item_fingerprint = base.source_fingerprint(source_item)
        old = old_items.get(item_id)
        fingerprint_matches = bool(
            old
            and (
                old.get("sourceItemFingerprint") == item_fingerprint
                or (not old.get("sourceItemFingerprint") and fast.legacy_item_reusable(source_item, old))
            )
        )
        quality_ok = bool(
            fingerprint_matches and fast.reused_translation_quality_ok(source_item, old)
        )
        if fingerprint_matches and not quality_ok:
            print(f"REUSE_REJECTED_LANGUAGE_QUALITY {name}:{item_id}")

        if fingerprint_matches and quality_ok:
            item = dict(old)
            reused += 1
        elif owner in deferred:
            continue
        else:
            try:
                item = base.convert(source_item)
                changed += 1
            except Exception as exc:
                deferred.add(owner)
                _remember_deferred(name, owner, exc)
                continue

        if isinstance(item, dict):
            item["sourceItemFingerprint"] = item_fingerprint
        output.append(item)

    if source_items and not output:
        raise RuntimeError(f"Self-healing guard refused empty {name} publication")

    translated[list_key] = output
    if name == "latest.json":
        _normalize_daily_references(translated, output)
    _mark_degraded(translated, name, deferred)
    print(
        f"SELF_HEAL_INCREMENTAL {name}: reused={reused} changed={changed} "
        f"deferred={len(deferred)} total={len(output)}/{len(source_items)}"
    )
    return translated


def _edition_key(edition, index):
    if isinstance(edition, dict):
        return str(edition.get("date") or edition.get("editionNumber") or f"index:{index}")
    return f"index:{index}"


def _convert_archive(source, existing):
    editions = source.get("editions") if isinstance(source, dict) else None
    if not isinstance(editions, list):
        return base.convert(source)

    shell = dict(source)
    shell.pop("editions", None)
    translated = base.convert(shell)
    old_editions = {}
    for index, edition in enumerate((existing or {}).get("editions", [])):
        if isinstance(edition, dict):
            old_editions[_edition_key(edition, index)] = edition

    output = []
    deferred = set(_DEFERRED.get("archive.json", set()))
    reused = 0
    changed = 0
    for index, source_edition in enumerate(editions):
        owner = _edition_key(source_edition, index)
        fingerprint = base.source_fingerprint(source_edition)
        old = old_editions.get(owner)
        can_reuse = bool(
            old
            and old.get("sourceEditionFingerprint") == fingerprint
            and fast.reused_translation_quality_ok(source_edition, old)
        )
        if can_reuse:
            edition = dict(old)
            reused += 1
        elif owner in deferred:
            continue
        else:
            try:
                edition = base.convert(source_edition)
                changed += 1
            except Exception as exc:
                deferred.add(owner)
                _remember_deferred("archive.json", owner, exc)
                continue
        if isinstance(edition, dict):
            edition["sourceEditionFingerprint"] = fingerprint
        output.append(edition)

    if editions and not output:
        raise RuntimeError("Self-healing guard refused empty archive publication")
    translated["editions"] = output
    _mark_degraded(translated, "archive.json", deferred)
    print(
        f"SELF_HEAL_INCREMENTAL archive.json: reused={reused} changed={changed} "
        f"deferred={len(deferred)} total={len(output)}/{len(editions)}"
    )
    return translated


def resilient_incremental_convert(name, source, existing):
    if name == "latest.json" and isinstance(source, dict) and isinstance(source.get("articles"), list):
        return _convert_story_list(name, source, existing, "articles")
    if name == "live.json" and isinstance(source, dict) and isinstance(source.get("items"), list):
        return _convert_story_list(name, source, existing, "items")
    if name == "archive.json":
        return _convert_archive(source, existing)
    return base.convert(source)


def resilient_incremental_main():
    """Retry degraded files forever; fast-path only fully translated publication."""
    base.OUT.mkdir(exist_ok=True)
    done = []
    skipped = []
    for name in base.FILES:
        src = base.fetch(name)
        if src is None:
            continue
        fingerprint = base.source_fingerprint(src)
        existing = base.load_existing(name)
        if (
            existing
            and not existing.get("translationDegraded")
            and int(existing.get("translationDeferredCount") or 0) == 0
            and existing.get("sourceFingerprint") == fingerprint
            and existing.get("translationSchemaVersion") == base.TRANSLATION_SCHEMA
            and base.existing_features_ok(name, existing)
        ):
            (base.OUT / name).write_text(
                json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            skipped.append(name)
            continue

        resilient_prewarm(src, name)
        translated = resilient_incremental_convert(name, src, existing)
        if name == "latest.json":
            translated = base.add_furigana(base.attach_daily_audio(translated), "articles")
        if name == "live.json":
            translated = base.add_furigana(base.attach_live_audio(translated), "items")
        if name == "archive.json":
            translated = base.add_archive_furigana(translated)
        if isinstance(translated, dict):
            translated["language"] = "ja"
            translated["translationSource"] = "kanuli/daily-brief-newspaper"
            translated["sourceFile"] = name
            translated["sourceFingerprint"] = fingerprint
            translated["translationSchemaVersion"] = base.TRANSLATION_SCHEMA
        (base.OUT / name).write_text(
            json.dumps(translated, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        done.append(name)

    base.CACHE_PATH.write_text(
        json.dumps(base.CACHE, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("Japanese data updated:", ", ".join(done) if done else "none")
    print("Fingerprint fast-path:", ", ".join(skipped) if skipped else "none")


def install():
    global _ORIGINAL_PREWARM
    _ORIGINAL_PREWARM = fast.prewarm_translations
    fast.prewarm_translations = resilient_prewarm
    fast.incremental_convert = resilient_incremental_convert
    fast.incremental_main = resilient_incremental_main
    print(
        "SELF_HEAL_RUNTIME_INSTALLED owner_quarantine=true "
        "degraded_fast_path=false retry_on_every_cycle=true"
    )
