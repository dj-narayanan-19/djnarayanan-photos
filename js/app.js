const PHOTOS_URL = "data/photos.json";
const TAGS_URL = "data/tags.json";

const gridEl = document.getElementById("grid");
const statusEl = document.getElementById("status");
const sortSelect = document.getElementById("sortSelect");
const loadMoreBtn = document.getElementById("loadMoreBtn");

// Filter UI
const tagListEl = document.getElementById("tagList");
const tagSummaryEl = document.getElementById("tagSummary");
const clearTagsBtn = document.getElementById("clearTagsBtn");
const modeAndBtn = document.getElementById("modeAnd");
const modeOrBtn = document.getElementById("modeOr");

let filterMode = "AND"; // OR
let selectedTags = new Set();
let tagCounts = new Map();
let sentinelEl = null;
let observer = null;
let isInitializing = true;

// Lightbox
const lightbox = document.getElementById("lightbox");
const lbImg = document.getElementById("lbImg");
const lbMeta = document.getElementById("lbMeta");
const lbClose = document.getElementById("lbClose");
const lbPrev = document.getElementById("lbPrev");
const lbNext = document.getElementById("lbNext");

// pagination
const PAGE_SIZE = 60;
let page = 1;

// data
let allPhotos = [];
let viewPhotos = [];
let lbIndex = -1;

function parseDateTaken(p) {
  const dt = p?.exif?.dateTaken;
  if (!dt) return null;
  const t = Date.parse(dt);
  return Number.isNaN(t) ? null : t;
}

function formatDateReadable(dtStr) {
  if (!dtStr) return null;
  const t = Date.parse(dtStr);
  if (Number.isNaN(t)) return dtStr;
  return new Date(t).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "2-digit",
    hour: "2-digit", minute: "2-digit"
  });
}

function hasAllTags(photo, tags) {
  const pt = new Set(photo?.tags || []);
  for (const t of tags) if (!pt.has(t)) return false;
  return true;
}

function hasAnyTag(photo, tags) {
  const pt = new Set(photo?.tags || []);
  for (const t of tags) if (pt.has(t)) return true;
  return false;
}

function applyFilter(arr) {
  const tags = Array.from(selectedTags);
  if (tags.length === 0) return arr;
  if (filterMode === "AND") return arr.filter(p => hasAllTags(p, tags));
  return arr.filter(p => hasAnyTag(p, tags));
}

function sortPhotos(arr, mode) {
  const copy = [...arr];
  if (mode === "random") {
    for (let i = copy.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [copy[i], copy[j]] = [copy[j], copy[i]];
    }
    return copy;
  }

  copy.sort((a, b) => {
    const ta = parseDateTaken(a) ?? 0;
    const tb = parseDateTaken(b) ?? 0;
    return mode === "date_asc" ? (ta - tb) : (tb - ta);
  });
  return copy;
}

function updateTagSummary() {
  if (selectedTags.size === 0) {
    tagSummaryEl.textContent = "Select tags…";
    return;
  }
  const tags = Array.from(selectedTags);
  const formatted = tags.map(t => `${t} (${tagCounts.get(t) ?? 0})`);
  tagSummaryEl.textContent =
    `${tags.length} tag(s): ${formatted.slice(0, 3).join(", ")}${tags.length > 3 ? "…" : ""}`;
}

function getUrlState() {
  const sp = new URLSearchParams(window.location.search);
  const tagsRaw = sp.get("tags") || "";
  const tags = tagsRaw.split(",").map(t => t.trim()).filter(Boolean);
  const mode = (sp.get("mode") || "AND").toUpperCase() === "OR" ? "OR" : "AND";
  const sort = sp.get("sort") || "date_desc";
  const pageParam = parseInt(sp.get("page") || "1", 10);
  const p = Number.isFinite(pageParam) && pageParam > 0 ? pageParam : 1;
  return { tags, mode, sort, page: p };
}

function setUrlState() {
  const sp = new URLSearchParams(window.location.search);
  const tagsArr = Array.from(selectedTags);
  if (tagsArr.length) sp.set("tags", tagsArr.join(","));
  else sp.delete("tags");
  sp.set("mode", filterMode);
  sp.set("sort", sortSelect.value);
  sp.set("page", String(page));
  history.replaceState(null, "", `${window.location.pathname}?${sp.toString()}`);
}

/* -------------------------------------------------------
   Collage packer (Skyline/bin-packing style)
   - No rows/columns; keeps order; equal prominence via area
   ------------------------------------------------------- */

let layoutRaf = 0;

function cssVarPx(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  if (!v) return fallback;
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : fallback;
}

function clamp(x, a, b) {
  return Math.max(a, Math.min(b, x));
}

function scheduleLayout() {
  if (layoutRaf) return;
  layoutRaf = requestAnimationFrame(() => {
    layoutRaf = 0;
    layoutCollagePacked();
  });
}

function layoutCollagePacked() {
  const tiles = Array.from(gridEl.querySelectorAll(".ctile"));
  if (!tiles.length) {
    gridEl.style.height = "0px";
    return;
  }

  const gap = cssVarPx("--gap", 8);
  const area = cssVarPx("--tileArea", 92000);
  const minW = cssVarPx("--minTileW", 220);
  const maxW = cssVarPx("--maxTileW", 560);
  const minH = cssVarPx("--minTileH", 190);
  const maxH = cssVarPx("--maxTileH", 520);

  const cw = gridEl.clientWidth;
  if (!cw || cw < 200) return;

  // Skyline nodes: each node is { x, y, w }
  // Interpretation: from x..x+w, the skyline height is y
  let skyline = [{ x: 0, y: 0, w: cw }];

  function mergeSkyline(nodes) {
    // merge adjacent nodes with same y
    const out = [];
    for (const n of nodes) {
      if (!out.length) out.push({ ...n });
      else {
        const last = out[out.length - 1];
        if (Math.abs(last.y - n.y) < 0.5 && Math.abs(last.x + last.w - n.x) < 0.5) {
          last.w += n.w;
        } else {
          out.push({ ...n });
        }
      }
    }
    return out;
  }

  function findPosition(w, h) {
    // Find the position (x,y) with minimal y where rect fits.
    // We scan skyline nodes as candidate x positions.
    let best = null;

    for (let i = 0; i < skyline.length; i++) {
      const start = skyline[i].x;
      if (start + w > cw) continue;

      // compute y at this start by scanning segments covering [start, start+w)
      let x = start;
      let y = 0;
      let remaining = w;
      let j = i;

      y = skyline[i].y;

      while (remaining > 0 && j < skyline.length) {
        const seg = skyline[j];
        if (seg.x > x + 0.5) break; // gap in skyline coverage (shouldn't happen)
        y = Math.max(y, seg.y);
        const consume = Math.min(remaining, seg.x + seg.w - x);
        x += consume;
        remaining -= consume;
        j += 1;
      }

      if (remaining > 0) continue; // didn't cover width

      // Candidate position
      const cand = { x: start, y };

      if (!best) best = cand;
      else {
        if (cand.y < best.y - 0.5) best = cand;
        else if (Math.abs(cand.y - best.y) < 0.5 && cand.x < best.x) best = cand;
      }
    }

    return best;
  }

  function addRect(x, y, w, h) {
    // Insert a skyline segment at (x, y+h) of width w, removing overlaps.
    const newY = y + h;

    const out = [];
    for (const seg of skyline) {
      const segEnd = seg.x + seg.w;
      const rectEnd = x + w;

      // No overlap
      if (segEnd <= x || seg.x >= rectEnd) {
        out.push(seg);
        continue;
      }

      // Left remainder
      if (seg.x < x) {
        out.push({ x: seg.x, y: seg.y, w: x - seg.x });
      }

      // Right remainder
      if (segEnd > rectEnd) {
        out.push({ x: rectEnd, y: seg.y, w: segEnd - rectEnd });
      }
    }

    // Add the new segment
    out.push({ x, y: newY, w });

    // Sort by x and merge
    out.sort((a, b) => a.x - b.x);
    skyline = mergeSkyline(out);
  }

  let maxBottom = 0;

  for (const tile of tiles) {
    // Aspect ratio from loaded image (w/h). If unknown, assume 3:2
    let ar = parseFloat(tile.dataset.ar || "1.5");
    if (!Number.isFinite(ar) || ar <= 0.05) ar = 1.5;

    // Equal prominence: constant area => w*h ≈ area, with ar = w/h
    // => w = sqrt(area * ar), h = w/ar
    let w = Math.sqrt(area * ar);
    let h = w / ar;

    // Clamp sizes to keep things sane
    w = clamp(w, minW, maxW);
    h = clamp(h, minH, maxH);

    // Add gap padding by inflating rectangle during packing,
    // but render actual tile at (w,h) and leave gap to the right/bottom.
    const packW = Math.min(w + gap, cw);
    const packH = h + gap;

    const pos = findPosition(packW, packH) || { x: 0, y: maxBottom };

    // Apply actual tile position (no need to add gap on left/top; we pack with extra)
    tile.style.left = `${pos.x}px`;
    tile.style.top = `${pos.y}px`;
    tile.style.width = `${w}px`;
    tile.style.height = `${h}px`;

    addRect(pos.x, pos.y, packW, packH);
    maxBottom = Math.max(maxBottom, pos.y + packH);
  }

  gridEl.style.height = `${Math.ceil(maxBottom)}px`;
}

/* ------------------------------------------------------- */

let renderedCount = 0;

function render() {
  const total = viewPhotos.length;
  const target = Math.min(total, page * PAGE_SIZE);

  statusEl.textContent = total === 0
    ? "No photos match your filter."
    : `Showing ${target} of ${total}`;

  if (renderedCount > target) {
    renderedCount = 0;
    gridEl.innerHTML = "";
  }

  for (let i = renderedCount; i < target; i++) {
    const p = viewPhotos[i];

    const tile = document.createElement("div");
    tile.className = "ctile";
    tile.dataset.index = String(i);
    tile.dataset.ar = "1.5"; // placeholder until thumb loads

    const img = document.createElement("img");
    img.loading = "lazy";
    img.src = p.paths.thumb;
    img.alt = p.meta?.title ?? "";

    img.addEventListener("load", () => {
      if (img.naturalWidth && img.naturalHeight) {
        tile.dataset.ar = String(img.naturalWidth / img.naturalHeight);
        scheduleLayout();
      }
    });

    tile.appendChild(img);
    tile.addEventListener("click", () => openLightbox(i));
    gridEl.appendChild(tile);
  }

  renderedCount = target;
  scheduleLayout();

  loadMoreBtn.style.display = renderedCount < total ? "inline-flex" : "none";
}

function rebuildView({ preservePage = false } = {}) {
  if (!preservePage) page = 1;

  const filtered = applyFilter(allPhotos);
  viewPhotos = sortPhotos(filtered, sortSelect.value);

  renderedCount = 0;
  gridEl.innerHTML = "";

  updateTagSummary();
  render();

  if (!isInitializing) setUrlState();
}

function openLightbox(index) {
  lbIndex = index;
  const p = viewPhotos[lbIndex];
  lbImg.src = p.paths.display;

  const date = formatDateReadable(p?.exif?.dateTaken);
  const camera = p?.exif?.cameraModel || p?.exif?.cameraMake;
  const lens = p?.exif?.lensModel;
  const exp = p?.exif?.exposureTime;
  const fno = p?.exif?.fNumber;
  const iso = p?.exif?.iso;
  const fl = p?.exif?.focalLength;

  const lines = [];
  lines.push(`${lbIndex + 1} / ${viewPhotos.length}`);
  if (date) lines.push(`Date: ${date}`);
  if (camera) lines.push(`Camera: ${camera}`);
  if (lens) lines.push(`Lens: ${lens}`);

  const settings = [];
  if (exp) settings.push(`Shutter: ${exp}`);
  if (fno) settings.push(`Aperture: ${fno}`);
  if (iso) settings.push(`ISO: ${iso}`);
  if (fl) settings.push(`Focal: ${fl}`);
  if (settings.length) lines.push(settings.join(" • "));

  const tags = (p?.tags || []).join(", ");
  if (tags) lines.push(`Tags: ${tags}`);

  lbMeta.textContent = lines.join("\n");

  lightbox.classList.remove("hidden");
  lightbox.setAttribute("aria-hidden", "false");
}

function closeLightbox() {
  lightbox.classList.add("hidden");
  lightbox.setAttribute("aria-hidden", "true");
  lbImg.src = "";
  lbIndex = -1;
}

function lbStep(dir) {
  if (lbIndex < 0) return;
  const next = lbIndex + dir;
  if (next < 0 || next >= viewPhotos.length) return;
  openLightbox(next);
}

function onKey(e) {
  if (lightbox.classList.contains("hidden")) return;
  if (e.key === "Escape") closeLightbox();
  if (e.key === "ArrowLeft") lbStep(-1);
  if (e.key === "ArrowRight") lbStep(1);
}

function buildTagUI(tagIndex) {
  tagListEl.innerHTML = "";

  const tags = (tagIndex?.tags || [])
    .slice()
    .sort((a, b) => (b.count ?? 0) - (a.count ?? 0) || String(a.name).localeCompare(String(b.name)));

  for (const t of tags) {
    const row = document.createElement("div");
    row.className = "tagrow";

    const lab = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = t.name;
    cb.checked = selectedTags.has(t.name);
    cb.addEventListener("change", () => {
      if (cb.checked) selectedTags.add(t.name);
      else selectedTags.delete(t.name);
      rebuildView();
    });

    const name = document.createElement("span");
    name.textContent = t.name;

    lab.appendChild(cb);
    lab.appendChild(name);

    const count = document.createElement("span");
    count.className = "tagcount";
    count.textContent = String(t.count ?? 0);

    row.appendChild(lab);
    row.appendChild(count);
    tagListEl.appendChild(row);
  }
}

function ensureInfiniteScroll() {
  if (!sentinelEl) {
    sentinelEl = document.createElement("div");
    sentinelEl.id = "scrollSentinel";
    sentinelEl.style.height = "1px";
    sentinelEl.style.width = "100%";
    sentinelEl.style.margin = "1px 0";
    gridEl.after(sentinelEl);
  }

  if (observer) observer.disconnect();

  observer = new IntersectionObserver(
    (entries) => {
      const e = entries[0];
      if (!e || !e.isIntersecting) return;

      const total = viewPhotos.length;
      const showing = Math.min(total, page * PAGE_SIZE);

      if (showing < total) {
        page += 1;
        render();
        if (!isInitializing) setUrlState();
      }
    },
    { root: null, rootMargin: "800px 0px", threshold: 0.01 }
  );

  observer.observe(sentinelEl);
}

async function init() {
  try {
    const [photosRes, tagsRes] = await Promise.all([
      fetch(PHOTOS_URL, { cache: "no-cache" }),
      fetch(TAGS_URL, { cache: "no-cache" }).catch(() => null),
    ]);

    if (!photosRes.ok) throw new Error(`Failed photos.json: ${photosRes.status}`);
    const photosData = await photosRes.json();
    allPhotos = Array.isArray(photosData.photos) ? photosData.photos : [];

    let tagIndex = null;
    if (tagsRes && tagsRes.ok) {
      tagIndex = await tagsRes.json();
    } else {
      const counts = {};
      for (const p of allPhotos) {
        for (const t of (p.tags || [])) counts[t] = (counts[t] || 0) + 1;
      }
      tagIndex = { tags: Object.keys(counts).sort().map(k => ({ name: k, count: counts[k] })) };
    }

    tagCounts = new Map((tagIndex.tags || []).map(t => [t.name, t.count ?? 0]));
    buildTagUI(tagIndex);

    const urlState = getUrlState();
    if (urlState.sort) sortSelect.value = urlState.sort;

    filterMode = urlState.mode;
    if (filterMode === "AND") {
      modeAndBtn.classList.add("active");
      modeOrBtn.classList.remove("active");
    } else {
      modeOrBtn.classList.add("active");
      modeAndBtn.classList.remove("active");
    }

    selectedTags = new Set(urlState.tags);
    tagListEl.querySelectorAll("input[type=checkbox]").forEach(cb => {
      cb.checked = selectedTags.has(cb.value);
    });

    page = urlState.page;

    updateTagSummary();
    ensureInfiniteScroll();

    sortSelect.addEventListener("change", rebuildView);

    clearTagsBtn.addEventListener("click", () => {
      selectedTags.clear();
      tagListEl.querySelectorAll("input[type=checkbox]").forEach(cb => cb.checked = false);
      rebuildView();
    });

    modeAndBtn.addEventListener("click", () => {
      filterMode = "AND";
      modeAndBtn.classList.add("active");
      modeOrBtn.classList.remove("active");
      rebuildView();
    });

    modeOrBtn.addEventListener("click", () => {
      filterMode = "OR";
      modeOrBtn.classList.add("active");
      modeAndBtn.classList.remove("active");
      rebuildView();
    });

    loadMoreBtn.addEventListener("click", () => {
      page += 1;
      render();
      if (!isInitializing) setUrlState();
    });

    lbClose.addEventListener("click", closeLightbox);
    lbPrev.addEventListener("click", () => lbStep(-1));
    lbNext.addEventListener("click", () => lbStep(1));

    lightbox.addEventListener("click", (e) => {
      if (e.target === lightbox) closeLightbox();
    });
    document.addEventListener("keydown", onKey);

    // Critical for pack layouts
    window.addEventListener("resize", scheduleLayout);

    isInitializing = false;
    rebuildView({ preservePage: true });
    setUrlState();
  } catch (err) {
    statusEl.textContent = "Failed to load gallery data.";
    console.error(err);
  }
}

init();