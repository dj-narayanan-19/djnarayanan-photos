const DATA_URL = "data/photos.json";

const gridEl = document.getElementById("grid");
const statusEl = document.getElementById("status");
const sortSelect = document.getElementById("sortSelect");
const quickFilter = document.getElementById("quickFilter");
const loadMoreBtn = document.getElementById("loadMoreBtn");

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

let allPhotos = [];
let viewPhotos = [];   // filtered + sorted
let lbIndex = -1;

function parseDateTaken(p) {
  // prefer exif.dateTaken, fallback null
  const dt = p?.exif?.dateTaken;
  if (!dt) return null;
  // dt may be "YYYY-MM-DDTHH:MM:SS"
  const t = Date.parse(dt);
  return Number.isNaN(t) ? null : t;
}

function matchesQuickFilter(photo, filterValue) {
  if (!filterValue) return true;
  const [cat, tag] = filterValue.split(":");
  const tags = photo?.tags?.[cat];
  return Array.isArray(tags) && tags.includes(tag);
}

function sortPhotos(arr, mode) {
  const copy = [...arr];
  if (mode === "random") {
    // Fisher–Yates shuffle
    for (let i = copy.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [copy[i], copy[j]] = [copy[j], copy[i]];
    }
    return copy;
  }

  // date sort
  copy.sort((a, b) => {
    const ta = parseDateTaken(a) ?? 0;
    const tb = parseDateTaken(b) ?? 0;
    return mode === "date_asc" ? (ta - tb) : (tb - ta);
  });
  return copy;
}

function rebuildView() {
  page = 1;
  const filterVal = quickFilter.value;
  const filtered = allPhotos.filter(p => matchesQuickFilter(p, filterVal));
  viewPhotos = sortPhotos(filtered, sortSelect.value);
  render();
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
  const dt = p?.exif?.dateTaken ? ` • ${p.exif.dateTaken}` : "";
  const cam = p?.exif?.cameraModel ? ` • ${p.exif.cameraModel}` : "";

  const exp = p?.exif?.exposureTime ? ` • ${p.exif.exposureTime}` : "";
  const fno = p?.exif?.fNumber ? ` • ${p.exif.fNumber}` : "";
  const iso = p?.exif?.iso ? ` • ISO ${p.exif.iso}` : "";
  const fl  = p?.exif?.focalLength ? ` • ${p.exif.focalLength}` : "";
  
  lbMeta.textContent = `${lbIndex + 1} / ${viewPhotos.length}${dt}${cam}${exp}${fno}${iso}${fl}`;
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

async function init() {
  try {
    const res = await fetch(DATA_URL, { cache: "no-cache" });
    if (!res.ok) throw new Error(`Failed to load ${DATA_URL}: ${res.status}`);
    const data = await res.json();
    allPhotos = Array.isArray(data.photos) ? data.photos : [];
    rebuildView();
  } catch (err) {
    statusEl.textContent = "Failed to load photos.json";
    console.error(err);
  }
}

// events
sortSelect?.addEventListener("change", rebuildView);
quickFilter?.addEventListener("change", rebuildView);

loadMoreBtn?.addEventListener("click", () => {
  page += 1;
  render();
});

lbClose?.addEventListener("click", closeLightbox);
lbPrev?.addEventListener("click", () => lbStep(-1));
lbNext?.addEventListener("click", () => lbStep(1));

lightbox?.addEventListener("click", (e) => {
  // click outside image closes
  if (e.target === lightbox) closeLightbox();
});

document.addEventListener("keydown", onKey);

init();