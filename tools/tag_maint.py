#!/usr/bin/env python3
"""
Local Tag Maintenance UI for photo-site.

Features:
- Rename tag
- Merge tags into target
- Delete tag
- Tag usage table
- Top co-occurring tag pairs
- "Related tags" view for a selected tag
- Backup before every write
- Writes data/tags.json after changes

Usage:
  source .venv/bin/activate
  python3 tools/tag_maint.py --repo-root . --host 127.0.0.1 --port 5051
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple
from collections import Counter, defaultdict

from flask import Flask, jsonify, redirect, render_template_string, request, url_for

DATA_REL = Path("data/photos.json")
TAGS_REL = Path("data/tags.json")

HOST_DEFAULT = "127.0.0.1"
PORT_DEFAULT = 5051


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s)
    return s.strip("-")


def normalize_tag_list(tags: List[str]) -> List[str]:
    out = []
    for t in tags:
        t = slugify(str(t))
        if t and t not in out:
            out.append(t)
    return out


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Dict[str, Any]) -> None:
    data["generatedAt"] = now_iso()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    bak = path.with_name(path.name + f".bak.{ts}")
    bak.write_bytes(path.read_bytes())
    return bak


def tag_counts(photos: List[Dict[str, Any]]) -> Counter:
    c = Counter()
    for ph in photos:
        tags = ph.get("tags", [])
        if isinstance(tags, list):
            for t in tags:
                if isinstance(t, str) and t:
                    c[t] += 1
    return c


def cooccurrence_pairs(photos: List[Dict[str, Any]], top_n: int = 50) -> List[Dict[str, Any]]:
    pair_counts = Counter()
    for ph in photos:
        tags = ph.get("tags", [])
        if not isinstance(tags, list):
            continue
        tags = [t for t in tags if isinstance(t, str) and t]
        tags = sorted(set(tags))
        for i in range(len(tags)):
            for j in range(i + 1, len(tags)):
                pair_counts[(tags[i], tags[j])] += 1
    out = []
    for (a, b), cnt in pair_counts.most_common(top_n):
        out.append({"a": a, "b": b, "count": cnt})
    return out


def related_tags(photos: List[Dict[str, Any]], anchor: str, top_n: int = 30) -> List[Dict[str, Any]]:
    anchor = slugify(anchor)
    co = Counter()
    for ph in photos:
        tags = ph.get("tags", [])
        if not isinstance(tags, list):
            continue
        tags = [t for t in tags if isinstance(t, str) and t]
        if anchor not in tags:
            continue
        for t in set(tags):
            if t != anchor:
                co[t] += 1
    return [{"tag": t, "count": c} for t, c in co.most_common(top_n)]


def generate_tags_json(photos_json: Dict[str, Any]) -> Dict[str, Any]:
    c = tag_counts(photos_json.get("photos", []))
    tags_sorted = sorted(c.keys())
    return {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "tags": [{"name": t, "count": c[t]} for t in tags_sorted],
    }


def apply_rename(photos: List[Dict[str, Any]], old: str, new: str) -> Tuple[int, int]:
    """
    Returns: (photos_touched, total_replacements)
    """
    old = slugify(old)
    new = slugify(new)
    if not old or not new:
        return 0, 0
    touched = 0
    replacements = 0
    for ph in photos:
        tags = ph.get("tags", [])
        if not isinstance(tags, list):
            continue
        if old not in tags:
            continue
        new_tags = []
        for t in tags:
            if t == old:
                new_tags.append(new)
                replacements += 1
            else:
                new_tags.append(t)
        ph["tags"] = normalize_tag_list(new_tags)
        touched += 1
    return touched, replacements


def apply_delete(photos: List[Dict[str, Any]], tag: str) -> Tuple[int, int]:
    tag = slugify(tag)
    if not tag:
        return 0, 0
    touched = 0
    removed = 0
    for ph in photos:
        tags = ph.get("tags", [])
        if not isinstance(tags, list):
            continue
        if tag not in tags:
            continue
        ph["tags"] = [t for t in tags if t != tag]
        ph["tags"] = normalize_tag_list(ph["tags"])
        removed += 1
        touched += 1
    return touched, removed


def apply_merge(photos: List[Dict[str, Any]], sources: List[str], target: str) -> Tuple[int, int]:
    sources = [slugify(s) for s in sources]
    sources = [s for s in sources if s]
    target = slugify(target)
    if not sources or not target:
        return 0, 0
    touched = 0
    merges = 0
    sources_set = set(sources)
    for ph in photos:
        tags = ph.get("tags", [])
        if not isinstance(tags, list):
            continue
        tags_set = set([t for t in tags if isinstance(t, str)])
        if not (tags_set & sources_set):
            continue
        # remove sources; add target
        new_tags = [t for t in tags if t not in sources_set]
        new_tags.append(target)
        ph["tags"] = normalize_tag_list(new_tags)
        touched += 1
        merges += 1
    return touched, merges


PAGE = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Tag Maintenance</title>
  <style>
    :root { --border: 1px solid rgba(0,0,0,.15); --maxw: 1120px; }
    body { margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; color:#111; }
    header { position: sticky; top:0; background: rgba(255,255,255,.92); backdrop-filter: blur(8px); border-bottom: var(--border); z-index:10; }
    .wrap { max-width: var(--maxw); margin: 0 auto; padding: 12px 16px; }
    .grid { display:grid; grid-template-columns: 1fr 1fr; gap: 14px; padding: 16px; max-width: var(--maxw); margin: 0 auto; }
    @media (max-width: 980px) { .grid { grid-template-columns: 1fr; } }
    .card { border: var(--border); border-radius: 16px; padding: 14px; }
    h2 { margin: 0 0 10px; font-size: 16px; }
    label { display:grid; gap: 6px; font-size: 12px; margin-bottom: 10px; }
    input, textarea, select { padding: 10px 12px; border-radius: 12px; border: var(--border); font-size: 14px; }
    textarea { min-height: 88px; resize: vertical; }
    .row { display:flex; gap: 10px; flex-wrap: wrap; align-items: center; }
    .btn { padding: 10px 14px; border-radius: 12px; border: var(--border); background:#111; color:#fff; cursor:pointer; font-weight: 650; }
    .btn.secondary { background:#fff; color:#111; }
    .pill { display:inline-flex; align-items:center; gap:8px; padding:6px 10px; border: var(--border); border-radius: 999px; font-size: 12px; background:#f7f7f7; }
    .hint { font-size: 12px; opacity: .75; margin-top: 6px; }
    .table { width:100%; border-collapse: collapse; font-size: 13px; }
    .table th, .table td { border-bottom: var(--border); padding: 8px 6px; text-align: left; }
    .table th { font-size: 12px; opacity: .8; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; }
    .scroll { max-height: 380px; overflow:auto; border: var(--border); border-radius: 12px; }
    .ok { color: #067d2b; font-weight: 650; }
    .warn { color: #b45309; font-weight: 650; }
    .danger { color: #b91c1c; font-weight: 650; }
  </style>
</head>
<body>
<header>
  <div class="wrap row" style="justify-content: space-between;">
    <div class="row">
      <div class="pill"><b>Photos</b> <span id="photoCount">—</span></div>
      <div class="pill"><b>Tags</b> <span id="tagCount">—</span></div>
    </div>
    <div class="row">
      <button class="btn secondary" id="refreshBtn" type="button">Refresh stats</button>
      <form action="/exit" method="post" style="margin:0;">
        <button class="btn" type="submit">Save & Exit</button>
      </form>
    </div>
  </div>
</header>

<div class="grid">
  <div class="card">
    <h2>Rename tag</h2>
    <label>Old tag<input id="renameOld" placeholder="e.g. streetphoto"/></label>
    <label>New tag<input id="renameNew" placeholder="e.g. street"/></label>
    <div class="row">
      <button class="btn" id="renameBtn" type="button">Preview</button>
      <button class="btn secondary" id="renameApplyBtn" type="button">Apply</button>
    </div>
    <div class="hint" id="renameOut"></div>
  </div>

  <div class="card">
    <h2>Merge tags</h2>
    <label>Source tags (space or comma separated)<textarea id="mergeSrc" placeholder="tag1 tag2 tag3"></textarea></label>
    <label>Target tag<input id="mergeDst" placeholder="target-tag"/></label>
    <div class="row">
      <button class="btn" id="mergeBtn" type="button">Preview</button>
      <button class="btn secondary" id="mergeApplyBtn" type="button">Apply</button>
    </div>
    <div class="hint" id="mergeOut"></div>
  </div>

  <div class="card">
    <h2>Delete tag</h2>
    <label>Tag<input id="deleteTag" placeholder="tag-to-delete"/></label>
    <div class="row">
      <button class="btn" id="deleteBtn" type="button">Preview</button>
      <button class="btn secondary" id="deleteApplyBtn" type="button">Apply</button>
    </div>
    <div class="hint" id="deleteOut"></div>
  </div>

  <div class="card">
    <h2>Related tags / Overlaps</h2>
    <label>Anchor tag<input id="anchorTag" placeholder="e.g. film"/></label>
    <div class="row">
      <button class="btn" id="anchorBtn" type="button">Show related</button>
      <button class="btn secondary" id="pairsBtn" type="button">Top pairs</button>
    </div>
    <div class="scroll" style="margin-top:10px;">
      <table class="table" id="overlapTable"></table>
    </div>
  </div>

  <div class="card" style="grid-column: 1 / -1;">
    <h2>Tag usage</h2>
    <label>Search<input id="search" placeholder="type to filter tags..."/></label>
    <div class="scroll">
      <table class="table" id="usageTable"></table>
    </div>
  </div>
</div>

<script>
  const usageTable = document.getElementById("usageTable");
  const overlapTable = document.getElementById("overlapTable");
  const searchEl = document.getElementById("search");
  const photoCountEl = document.getElementById("photoCount");
  const tagCountEl = document.getElementById("tagCount");

  async function getStats() {
    const res = await fetch("/api/stats");
    return await res.json();
  }

  function renderUsage(tags, query="") {
    usageTable.innerHTML = "";
    const q = (query || "").trim().toLowerCase();
    const filtered = q ? tags.filter(t => t.name.includes(q)) : tags;

    usageTable.innerHTML = "<tr><th>Tag</th><th>Count</th></tr>" +
      filtered.map(t => `<tr><td class="mono">${t.name}</td><td>${t.count}</td></tr>`).join("");
  }

  function renderRelated(items, title) {
    overlapTable.innerHTML = "";
    overlapTable.innerHTML = `<tr><th colspan="2">${title}</th></tr>` +
      items.map(x => `<tr><td class="mono">${x.tag}</td><td>${x.count}</td></tr>`).join("");
  }

  function renderPairs(items) {
    overlapTable.innerHTML = "";
    overlapTable.innerHTML = "<tr><th>Tag A</th><th>Tag B</th><th>Count</th></tr>" +
      items.map(x => `<tr><td class="mono">${x.a}</td><td class="mono">${x.b}</td><td>${x.count}</td></tr>`).join("");
  }

  async function refresh() {
    const s = await getStats();
    photoCountEl.textContent = s.photosCount;
    tagCountEl.textContent = s.tags.length;
    renderUsage(s.tags, searchEl.value);
  }

  searchEl.addEventListener("input", () => refresh());

  document.getElementById("refreshBtn").addEventListener("click", refresh);

  async function preview(op, payload, outEl) {
    const res = await fetch("/api/preview/" + op, {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(payload)
    });
    const j = await res.json();
    outEl.textContent = j.message;
    outEl.className = "hint " + (j.ok ? "ok" : "danger");
  }

  async function apply(op, payload, outEl) {
    const res = await fetch("/api/apply/" + op, {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(payload)
    });
    const j = await res.json();
    outEl.textContent = j.message;
    outEl.className = "hint " + (j.ok ? "ok" : "danger");
    await refresh();
  }

  document.getElementById("renameBtn").addEventListener("click", () =>
    preview("rename", {old: document.getElementById("renameOld").value, new: document.getElementById("renameNew").value}, document.getElementById("renameOut"))
  );
  document.getElementById("renameApplyBtn").addEventListener("click", () =>
    apply("rename", {old: document.getElementById("renameOld").value, new: document.getElementById("renameNew").value}, document.getElementById("renameOut"))
  );

  document.getElementById("mergeBtn").addEventListener("click", () =>
    preview("merge", {sources: document.getElementById("mergeSrc").value, target: document.getElementById("mergeDst").value}, document.getElementById("mergeOut"))
  );
  document.getElementById("mergeApplyBtn").addEventListener("click", () =>
    apply("merge", {sources: document.getElementById("mergeSrc").value, target: document.getElementById("mergeDst").value}, document.getElementById("mergeOut"))
  );

  document.getElementById("deleteBtn").addEventListener("click", () =>
    preview("delete", {tag: document.getElementById("deleteTag").value}, document.getElementById("deleteOut"))
  );
  document.getElementById("deleteApplyBtn").addEventListener("click", () =>
    apply("delete", {tag: document.getElementById("deleteTag").value}, document.getElementById("deleteOut"))
  );

  document.getElementById("anchorBtn").addEventListener("click", async () => {
    const tag = document.getElementById("anchorTag").value;
    const res = await fetch("/api/related?tag=" + encodeURIComponent(tag));
    const j = await res.json();
    renderRelated(j.items || [], `Related to "${j.anchor}"`);
  });

  document.getElementById("pairsBtn").addEventListener("click", async () => {
    const res = await fetch("/api/pairs");
    const j = await res.json();
    renderPairs(j.items || []);
  });

  refresh();
</script>
</body>
</html>
"""


def create_app(repo_root: Path) -> Flask:
    app = Flask(__name__)

    photos_path = repo_root / DATA_REL
    tags_path = repo_root / TAGS_REL

    # Load into memory once; apply changes and write on every "apply"
    photos_json = load_json(photos_path)
    if not isinstance(photos_json.get("photos", []), list):
        photos_json["photos"] = []

    def write_all():
        # backup first
        bak = backup_file(photos_path)
        if bak:
            print(f"[backup] Wrote {bak.name}")
        save_json(photos_path, photos_json)
        save_json(tags_path, generate_tags_json(photos_json))

    @app.get("/")
    def root():
        return render_template_string(PAGE)

    @app.get("/api/stats")
    def api_stats():
        photos = photos_json.get("photos", [])
        c = tag_counts(photos)
        tags = [{"name": t, "count": c[t]} for t in sorted(c.keys())]
        tags.sort(key=lambda x: (-x["count"], x["name"]))
        return jsonify({"photosCount": len(photos), "tags": tags})

    @app.get("/api/pairs")
    def api_pairs():
        photos = photos_json.get("photos", [])
        return jsonify({"items": cooccurrence_pairs(photos, top_n=60)})

    @app.get("/api/related")
    def api_related():
        photos = photos_json.get("photos", [])
        tag = request.args.get("tag", "")
        tag_s = slugify(tag)
        return jsonify({"anchor": tag_s, "items": related_tags(photos, tag_s, top_n=40)})

    @app.post("/api/preview/rename")
    def preview_rename():
        photos = photos_json.get("photos", [])
        payload = request.get_json(force=True)
        old = slugify(payload.get("old", ""))
        new = slugify(payload.get("new", ""))
        if not old or not new:
            return jsonify({"ok": False, "message": "Provide both old and new tags."})
        touched, repl = apply_rename([dict(p) for p in photos], old, new)  # simulate on copies
        return jsonify({"ok": True, "message": f"Would rename '{old}' → '{new}' in {touched} photo(s). Replacements: {repl}."})

    @app.post("/api/apply/rename")
    def apply_rename_api():
        photos = photos_json.get("photos", [])
        payload = request.get_json(force=True)
        old = slugify(payload.get("old", ""))
        new = slugify(payload.get("new", ""))
        if not old or not new:
            return jsonify({"ok": False, "message": "Provide both old and new tags."})
        touched, repl = apply_rename(photos, old, new)
        write_all()
        return jsonify({"ok": True, "message": f"Renamed '{old}' → '{new}' in {touched} photo(s). Replacements: {repl}."})

    @app.post("/api/preview/delete")
    def preview_delete():
        photos = photos_json.get("photos", [])
        payload = request.get_json(force=True)
        tag = slugify(payload.get("tag", ""))
        if not tag:
            return jsonify({"ok": False, "message": "Provide a tag to delete."})
        touched, removed = apply_delete([dict(p) for p in photos], tag)
        return jsonify({"ok": True, "message": f"Would delete '{tag}' from {touched} photo(s)."} )

    @app.post("/api/apply/delete")
    def apply_delete_api():
        photos = photos_json.get("photos", [])
        payload = request.get_json(force=True)
        tag = slugify(payload.get("tag", ""))
        if not tag:
            return jsonify({"ok": False, "message": "Provide a tag to delete."})
        touched, removed = apply_delete(photos, tag)
        write_all()
        return jsonify({"ok": True, "message": f"Deleted '{tag}' from {touched} photo(s)."} )

    @app.post("/api/preview/merge")
    def preview_merge():
        photos = photos_json.get("photos", [])
        payload = request.get_json(force=True)
        sources_raw = payload.get("sources", "")
        target = slugify(payload.get("target", ""))
        sources = [s for s in re.split(r"[,\s]+", sources_raw.strip()) if s]
        sources = [slugify(s) for s in sources if s]
        if not sources or not target:
            return jsonify({"ok": False, "message": "Provide sources and a target tag."})
        touched, merges = apply_merge([dict(p) for p in photos], sources, target)
        return jsonify({"ok": True, "message": f"Would merge {sources} → '{target}' affecting {touched} photo(s)."} )

    @app.post("/api/apply/merge")
    def apply_merge_api():
        photos = photos_json.get("photos", [])
        payload = request.get_json(force=True)
        sources_raw = payload.get("sources", "")
        target = slugify(payload.get("target", ""))
        sources = [s for s in re.split(r"[,\s]+", sources_raw.strip()) if s]
        sources = [slugify(s) for s in sources if s]
        if not sources or not target:
            return jsonify({"ok": False, "message": "Provide sources and a target tag."})
        touched, merges = apply_merge(photos, sources, target)
        write_all()
        return jsonify({"ok": True, "message": f"Merged {sources} → '{target}' affecting {touched} photo(s)."} )

    @app.post("/exit")
    def exit_app():
        write_all()
        func = request.environ.get("werkzeug.server.shutdown")
        if func:
            func()
        return "Saved. Exiting… You can close this tab."

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", default=".", help="Repo root")
    ap.add_argument("--host", default=HOST_DEFAULT)
    ap.add_argument("--port", type=int, default=PORT_DEFAULT)
    args = ap.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    app = create_app(repo_root)

    url = f"http://{args.host}:{args.port}"
    print(f"[tag-maint] Launching at {url}")
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()