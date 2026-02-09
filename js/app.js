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

  if (filterMode === "AND") {
    return arr.filter(p => hasAllTags(p, tags));
  }
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

function rebuildView() {
  page = 1;
  const filtered = applyFilter(allPhotos);
  viewPhotos = sortPhotos(filtered, sortSelect.value);
  updateTagSummary();
  render();
}

function updateTagSummary() {
  if (selectedTags.size === 0) {
    tagSummaryEl.textContent = "Select tags…";
    return;
  }
  const tags = Array.from(selectedTags);
  tagSummaryEl.textContent = `${tags.length} tag(s): ${tags.slice(0, 3).join(", ")}${tags.length > 3 ? "…" : ""}`;
}

function render() {
  const total = viewPhotos.length;
  const showing = Math.min(total, page * PAGE_SIZE);

  statusEl.textContent = total === 0
    ? "No photos match your filter."
    : `Showing ${showing} of ${total}`;

  gridEl.innerHTML = "";

  const slice = viewPhotos.slice(0, showing);
  for (let i = 0; i < slice.length; i++) {
    const p = slice[i];
    const tile = document.createElement("div");
    tile.className = "tile";
    tile.dataset.index = String(i);

    const img = document.createElement("img");
    img.loading = "lazy";
    img.src = p.paths.thumb;
    img.alt = p.meta?.title ?? "";

    tile.appendChild(img);
    tile.addEventListener("click", () => openLightbox(i));

    gridEl.appendChild(tile);
  }

  loadMoreBtn.style.display = showing < total ? "inline-flex" : "none";
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
  const tags = tagIndex?.tags || [];

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
    count.textContent = String(t.count ?? "");

    row.appendChild(lab);
    row.appendChild(count);
    tagListEl.appendChild(row);
  }
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

    // If tags.json missing, derive from photos.json (fallback)
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

    buildTagUI(tagIndex);

    // events
    sortSelect.addEventListener("change", rebuildView);

    clearTagsBtn.addEventListener("click", () => {
      selectedTags.clear();
      // uncheck all
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
    });

    lbClose.addEventListener("click", closeLightbox);
    lbPrev.addEventListener("click", () => lbStep(-1));
    lbNext.addEventListener("click", () => lbStep(1));

    lightbox.addEventListener("click", (e) => {
      if (e.target === lightbox) closeLightbox();
    });
    document.addEventListener("keydown", onKey);

    // Make lbMeta render newlines
    lbMeta.style.whiteSpace = "pre-line";

    rebuildView();
  } catch (err) {
    statusEl.textContent = "Failed to load gallery data.";
    console.error(err);
  }
}

init();