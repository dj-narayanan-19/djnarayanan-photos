#!/usr/bin/env python3
"""
Photo ingest + local tagger server for a GitHub Pages photo site.

Adds:
- Copy previous tags button (and displays previous tags)
- Clickable event chips (like misc suggestions)
- Captures additional EXIF fields (exposure time, f-number, ISO, focal length)
- Auto-defaults medium to "digital" when camera EXIF exists

Usage:
  source .venv/bin/activate
  python3 tools/ingest.py --originals "/path/to/originals" --repo-root "."
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, redirect, render_template_string, request, send_file, url_for
from PIL import Image, ImageOps, ExifTags


SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}  # keep v1 simple; HEIC later if needed

DEFAULT_THUMB_LONG_EDGE = 450
DEFAULT_DISPLAY_LONG_EDGE = 2000

DATA_REL = Path("data/photos.json")
THUMBS_REL = Path("assets/thumbs")
DISPLAY_REL = Path("assets/display")

HOST = "127.0.0.1"
PORT = 5050


# ----------------------------
# Utilities
# ----------------------------
def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s)
    return s.strip("-")


def ensure_dirs(repo_root: Path) -> None:
    for p in [repo_root / THUMBS_REL, repo_root / DISPLAY_REL, repo_root / DATA_REL.parent]:
        p.mkdir(parents=True, exist_ok=True)


def load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"schemaVersion": 1, "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "photos": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Dict[str, Any]) -> None:
    data["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def fingerprint_for_file(p: Path) -> str:
    st = p.stat()
    return f"size:{st.st_size}_mtime:{int(st.st_mtime)}"


def build_existing_fingerprints(photos_json: Dict[str, Any]) -> set[str]:
    fps = set()
    for ph in photos_json.get("photos", []):
        fp = ph.get("source", {}).get("fingerprint")
        if fp:
            fps.add(fp)
    return fps


def safe_open_image(path: Path) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    return img


def resize_long_edge(img: Image.Image, long_edge: int) -> Image.Image:
    w, h = img.size
    if max(w, h) <= long_edge:
        return img.copy()
    if w >= h:
        new_w = long_edge
        new_h = int(round(h * (long_edge / w)))
    else:
        new_h = long_edge
        new_w = int(round(w * (long_edge / h)))
    return img.resize((new_w, new_h), Image.Resampling.LANCZOS)


def to_jpeg(img: Image.Image, out_path: Path, quality: int) -> None:
    # v1: practical default, convert to RGB and write JPEG
    if img.mode != "RGB":
        img = img.convert("RGB")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="JPEG", quality=quality, optimize=True, progressive=True)


def _to_float_ratio(val) -> Optional[float]:
    # EXIF may store rationals
    try:
        if isinstance(val, tuple) and len(val) == 2:
            num, den = val
            return float(num) / float(den) if den else None
        # Pillow sometimes returns IFDRational-like objects
        return float(val)
    except Exception:
        return None


def _format_exposure_time(val) -> Optional[str]:
    f = _to_float_ratio(val)
    if f is None:
        return None
    if f >= 1:
        # 1.0 -> "1s", 1.3 -> "1.3s"
        return f"{f:g}s"
    # 0.004 -> "1/250s" (approx)
    denom = round(1 / f)
    if denom > 0:
        return f"1/{denom}s"
    return None


def _format_fnumber(val) -> Optional[str]:
    f = _to_float_ratio(val)
    if f is None:
        return None
    return f"f/{f:.1f}".rstrip("0").rstrip(".")


def _format_focal_length(val) -> Optional[str]:
    f = _to_float_ratio(val)
    if f is None:
        return None
    # Typically mm
    return f"{f:.0f}mm"


def get_exif_fields(img: Image.Image) -> Dict[str, Optional[str]]:
    """
    Returns strings so they're easy to display on site.
    """
    try:
        exif = img.getexif()
        if not exif:
            return {
                "dateTaken": None,
                "cameraMake": None,
                "cameraModel": None,
                "lensModel": None,
                "exposureTime": None,
                "fNumber": None,
                "iso": None,
                "focalLength": None,
            }

        tag_map = {v: k for k, v in ExifTags.TAGS.items()}  # name -> id

        def get(tag_name: str):
            tid = tag_map.get(tag_name)
            return exif.get(tid) if tid is not None else None

        dt = get("DateTimeOriginal") or get("DateTime")
        if isinstance(dt, bytes):
            dt = dt.decode("utf-8", errors="ignore")
        if isinstance(dt, str) and ":" in dt[:10]:
            dt = dt.replace(":", "-", 2).replace(" ", "T", 1)

        make = get("Make")
        model = get("Model")
        lens = get("LensModel") or get("LensSpecification")

        if isinstance(make, bytes):
            make = make.decode("utf-8", errors="ignore")
        if isinstance(model, bytes):
            model = model.decode("utf-8", errors="ignore")
        if isinstance(lens, bytes):
            lens = lens.decode("utf-8", errors="ignore")

        exposure = _format_exposure_time(get("ExposureTime"))
        fnum = _format_fnumber(get("FNumber"))
        iso = get("ISOSpeedRatings") or get("PhotographicSensitivity")
        if isinstance(iso, (list, tuple)) and iso:
            iso = iso[0]
        iso_str = str(iso) if iso is not None else None

        focal = _format_focal_length(get("FocalLength"))

        out = {
            "dateTaken": dt if isinstance(dt, str) else None,
            "cameraMake": str(make).strip() if make else None,
            "cameraModel": str(model).strip() if model else None,
            "lensModel": str(lens).strip() if lens else None,
            "exposureTime": exposure,
            "fNumber": fnum,
            "iso": iso_str,
            "focalLength": focal,
        }

        # normalize empties
        for k, v in list(out.items()):
            if not v or v == "None":
                out[k] = None

        return out
    except Exception:
        return {
            "dateTaken": None,
            "cameraMake": None,
            "cameraModel": None,
            "lensModel": None,
            "exposureTime": None,
            "fNumber": None,
            "iso": None,
            "focalLength": None,
        }


def make_id(exif_date_taken: Optional[str], original_name: str) -> str:
    if exif_date_taken and len(exif_date_taken) >= 10:
        date_part = exif_date_taken[:10]
    else:
        date_part = time.strftime("%Y-%m-%d", time.localtime())
    base = slugify(Path(original_name).stem) or "photo"
    return f"{date_part}_{base}"


def uniquify_id(candidate: str, existing_ids: set[str]) -> str:
    if candidate not in existing_ids:
        return candidate
    i = 2
    while f"{candidate}-{i}" in existing_ids:
        i += 1
    return f"{candidate}-{i}"


# ----------------------------
# Data model for pending queue
# ----------------------------
@dataclass
class PendingItem:
    id: str
    original_path: Path
    display_rel: str
    thumb_rel: str
    exif: Dict[str, Optional[str]]
    source_fingerprint: str
    original_filename: str


# ----------------------------
# Local Tagger UI (Flask)
# ----------------------------
TEMPLATE = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Photo Tagger</title>
  <style>
    :root { --maxw: 1120px; --border: 1px solid rgba(0,0,0,.15); }
    body { margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; background:#fff; color:#111; }
    header { position: sticky; top:0; background: rgba(255,255,255,.92); backdrop-filter: blur(8px); border-bottom: var(--border); z-index:10; }
    .wrap { max-width: var(--maxw); margin: 0 auto; padding: 12px 16px; }
    .row { display:flex; gap:16px; align-items:center; justify-content: space-between; flex-wrap: wrap; }
    .pill { display:inline-flex; gap:8px; align-items:center; padding:6px 10px; border: var(--border); border-radius: 999px; font-size: 12px; background:#f7f7f7; }
    main .wrap { display:grid; grid-template-columns: 1.6fr 1fr; gap: 16px; padding-top: 16px; }
    @media (max-width: 900px) { main .wrap { grid-template-columns: 1fr; } }
    .card { border: var(--border); border-radius: 16px; overflow:hidden; background:#fff; }
    .imgbox { background:#000; display:grid; place-items:center; min-height: 360px; }
    img { max-width:100%; max-height: 78vh; display:block; }
    .meta { padding: 10px 12px; border-top: var(--border); font-size: 12px; opacity:.88; line-height: 1.45; }
    .form { padding: 12px; display:grid; gap: 10px; }
    label { display:grid; gap: 6px; font-size: 12px; }
    input, select { padding: 10px 12px; border-radius: 12px; border: var(--border); font-size: 14px; }
    .chips { display:flex; flex-wrap: wrap; gap: 8px; }
    .chipbtn { padding: 7px 10px; border-radius: 999px; border: var(--border); background:#fff; cursor:pointer; font-size: 12px; }
    .btnrow { display:flex; gap:10px; flex-wrap: wrap; }
    .btn { padding: 10px 14px; border-radius: 12px; border: var(--border); background: #111; color:#fff; cursor:pointer; font-weight: 650; }
    .btn.secondary { background:#fff; color:#111; }
    .hint { font-size: 12px; opacity: .75; }
    .small { font-size: 12px; opacity:.8; }
    .sectionTitle { font-size: 12px; margin: 6px 0 6px; opacity:.85; }
    .prevbox { border: var(--border); border-radius: 14px; padding: 10px; background:#fafafa; }
    .prevtags { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; opacity: .9; }
  </style>
</head>
<body>
<header>
  <div class="wrap row">
    <div class="row" style="gap:10px;">
      <div class="pill"><b>Queue</b> {{idx+1}} / {{total}}</div>
      <div class="pill"><b>ID</b> {{item.id}}</div>
    </div>
    <div class="row" style="gap:10px;">
      <button class="btn secondary" id="prevBtn" type="button">← Prev</button>
      <button class="btn secondary" id="nextBtn" type="button">Next →</button>
    </div>
  </div>
</header>

<main>
  <div class="wrap">
    <div class="card">
      <div class="imgbox">
        <img id="photo" src="{{ url_for('serve_display', photo_id=item.id) }}" alt="photo"/>
      </div>
      <div class="meta">
        <div><b>Original:</b> {{item.original_filename}}</div>
        <div><b>Date:</b> {{item.exif.get('dateTaken') or '—'}} &nbsp; <b>Camera:</b> {{item.exif.get('cameraModel') or '—'}}</div>
        <div class="small">
          <b>Exposure:</b> {{item.exif.get('exposureTime') or '—'}} &nbsp;
          <b>Aperture:</b> {{item.exif.get('fNumber') or '—'}} &nbsp;
          <b>ISO:</b> {{item.exif.get('iso') or '—'}} &nbsp;
          <b>Focal:</b> {{item.exif.get('focalLength') or '—'}}
        </div>
      </div>
    </div>

    <div class="card">
      <form class="form" id="tagForm">
        <div class="hint">
          Tips: <b>Enter</b> = Save & Next • <b>←/→</b> = Prev/Next
        </div>

        <div class="prevbox">
          <div class="row" style="justify-content: space-between; gap:10px;">
            <div class="sectionTitle" style="margin:0;"><b>Previous tags</b> (from last save)</div>
            <button class="btn secondary" id="copyPrev" type="button">Copy previous tags</button>
          </div>
          <div class="prevtags" id="prevTagsText">None yet.</div>
        </div>

        <label>
          Medium (auto-defaulted)
          <select name="medium" id="medium">
            <option value="">(select)</option>
            <option value="digital">digital</option>
            <option value="film">film</option>
          </select>
        </label>

        <label>
          Color
          <select name="color" id="color">
            <option value="">(select)</option>
            <option value="color">color</option>
            <option value="bw">bw</option>
          </select>
        </label>

        <label>
          Event / Trip (autocomplete)
          <input name="event" id="event" list="eventList" placeholder="e.g., prague-2024"/>
          <datalist id="eventList"></datalist>
        </label>

        <div>
          <div class="sectionTitle">Event suggestions (click)</div>
          <div class="chips" id="eventChips"></div>
        </div>

        <label>
          Camera (autocomplete; EXIF prefill)
          <input name="camera" id="camera" list="cameraList" placeholder="e.g., x100v"/>
          <datalist id="cameraList"></datalist>
        </label>

        <div>
          <div class="sectionTitle">Quick add</div>
          <div class="chips">
            <button class="chipbtn" type="button" data-add="medium:digital">digital</button>
            <button class="chipbtn" type="button" data-add="medium:film">film</button>
            <button class="chipbtn" type="button" data-add="color:color">color</button>
            <button class="chipbtn" type="button" data-add="color:bw">bw</button>
          </div>
        </div>

        <label>
          Misc tags (space-separated; click suggestions)
          <input name="misc" id="misc" placeholder="e.g., street night portrait"/>
        </label>
        <div class="chips" id="miscSuggestions"></div>

        <div class="btnrow">
          <button class="btn" id="saveNext" type="submit">Save & Next</button>
          <button class="btn secondary" id="skip" type="button">Skip (leave untagged)</button>
        </div>
      </form>
    </div>
  </div>
</main>

<script>
  const idx = {{idx}};
  const total = {{total}};
  const exifModel = {{ (item.exif.get('cameraModel') or "") | tojson }};
  const defaultMedium = {{ default_medium | tojson }};

  const eventEl = document.getElementById('event');
  const cameraEl = document.getElementById('camera');
  const miscEl = document.getElementById('misc');
  const mediumEl = document.getElementById('medium');
  const colorEl = document.getElementById('color');

  const eventList = document.getElementById('eventList');
  const cameraList = document.getElementById('cameraList');
  const miscSuggestions = document.getElementById('miscSuggestions');
  const eventChips = document.getElementById('eventChips');

  const prevTagsText = document.getElementById('prevTagsText');
  const copyPrevBtn = document.getElementById('copyPrev');

  function setDatalist(datalistEl, items) {
    datalistEl.innerHTML = "";
    for (const t of items) {
      const opt = document.createElement("option");
      opt.value = t;
      datalistEl.appendChild(opt);
    }
  }

  function setChips(container, items, onClick, limit=18) {
    container.innerHTML = "";
    for (const t of items.slice(0, limit)) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chipbtn";
      b.textContent = t;
      b.addEventListener("click", () => onClick(t));
      container.appendChild(b);
    }
  }

  function parseMisc(val) {
    const raw = val.trim();
    if (!raw) return [];
    return raw.split(/\s+/).filter(Boolean);
  }

  async function loadBanksAndPrev() {
    const [bankRes, prevRes] = await Promise.all([
      fetch("/api/tagbank"),
      fetch("/api/prev")
    ]);
    const bank = await bankRes.json();
    const prev = await prevRes.json();

    setDatalist(eventList, bank.event || []);
    setDatalist(cameraList, bank.camera || []);

    // Event chips
    setChips(eventChips, bank.event || [], (t) => { eventEl.value = t; eventEl.focus(); }, 24);

    // Misc chips
    setChips(miscSuggestions, bank.misc || [], (t) => {
      const parts = parseMisc(miscEl.value);
      if (!parts.includes(t)) parts.push(t);
      miscEl.value = parts.join(" ");
      miscEl.focus();
    }, 24);

    // Prefill camera: if EXIF model exists, keep it; otherwise blank
    if (!cameraEl.value && exifModel) cameraEl.value = bank.cameraMap?.[exifModel] || exifModel;

    // Default medium
    if (!mediumEl.value && defaultMedium) mediumEl.value = defaultMedium;

    // Previous tags display
    if (prev && prev.ok && prev.tagsText) {
      prevTagsText.textContent = prev.tagsText;
      copyPrevBtn.disabled = false;
    } else {
      prevTagsText.textContent = "None yet.";
      copyPrevBtn.disabled = true;
    }
  }

  // Quick-add buttons
  document.querySelectorAll("[data-add]").forEach(btn => {
    btn.addEventListener("click", () => {
      const [cat, val] = btn.dataset.add.split(":");
      if (cat === "medium") mediumEl.value = val;
      if (cat === "color") colorEl.value = val;
    });
  });

  // Copy previous tags
  copyPrevBtn.addEventListener("click", async () => {
    const res = await fetch("/api/prev");
    const prev = await res.json();
    if (!prev.ok) return;
    // Apply previous tags to current form
    mediumEl.value = prev.medium || mediumEl.value;
    colorEl.value = prev.color || colorEl.value;
    eventEl.value = prev.event || eventEl.value;
    cameraEl.value = prev.camera || cameraEl.value;

    // Merge misc
    const cur = parseMisc(miscEl.value);
    const add = (prev.misc || []);
    for (const t of add) if (t && !cur.includes(t)) cur.push(t);
    miscEl.value = cur.join(" ");
  });

  // Prev / Next buttons
  document.getElementById("prevBtn").addEventListener("click", () => location.href = "/tag/" + Math.max(0, idx - 1));
  document.getElementById("nextBtn").addEventListener("click", () => location.href = "/tag/" + Math.min(total - 1, idx + 1));

  // Skip
  document.getElementById("skip").addEventListener("click", async () => {
    await fetch("/api/skip", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({ idx }) });
    location.href = (idx + 1 >= total) ? "/done" : ("/tag/" + (idx + 1));
  });

  // Save
  document.getElementById("tagForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      idx,
      medium: mediumEl.value.trim(),
      color: colorEl.value.trim(),
      event: eventEl.value.trim(),
      camera: cameraEl.value.trim(),
      misc: miscEl.value.trim()
    };
    const res = await fetch("/api/save", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify(payload)
    });
    const out = await res.json();
    if (!out.ok) {
      alert(out.error || "Save failed");
      return;
    }
    location.href = (idx + 1 >= total) ? "/done" : ("/tag/" + (idx + 1));
  });

  // Keyboard shortcuts
  document.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") location.href = "/tag/" + Math.max(0, idx - 1);
    if (e.key === "ArrowRight") location.href = "/tag/" + Math.min(total - 1, idx + 1);
    if (e.key === "Enter" && (document.activeElement?.tagName !== "TEXTAREA")) {
      // Let the form submit naturally when focused in an input/select
    }
  });

  loadBanksAndPrev();
</script>
</body>
</html>
"""

DONE_TEMPLATE = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Done</title>
  <style>
    body { margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; }
    .wrap { max-width: 860px; margin: 0 auto; padding: 28px 18px; }
    .card { border: 1px solid rgba(0,0,0,.15); border-radius: 16px; padding: 18px; }
    .cmd { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; background:#f6f6f6; padding: 10px 12px; border-radius: 12px; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h2>All set ✅</h2>
      <p>No more photos in the queue.</p>
      <p>Next steps:</p>
      <div class="cmd">git status<br/>git add data/photos.json assets/thumbs assets/display<br/>git commit -m "Add new photos"<br/>git push</div>
    </div>
  </div>
</body>
</html>
"""


def build_tagbank(photos_json: Dict[str, Any]) -> Dict[str, Any]:
    bank = {"event": set(), "camera": set(), "misc": set()}
    for ph in photos_json.get("photos", []):
        tags = ph.get("tags", {})
        for cat in ("event", "camera", "misc"):
            vals = tags.get(cat, [])
            if isinstance(vals, list):
                for v in vals:
                    if isinstance(v, str) and v.strip():
                        bank[cat].add(v.strip())

    # optional mapping: EXIF model -> your desired slug (leave empty for now)
    camera_map = {}

    return {
        "event": sorted(bank["event"]),
        "camera": sorted(bank["camera"]),
        "misc": sorted(bank["misc"]),
        "cameraMap": camera_map,
    }


def create_app(
    pending: List[PendingItem],
    repo_root: Path,
    photos_json_path: Path,
    photos_json: Dict[str, Any],
) -> Flask:
    app = Flask(__name__)

    # server-side memory for "copy previous tags"
    prev_tags: Dict[str, Any] = {"ok": False}

    def _tags_text(t: Dict[str, Any]) -> str:
        # Human-friendly display
        parts = []
        if t.get("medium"): parts.append(f"medium={t['medium']}")
        if t.get("color"): parts.append(f"color={t['color']}")
        if t.get("event"): parts.append(f"event={t['event']}")
        if t.get("camera"): parts.append(f"camera={t['camera']}")
        if t.get("misc"):
            parts.append("misc=" + " ".join(t["misc"]))
        return " • ".join(parts) if parts else "None"

    @app.get("/")
    def root():
        if not pending:
            return redirect(url_for("done"))
        return redirect(url_for("tag_page", idx=0))

    @app.get("/tag/<int:idx>")
    def tag_page(idx: int):
        if not pending:
            return redirect(url_for("done"))
        idx = max(0, min(idx, len(pending) - 1))
        item = pending[idx]

        # auto-default medium: if EXIF camera model exists, default digital; else blank (user chooses)
        default_medium = "digital" if (item.exif.get("cameraMake") or item.exif.get("cameraModel")) else ""
        return render_template_string(TEMPLATE, item=item, idx=idx, total=len(pending), default_medium=default_medium)

    @app.get("/display/<photo_id>")
    def serve_display(photo_id: str):
        for it in pending:
            if it.id == photo_id:
                fp = repo_root / it.display_rel
                return send_file(fp)
        return ("Not found", 404)

    @app.get("/api/tagbank")
    def api_tagbank():
        return jsonify(build_tagbank(photos_json))

    @app.get("/api/prev")
    def api_prev():
        nonlocal prev_tags
        if not prev_tags.get("ok"):
            return jsonify({"ok": False})
        out = dict(prev_tags)
        out["tagsText"] = _tags_text(prev_tags)
        return jsonify(out)

    @app.post("/api/skip")
    def api_skip():
        return jsonify({"ok": True})

    @app.post("/api/save")
    def api_save():
        nonlocal photos_json, prev_tags

        payload = request.get_json(force=True)
        idx = int(payload.get("idx", -1))
        if idx < 0 or idx >= len(pending):
            return jsonify({"ok": False, "error": "Bad idx"})

        it = pending[idx]

        # Raw from UI
        medium = payload.get("medium", "").strip()
        color = payload.get("color", "").strip()
        event_raw = payload.get("event", "").strip()
        camera_raw = payload.get("camera", "").strip()
        misc_raw = payload.get("misc", "").strip()

        # Normalize (slugs for stable tags)
        event = slugify(event_raw) if event_raw else ""
        camera = slugify(camera_raw) if camera_raw else ""
        misc = [slugify(t) for t in re.split(r"\s+", misc_raw) if slugify(t)]

        # Build tags dict, omitting empties
        tags: Dict[str, List[str]] = {}
        if medium:
            tags["medium"] = [medium]
        if color:
            tags["color"] = [color]
        if event:
            tags["event"] = [event]
        if camera:
            tags["camera"] = [camera]
        if misc:
            tags["misc"] = misc

        # Photo entry: include richer EXIF (already present in it.exif)
        entry = {
            "id": it.id,
            "source": {
                "originalFilename": it.original_filename,
                "fingerprint": it.source_fingerprint,
            },
            "paths": {
                "thumb": it.thumb_rel.replace("\\", "/"),
                "display": it.display_rel.replace("\\", "/"),
                "original": None,
            },
            "exif": it.exif,
            "meta": {"title": None, "caption": None, "location": None},
            "tags": tags,
        }

        # Append/replace
        photos = photos_json.get("photos", [])
        replaced = False
        for i, ph in enumerate(photos):
            if ph.get("id") == it.id:
                photos[i] = entry
                replaced = True
                break
        if not replaced:
            photos.append(entry)
        photos_json["photos"] = photos
        save_json(photos_json_path, photos_json)

        # Update prev_tags memory for "copy previous"
        prev_tags = {
            "ok": True,
            "medium": medium,
            "color": color,
            "event": event,
            "camera": camera,
            "misc": misc,
        }

        return jsonify({"ok": True})

    @app.get("/done")
    def done():
        return render_template_string(DONE_TEMPLATE)

    return app

def backfill_exif_from_originals(photos_json: Dict[str, Any], originals_dir: Path) -> int:
    """
    Update exif fields for existing entries by matching originalFilename in originals_dir.
    Does NOT change tags or paths.
    Returns number of entries updated.
    """
    originals_index: Dict[str, Path] = {}
    for p in originals_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
            originals_index[p.name] = p  # assumes filenames unique; good enough for v1

    updated = 0
    photos = photos_json.get("photos", [])
    for ph in photos:
        src = ph.get("source", {})
        name = src.get("originalFilename")
        if not name:
            continue

        orig_path = originals_index.get(name)
        if not orig_path:
            continue  # can't find original; skip

        try:
            img = safe_open_image(orig_path)
            exif_fields = get_exif_fields(img)
        except Exception:
            continue

        old_exif = ph.get("exif", {}) or {}
        # Only overwrite/add EXIF keys we know about (safe)
        merged = dict(old_exif)
        for k, v in exif_fields.items():
            merged[k] = v
        ph["exif"] = merged
        updated += 1

    return updated

# ----------------------------
# Main ingest logic
# ----------------------------
def scan_originals(originals_dir: Path) -> List[Path]:
    paths = []
    for p in originals_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
            paths.append(p)
    paths.sort()
    return paths


def generate_derivatives(
    repo_root: Path,
    original_path: Path,
    photo_id: str,
    thumb_long_edge: int,
    display_long_edge: int,
) -> Tuple[str, str, Dict[str, Optional[str]]]:
    img = safe_open_image(original_path)
    exif_fields = get_exif_fields(img)

    display_img = resize_long_edge(img, display_long_edge)
    thumb_img = resize_long_edge(img, thumb_long_edge)

    thumb_rel = (THUMBS_REL / f"{photo_id}.jpg").as_posix()
    display_rel = (DISPLAY_REL / f"{photo_id}.jpg").as_posix()

    to_jpeg(thumb_img, repo_root / thumb_rel, quality=78)
    to_jpeg(display_img, repo_root / display_rel, quality=86)

    return thumb_rel, display_rel, exif_fields


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--originals", required=True, help="Path to folder containing original images")
    parser.add_argument("--repo-root", default=".", help="Path to repo root (default: .)")
    parser.add_argument("--thumb-long-edge", type=int, default=DEFAULT_THUMB_LONG_EDGE)
    parser.add_argument("--display-long-edge", type=int, default=DEFAULT_DISPLAY_LONG_EDGE)
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--backfill-exif", action="store_true", help="Update EXIF fields for existing photos.json entries without retagging")
    args = parser.parse_args()

    originals_dir = Path(args.originals).expanduser().resolve()
    repo_root = Path(args.repo_root).expanduser().resolve()
    ensure_dirs(repo_root)

    photos_json_path = repo_root / DATA_REL
    photos_json = load_json(photos_json_path)

    if args.backfill_exif:
        if not originals_dir.exists():
            print(f"Originals dir not found: {originals_dir}")
            sys.exit(1)

        n = backfill_exif_from_originals(photos_json, originals_dir)
        save_json(photos_json_path, photos_json)
        print(f"Backfilled EXIF for {n} photo(s).")
        sys.exit(0)

    existing_fps = build_existing_fingerprints(photos_json)
    existing_ids = {ph.get("id") for ph in photos_json.get("photos", []) if ph.get("id")}

    originals = scan_originals(originals_dir)
    if not originals:
        print(f"No images found in {originals_dir}")
        sys.exit(0)

    pending: List[PendingItem] = []
    new_count = 0

    for orig in originals:
        fp = fingerprint_for_file(orig)
        if fp in existing_fps:
            continue

        # get tentative exif for ID generation
        try:
            img = safe_open_image(orig)
            exif_for_id = get_exif_fields(img)
        except Exception:
            exif_for_id = {"dateTaken": None, "cameraMake": None, "cameraModel": None, "lensModel": None,
                           "exposureTime": None, "fNumber": None, "iso": None, "focalLength": None}

        candidate_id = make_id(exif_for_id.get("dateTaken"), orig.name)
        photo_id = uniquify_id(candidate_id, existing_ids)
        existing_ids.add(photo_id)

        try:
            thumb_rel, display_rel, exif_fields = generate_derivatives(
                repo_root, orig, photo_id, args.thumb_long_edge, args.display_long_edge
            )
        except Exception as e:
            print(f"Failed processing {orig}: {e}")
            continue

        pending.append(
            PendingItem(
                id=photo_id,
                original_path=orig,
                display_rel=display_rel,
                thumb_rel=thumb_rel,
                exif=exif_fields,
                source_fingerprint=fp,
                original_filename=orig.name,
            )
        )
        new_count += 1

    if new_count == 0:
        print("No new photos detected (everything already in photos.json).")
        sys.exit(0)

    print(f"Prepared {new_count} new photo(s). Launching local tagger at http://{args.host}:{args.port}")

    app = create_app(pending=pending, repo_root=repo_root, photos_json_path=photos_json_path, photos_json=photos_json)

    try:
        import webbrowser
        webbrowser.open(f"http://{args.host}:{args.port}")
    except Exception:
        pass

    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()