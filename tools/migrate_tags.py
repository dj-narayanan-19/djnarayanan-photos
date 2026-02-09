# tools/migrate_tags.py
#!/usr/bin/env python3
"""
Migrate photos.json from legacy tag schema to flat tags list:

Legacy:
  "tags": { "medium": [...], "color": [...], "event": [...], "camera": [...], "misc": [...] }

New:
  "tags": ["digital", "color", "prague-2024", "x100v", "street", "night"]

Also writes/updates data/tags.json (tag index with counts).

Usage:
  python3 tools/migrate_tags.py --repo-root .
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List


DATA_REL = Path("data/photos.json")
TAGS_REL = Path("data/tags.json")


def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s)
    return s.strip("-")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Dict[str, Any]) -> None:
    data["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def normalize_tag_list(tags: List[str]) -> List[str]:
    out: List[str] = []
    for t in tags:
        s = slugify(str(t))
        if s and s not in out:
            out.append(s)
    return out


def generate_tag_index(photos_json: Dict[str, Any]) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    for ph in photos_json.get("photos", []):
        tags = ph.get("tags", [])
        if isinstance(tags, list):
            for t in tags:
                if isinstance(t, str) and t.strip():
                    counts[t] = counts.get(t, 0) + 1
    tags_sorted = sorted(counts.keys())
    return {
        "schemaVersion": 1,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tags": [{"name": t, "count": counts[t]} for t in tags_sorted],
    }


def migrate_entry_tags(ph: Dict[str, Any]) -> bool:
    """
    Returns True if entry was modified.
    """
    tags = ph.get("tags")

    # Already new format
    if isinstance(tags, list):
        ph["tags"] = normalize_tag_list(tags)
        return False

    # Legacy format: dict of categories -> list of tags
    if isinstance(tags, dict):
        collected: List[str] = []
        for _, vals in tags.items():
            if isinstance(vals, list):
                collected.extend([str(v) for v in vals])
            elif isinstance(vals, str):
                collected.append(vals)

        ph["tags"] = normalize_tag_list(collected)
        return True

    # Missing/unknown
    ph["tags"] = []
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".", help="Repo root containing data/photos.json")
    args = ap.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    photos_path = repo_root / DATA_REL
    tags_path = repo_root / TAGS_REL

    photos_json = load_json(photos_path)

    changed = 0
    for ph in photos_json.get("photos", []):
        if migrate_entry_tags(ph):
            changed += 1

    save_json(photos_path, photos_json)

    tag_index = generate_tag_index(photos_json)
    save_json(tags_path, tag_index)

    print(f"Done. Migrated {changed} photo(s). Wrote {DATA_REL} and {TAGS_REL}.")


if __name__ == "__main__":
    main()