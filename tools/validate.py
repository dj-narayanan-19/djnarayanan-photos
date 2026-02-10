#!/usr/bin/env python3
"""
Validate the repo's gallery data integrity.

Checks:
- data/photos.json exists and parses
- each photo has unique id
- thumb/display files exist
- tags is list of strings
- reports orphaned assets (files not referenced)
- reports photos missing source.hash (warn)

Optional cleanup:
- --clean-orphans deletes orphan thumb/display files
- --dry-run prints what would be deleted without deleting (use with --clean-orphans)

Usage:
  python3 tools/validate.py --repo-root .
  python3 tools/validate.py --repo-root . --clean-orphans --dry-run
  python3 tools/validate.py --repo-root . --clean-orphans

Exit code:
  0 if OK (no errors)
  1 if errors found
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


DATA_PHOTOS = Path("data/photos.json")
ASSETS_THUMBS = Path("assets/thumbs")
ASSETS_DISPLAY = Path("assets/display")


def load_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))


def is_str_list(x) -> bool:
    return isinstance(x, list) and all(isinstance(t, str) for t in x)


def referenced_asset_paths(repo_root: Path, photos: List[Dict[str, Any]]) -> Tuple[Set[Path], Set[Path]]:
    referenced_thumbs: Set[Path] = set()
    referenced_display: Set[Path] = set()

    for ph in photos:
        paths = ph.get("paths", {}) or {}
        t = paths.get("thumb")
        d = paths.get("display")
        if isinstance(t, str) and t:
            referenced_thumbs.add((repo_root / t).resolve())
        if isinstance(d, str) and d:
            referenced_display.add((repo_root / d).resolve())

    return referenced_thumbs, referenced_display


def find_orphans(repo_root: Path, referenced_thumbs: Set[Path], referenced_display: Set[Path]) -> Tuple[List[Path], List[Path]]:
    orphan_thumbs: List[Path] = []
    orphan_display: List[Path] = []

    thumbs_dir = repo_root / ASSETS_THUMBS
    display_dir = repo_root / ASSETS_DISPLAY

    if thumbs_dir.exists():
        for f in thumbs_dir.glob("*.jpg"):
            if f.resolve() not in referenced_thumbs:
                orphan_thumbs.append(f)

    if display_dir.exists():
        for f in display_dir.glob("*.jpg"):
            if f.resolve() not in referenced_display:
                orphan_display.append(f)

    orphan_thumbs.sort()
    orphan_display.sort()
    return orphan_thumbs, orphan_display


def validate_repo(repo_root: Path) -> Tuple[Dict[str, Any], int]:
    errors: List[str] = []
    warnings: List[str] = []

    photos_path = repo_root / DATA_PHOTOS
    if not photos_path.exists():
        return {"errors": [f"Missing {DATA_PHOTOS}"], "warnings": []}, 1

    try:
        data = load_json(photos_path)
    except Exception as e:
        return {"errors": [f"Failed to parse {DATA_PHOTOS}: {e}"], "warnings": []}, 1

    photos = data.get("photos", [])
    if not isinstance(photos, list):
        return {"errors": [f"{DATA_PHOTOS} 'photos' is not a list"], "warnings": []}, 1

    # Unique IDs + per-photo checks
    seen_ids = set()
    for i, ph in enumerate(photos):
        pid = ph.get("id")
        if not pid or not isinstance(pid, str):
            errors.append(f"Photo at index {i} missing valid 'id'")
            continue
        if pid in seen_ids:
            errors.append(f"Duplicate id: {pid}")
        seen_ids.add(pid)

        paths = ph.get("paths", {}) or {}
        thumb = paths.get("thumb")
        display = paths.get("display")

        if not thumb or not isinstance(thumb, str):
            errors.append(f"{pid}: missing paths.thumb")
        else:
            if not (repo_root / thumb).exists():
                errors.append(f"{pid}: thumb missing on disk: {thumb}")

        if not display or not isinstance(display, str):
            errors.append(f"{pid}: missing paths.display")
        else:
            if not (repo_root / display).exists():
                errors.append(f"{pid}: display missing on disk: {display}")

        tags = ph.get("tags", [])
        if not is_str_list(tags):
            errors.append(f"{pid}: tags must be a list of strings")

        src = ph.get("source", {}) or {}
        if not isinstance(src, dict):
            warnings.append(f"{pid}: source is not an object")
        else:
            if not src.get("hash"):
                warnings.append(f"{pid}: source.hash missing (recommended for stable identity)")

    # Orphans
    ref_thumbs, ref_display = referenced_asset_paths(repo_root, photos)
    orphan_thumbs, orphan_display = find_orphans(repo_root, ref_thumbs, ref_display)

    for f in orphan_thumbs:
        warnings.append(f"Orphan thumb file not referenced: {f.relative_to(repo_root)}")
    for f in orphan_display:
        warnings.append(f"Orphan display file not referenced: {f.relative_to(repo_root)}")

    report = {
        "errors": errors,
        "warnings": warnings,
        "orphans": {
            "thumbs": [str(p.relative_to(repo_root)) for p in orphan_thumbs],
            "display": [str(p.relative_to(repo_root)) for p in orphan_display],
        },
        "photos_count": len(photos),
    }
    code = 1 if errors else 0
    return report, code


def clean_orphans(repo_root: Path, orphans: Dict[str, List[str]], dry_run: bool) -> Tuple[int, List[str]]:
    deleted = 0
    log: List[str] = []

    for rel in orphans.get("thumbs", []):
        p = repo_root / rel
        if p.exists():
            if dry_run:
                log.append(f"[dry-run] would delete {rel}")
            else:
                p.unlink()
                log.append(f"deleted {rel}")
                deleted += 1

    for rel in orphans.get("display", []):
        p = repo_root / rel
        if p.exists():
            if dry_run:
                log.append(f"[dry-run] would delete {rel}")
            else:
                p.unlink()
                log.append(f"deleted {rel}")
                deleted += 1

    return deleted, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".", help="Repo root (default: .)")
    ap.add_argument("--clean-orphans", action="store_true", help="Delete orphan thumb/display files")
    ap.add_argument("--dry-run", action="store_true", help="With --clean-orphans: print deletions without deleting")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    report, code = validate_repo(repo_root)

    print("\n=== VALIDATE REPORT ===")
    if report["errors"]:
        print(f"\nErrors ({len(report['errors'])}):")
        for e in report["errors"]:
            print(f"  - {e}")
    else:
        print("\nErrors (0): none ✅")

    if report["warnings"]:
        print(f"\nWarnings ({len(report['warnings'])}):")
        for w in report["warnings"]:
            print(f"  - {w}")
    else:
        print("\nWarnings (0): none ✅")

    if args.clean_orphans:
        orphans = report.get("orphans", {}) or {}
        total_orphans = len(orphans.get("thumbs", [])) + len(orphans.get("display", []))
        if total_orphans == 0:
            print("\n[clean] No orphan assets to delete.")
        else:
            print(f"\n[clean] Found {total_orphans} orphan asset(s).")
            deleted, log = clean_orphans(repo_root, orphans, args.dry_run)
            for line in log:
                print(f"  {line}")
            if args.dry_run:
                print("\n[clean] Dry-run only (no files deleted).")
            else:
                print(f"\n[clean] Deleted {deleted} file(s). Re-run validate to confirm.")

    sys.exit(code)


if __name__ == "__main__":
    main()