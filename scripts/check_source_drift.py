#!/usr/bin/env python3
import hashlib,json,os,sys,urllib.request
from pathlib import Path
import validate_content_integrity as integrity

ROOT=Path(__file__).resolve().parents[1]
SOURCE_BASE="https://raw.githubusercontent.com/kanuli/daily-brief-newspaper/main/data"
FILES=("latest.json","live.json","archive.json")

def fingerprint(obj):
    raw=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def remote_json(name):
    req=urllib.request.Request(f"{SOURCE_BASE}/{name}",headers={"User-Agent":"daily-brief-newspaper-japanese-maintenance"})
    with urllib.request.urlopen(req,timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))

def local_json(name):
    p=ROOT/"data"/name
    if not p.is_file():return None
    try:return json.loads(p.read_text(encoding="utf-8"))
    except Exception:return None

def emit(key,value):
    path=os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path,"a",encoding="utf-8") as f:f.write(f"{key}={value}\n")

def main():
    drift=[];errors=[];integrity_bad=[]
    for name in FILES:
        try:src=remote_json(name)
        except Exception as exc:
            errors.append(f"{name}:{type(exc).__name__}");continue
        local=local_json(name)
        expected=fingerprint(src)
        actual=str((local or {}).get("sourceFingerprint") or "")
        if expected!=actual:drift.append(name)
        if local is None:
            integrity_bad.append(name)
        else:
            issues=integrity.collect_issues(name,local)
            if issues:integrity_bad.append(name)
    dirty=sorted(set(drift)|set(integrity_bad))
    available=not errors
    emit("available",str(available).lower())
    emit("drift",str(bool(dirty)).lower())
    emit("files",",".join(dirty))
    emit("integrity",",".join(sorted(set(integrity_bad))))
    emit("errors",",".join(errors))
    if errors:
        print("SOURCE_DRIFT_CHECK_DEGRADED",",".join(errors))
    if integrity_bad:
        print("LOCAL_CONTENT_INTEGRITY_FAIL",",".join(sorted(set(integrity_bad))))
    if dirty:
        print("SOURCE_DRIFT_DETECTED",",".join(dirty));return 10
    print("SOURCE_DRIFT_OK" if available else "SOURCE_DRIFT_UNKNOWN")
    return 0

if __name__=="__main__":sys.exit(main())
