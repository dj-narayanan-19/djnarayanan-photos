const PHOTOS_URL = "data/photos.json";
const TAGS_URL = "data/tags.json";

const gridEl = document.getElementById("grid");
const statusEl = document.getElementById("status");
const sortSelect = document.getElementById("sortSelect");
const loadMoreBtn = document.getElementById("loadMoreBtn");

// Sidebar / drawer
const sidebarEl = document.getElementById("sidebar");
const tagMenuEl = document.getElementById("tagMenu");
const clearTagsBtn = document.getElementById("clearTagsBtn");
const menuBtn = document.getElementById("menuBtn");
const drawerBackdrop = document.getElementById("drawerBackdrop");

// AND/OR
const modeAndBtn = document.getElementById("modeAnd");
const modeOrBtn = document.getElementById("modeOr");
let filterMode = "AND"; // OR
let selectedTags = new Set(); // multi-select

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
const PAGE_SIZE = 30; // fewer per page since display images are heavier
let page = 1;

// data
let allPhotos = [];
let viewPhotos = [];
let lbIndex = -1;
let renderedCount = 0;

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

function rebuildView({ preservePage = false } = {}) {
  if (!preservePage) page = 1;

  const filtered = applyFilter(allPhotos);
  viewPhotos = sortPhotos(filtered, sortSelect.value);

  renderedCount = 0;
  gridEl.innerHTML = "";

  render();

  if (!isInitializing) setUrlState();
  syncTagMenuUI();
}

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
    tile.className = "tile";
    tile.dataset.index = String(i);

    const img = document.createElement("img");
    img.loading = "lazy";

    // ✅ use display images for crispness
    img.src = p.paths.display;

    img.alt = p.meta?.title ?? "";

    tile.appendChild(img);
    tile.addEventListener("click", () => openLightbox(i));
    gridEl.appendChild(tile);
  }

  renderedCount = target;
  loadMoreBtn.style.display = renderedCount < total ? "inline-flex" : "none";
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

function isMobileLike() {
  return window.matchMedia && window.matchMedia("(max-width: 700px)").matches;
}

/* Swipe support (lightbox) */
let swipeStartX = 0;
let swipeStartY = 0;
let swipeActive = false;

function onLbTouchStart(e) {
  if (!e.touches || e.touches.length !== 1) return;
  const t = e.touches[0];
  swipeStartX = t.clientX;
  swipeStartY = t.clientY;
  swipeActive = true;
}

function onLbTouchMove(e) {
  if (!swipeActive || !e.touches || e.touches.length !== 1) return;
  const t = e.touches[0];
  const dx = Math.abs(t.clientX - swipeStartX);
  const dy = Math.abs(t.clientY - swipeStartY);
  if (dx > dy && dx > 10) e.preventDefault();
}

function onLbTouchEnd(e) {
  if (!swipeActive) return;
  swipeActive = false;

  const changed = e.changedTouches && e.changedTouches[0];
  if (!changed) return;

  const dx = changed.clientX - swipeStartX;
  const dy = changed.clientY - swipeStartY;

  if (Math.abs(dx) < 50 || Math.abs(dx) < Math.abs(dy)) return;

  if (dx < 0) lbStep(1);
  else lbStep(-1);
}

function onKey(e) {
  if (lightbox.classList.contains("hidden")) return;
  if (e.key === "Escape") closeLightbox();
  if (e.key === "ArrowLeft") lbStep(-1);
  if (e.key === "ArrowRight") lbStep(1);
}

/* Tag menu (multi-select) */
function buildTagMenu(tagIndex) {
  tagMenuEl.innerHTML = "";

  const tags = (tagIndex?.tags || [])
    .slice()
    .sort((a, b) => (b.count ?? 0) - (a.count ?? 0) || String(a.name).localeCompare(String(b.name)));

  for (const t of tags) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "tagitem";
    btn.dataset.tag = t.name;

    const left = document.createElement("span");
    left.textContent = t.name;

    const right = document.createElement("span");
    right.className = "tagcount";
    right.textContent = String(t.count ?? 0);

    btn.appendChild(left);
    btn.appendChild(right);

    btn.addEventListener("click", () => {
      if (selectedTags.has(t.name)) selectedTags.delete(t.name);
      else selectedTags.add(t.name);

      rebuildView();
    });

    tagMenuEl.appendChild(btn);
  }

  syncTagMenuUI();
}

function syncTagMenuUI() {
  tagMenuEl.querySelectorAll(".tagitem").forEach(el => {
    const tag = el.dataset.tag;
    el.classList.toggle("active", selectedTags.has(tag));
  });
}

/* URL state: ?tags=a,b&mode=AND&sort=...&page=... */
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

/* Infinite scroll */
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
    { root: null, rootMargin: "1200px 0px", threshold: 0.01 }
  );

  observer.observe(sentinelEl);
}

/* Mobile drawer */
function isDrawerMobile() {
  return window.matchMedia && window.matchMedia("(max-width: 860px)").matches;
}

function openDrawer() {
  sidebarEl.classList.add("open");
  drawerBackdrop.classList.remove("hidden");
  drawerBackdrop.setAttribute("aria-hidden", "false");
  menuBtn?.setAttribute("aria-expanded", "true");
}

function closeDrawer() {
  sidebarEl.classList.remove("open");
  drawerBackdrop.classList.add("hidden");
  drawerBackdrop.setAttribute("aria-hidden", "true");
  menuBtn?.setAttribute("aria-expanded", "false");
}

function toggleDrawer() {
  if (sidebarEl.classList.contains("open")) closeDrawer();
  else openDrawer();
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
    buildTagMenu(tagIndex);

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
    syncTagMenuUI();

    page = urlState.page;

    ensureInfiniteScroll();

    sortSelect.addEventListener("change", () => rebuildView());

    clearTagsBtn.addEventListener("click", () => {
      selectedTags.clear();
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

    // drawer events
    menuBtn?.addEventListener("click", toggleDrawer);
    drawerBackdrop.addEventListener("click", closeDrawer);

    // lightbox events
    lbClose.addEventListener("click", closeLightbox);
    lbPrev.addEventListener("click", () => lbStep(-1));
    lbNext.addEventListener("click", () => lbStep(1));

    // Swipe support on mobile
    lightbox.addEventListener("touchstart", onLbTouchStart, { passive: true });
    lightbox.addEventListener("touchmove", onLbTouchMove, { passive: false });
    lightbox.addEventListener("touchend", onLbTouchEnd, { passive: true });

    // backdrop closes + tap zones navigate
    lightbox.addEventListener("click", (e) => {
      if (lightbox.classList.contains("hidden")) return;

      if (e.target === lightbox) {
        closeLightbox();
        return;
      }

      if (!isMobileLike()) return;

      const el = e.target;
      if (el.closest && (el.closest(".lb-close") || el.closest(".lb-meta"))) return;

      const center = document.querySelector(".lb-center");
      if (!center || !center.contains(el)) return;

      const x = e.clientX;
      const w = window.innerWidth;

      if (x < w * 0.35) lbStep(-1);
      else if (x > w * 0.65) lbStep(1);
    });

    document.addEventListener("keydown", onKey);

    isInitializing = false;
    rebuildView({ preservePage: true });
    setUrlState();
  } catch (err) {
    statusEl.textContent = "Failed to load gallery data.";
    console.error(err);
  }
}

init();