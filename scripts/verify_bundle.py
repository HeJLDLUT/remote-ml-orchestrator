#!/usr/bin/env python3
"""Create or verify a recursive SHA-256 manifest for transferred results."""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def files(root: Path) -> Iterable[Path]:
    return sorted((path for path in root.rglob("*") if path.is_file()),
                  key=lambda path: path.relative_to(root).as_posix())


def build(root: Path) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    for path in files(root):
        entries.append({
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256(path),
        })
    return {"schema_version": 1, "algorithm": "sha256", "files": entries}


def create(root: Path, manifest: Path) -> int:
    if not root.is_dir():
        raise ValueError("Result root is not a directory: %s" % root)
    payload = build(root)
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Recorded %d files in %s" % (len(payload["files"]), manifest))
    return 0


def verify(root: Path, manifest: Path, allow_extra: bool) -> int:
    expected_payload = json.loads(manifest.read_text(encoding="utf-8"))
    expected = {entry["path"]: entry for entry in expected_payload.get("files", [])}
    actual_payload = build(root)
    actual = {entry["path"]: entry for entry in actual_payload["files"]}
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    changed = sorted(path for path in set(expected) & set(actual)
                     if expected[path]["size"] != actual[path]["size"]
                     or expected[path]["sha256"] != actual[path]["sha256"])
    status = "PASS" if not missing and not changed and (allow_extra or not extra) else "FAIL"
    report = {"status": status, "missing": missing, "changed": changed, "extra": extra}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if status == "PASS" else 4


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    create_parser = sub.add_parser("create")
    create_parser.add_argument("--root", required=True, type=Path)
    create_parser.add_argument("--manifest", required=True, type=Path)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--root", required=True, type=Path)
    verify_parser.add_argument("--manifest", required=True, type=Path)
    verify_parser.add_argument("--allow-extra", action="store_true")
    args = parser.parse_args()
    if args.mode == "create":
        return create(args.root, args.manifest)
    return verify(args.root, args.manifest, args.allow_extra)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        sys.exit(2)
