"""Verify translated editions against the original immutable Cantonese snapshot."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import cantonese_snapshot as source

CORE = {"live.json": "items", "latest.json": "articles"}
HKT = timezone(timedelta(hours=8))
PRESERVED = ("id", "sourceUrl", "url", "publishedAt", "verifiedAt", "desk", "deskSlugs", "category", "sourceAggregation")
TEXT = ("title","headline","dek","summary","body","context","why","watchNext")
MANIFEST = "data/cantonese-lineage"
SCHEMA = "CANTONESE_TO_JAPANESE_LINEAGE_V1"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",",":"), allow_nan=False).encode()


def article_sets(doc, name):
    if name in CORE:
        return {CORE[name]:doc[CORE[name]]}
    if name=="desk-latest.json":
        return doc["desks"]
    if name.startswith("topic-more/"):
        key = "articles" if "articles" in doc else "items"
        return {key:doc[key]}
    if name=="stocks-latest.json":
        return {ticker:value["stories"] for ticker,value in doc["tickers"].items()}
    return {}


def by_id(rows, name):
    result={}
    for row in rows:
        key=row.get("id")
        if not isinstance(key,str) or not key or key in result:
            raise ValueError(f"Invalid or duplicate article identifier in {name}")
        result[key]=row
    return result


def lineage(name, original, translated, *, quality, strict_core=True):
    upstream=json.loads(original)
    output=json.loads(translated)
    if output.get("translationSource")!=source.REPO or output.get("sourceFingerprint")!=source.sha(canonical(upstream)):
        raise ValueError(f"Wrong or stale Cantonese source binding in {name}")
    upstream_groups=article_sets(upstream,name)
    translated_groups=article_sets(output,name)
    if set(translated_groups)-set(upstream_groups) or (name in CORE and set(translated_groups)!=set(upstream_groups)):
        raise ValueError(f"Unknown article group in {name}")
    witnesses=[]
    for group in sorted(translated_groups):
        old=by_id(upstream_groups[group],name)
        new=by_id(translated_groups[group],name)
        if set(new)-set(old) or (name in CORE and strict_core and set(new)!=set(old)):
            raise ValueError(f"Missing or independent upstream article in {name}/{group}")
        for key, item in new.items():
            original_item=old[key]
            if any(item.get(field)!=original_item.get(field) for field in PRESERVED):
                raise ValueError(f"Article source or category changed in {name}/{key}")
            original_hash=source.sha(canonical(original_item))
            recorded_input = item.get("sourceItemFingerprint")
            if not isinstance(recorded_input,str) or recorded_input != original_hash:
                raise ValueError(f"Missing or outdated translation input proof in {name}/{key}")
            for field in TEXT:
                text=original_item.get(field)
                if isinstance(text,str) and text.strip() and not quality(text,item.get(field),field):
                    raise ValueError(f"Translation quality rejection in {name}/{key}/{field}")
            witnesses.append({"group":group,"id":key,
                              **{field:original_item[field] for field in PRESERVED if field in original_item},
                              "cantoneseArticleSha256":original_hash,
                              "translationInputSha256":source.sha(canonical({k:original_item[k] for k in TEXT if k in original_item})),
                              "japaneseArticleSha256":source.sha(canonical(item))})
    return witnesses


def read_manifest(name):
    path=Path(MANIFEST)/name
    return json.loads(path.read_bytes()) if path.exists() else None


def seal(name, *, quality, require_today, clock):
    snapshot=source.metadata()
    original=source.load_bytes(name,manifest=snapshot)
    translated=(Path("data")/name).read_bytes()
    if name=="live.json" and require_today and json.loads(original).get("date")!=clock().astimezone(HKT).date().isoformat():
        raise ValueError("Cantonese Live is from another HKT date")
    articles=lineage(name,original,translated,quality=quality)
    proof={"schema":SCHEMA,"upstreamRepository":source.REPO,"sourceFile":name,
           "cantoneseSha256":source.sha(original),"japaneseSha256":source.sha(translated),"articles":articles}
    old=read_manifest(name)
    if old is not None and {k:v for k,v in old.items() if k!="cantoneseRevision"}==proof:
        # Identical published input and output do not make a new revision
        # when Cantonese main moves for an unrelated file.
        return
    source.write_atomic(Path(MANIFEST)/name,canonical({**proof,"cantoneseRevision":snapshot["commit"]})+b"\n")


def prepush(names):
    head=source.resolve_commit()
    for name in names:
        proof=read_manifest(name)
        if (not proof or proof.get("schema")!=SCHEMA or proof.get("sourceFile")!=name
                or proof.get("upstreamRepository")!=source.REPO
                or proof["cantoneseSha256"]!=source.sha(source.read_remote(head,name))
                or proof["japaneseSha256"]!=source.sha((Path("data")/name).read_bytes())
                or proof["cantoneseRevision"]!=head and proof["cantoneseSha256"]!=source.sha(
                    source.read_remote(proof["cantoneseRevision"],name))):
            raise ValueError(f"Source or translation changed before push: {name}")
        if name=="live.json" and json.loads((Path("data")/name).read_bytes()).get("date")!=datetime.now(HKT).date().isoformat():
            raise ValueError("Japanese Live is from another HKT date")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("command",choices=("seal","prepush"))
    p.add_argument("paths",nargs="+")
    a=p.parse_args()
    names=[]
    for value in a.paths:
        path=Path(value)
        if not value.startswith("data/") or not (value[5:] in source.BASE_FILES or
                len(path.parts)==3 and path.parts[1]=="topic-more" and ".." not in path.parts):
            raise ValueError("Invalid Japanese publication path")
        names.append(value[5:])
    if a.command=="prepush":
        prepush(names)
    else:
        from safe_sync import target_quality_ok, STRICT_PROSE_KEYS

        def quality(src,target,field):
            return isinstance(target,str) and target_quality_ok(src,target,strict=field in STRICT_PROSE_KEYS)
        for name in names:
            seal(name,quality=quality,require_today=True,clock=lambda:datetime.now(HKT))
    print("CANTONESE_LINEAGE_VERIFIED",a.command,",".join(names))


if __name__=="__main__":
    main()
