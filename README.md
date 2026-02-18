# Photography Gallery Repo

This repo contains a static photo gallery (HTML/CSS/JS) plus a local **ingest + tagger** tool (Python/Flask) that:
- scans a folder of original images,
- generates derivatives into `assets/`,
- updates `data/photos.json` and `data/tags.json`,
- (optionally) launches a local tagging UI.

The instructions below assume:
- You have already **cloned** the repo.
- Your **original images folder** sits **next to** the repo folder (same parent directory), e.g.

```
ParentFolder/
  my-photo-site-repo/
  originals/
    IMG_0001.jpg
    ...
```

---

## Folder structure

Key paths in this repo:

```
my-photo-site-repo/
  index.html
  gallery.html
  css/
    styles.css
  js/
    app.js
  data/
    photos.json      # main photo database
    tags.json        # derived tag index (counts)
  assets/
    thumbs/          # small derivatives (fast to load)
    display/         # larger derivatives (lightbox + grid if you choose)
  tools/
    ingest.py        # ingest + tagging UI + validation
```

Notes:
- `data/tags.json` is derived from `data/photos.json` (counts), so it can be regenerated.
- Your **full originals** live outside the repo; the site uses the derivatives in `assets/`.

---

## Set up the virtual environment

From the repo root:

```bash
# 1) go to the repo root
cd my-photo-site-repo

# 2) create a venv (first time only)
python3 -m venv .venv

# 3) activate it
source .venv/bin/activate

# 4) upgrade pip
python -m pip install --upgrade pip

# 5) install dependencies
# If your repo includes requirements.txt, prefer that:
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
else
  # minimal deps for tools/ingest.py
  pip install Flask Pillow
fi
```

To leave the venv later:
```bash
deactivate
```

---

## Run ingest with a clean reset (`--reset`)

Use `--reset` when you want a **clean slate** (e.g., assets/derivatives and metadata rebuilt from originals).

From the repo root with the venv active:

```bash
# originals folder is next to the repo
python3 tools/ingest.py --originals ../originals --repo-root . --reset
```

What `--reset` should do (by design):
- clears generated derivatives (`assets/thumbs`, `assets/display`)
- clears / rebuilds photo metadata store (`data/photos.json`, `data/tags.json`)
- then runs ingest normally and launches the local tagger UI (unless you also pass `--no-tag`)

When the tool launches the tagger UI, open the URL printed in the terminal (typically `http://127.0.0.1:5050`).

After tagging:
```bash
git add data/photos.json data/tags.json assets/thumbs assets/display
git commit -m "Add new photos"
git push
```

---

## Further documentation on other ingest methods

### 1) Normal ingest (no reset)
Adds only new photos (detected by stable identity), then launches the tagger UI:

```bash
python3 tools/ingest.py --originals ../originals --repo-root .
```

### 2) Backfill / rebuild derivatives without tagging (`--no-tag`)
Use this when you want to:
- fill missing metadata,
- (re)generate missing derivatives,
- update `data/tags.json`,
without opening the UI.

```bash
python3 tools/ingest.py --originals ../originals --repo-root . --no-tag
```

### 3) Validation-only mindset
The ingest tool also includes validation utilities (run via the UI “Validate & Exit” button) to check:
- missing derivative files
- duplicate IDs
- tag format issues
- orphan files in `assets/`

If you’re debugging a broken state, run:
- `--no-tag` to backfill/repair
- or `--reset` to rebuild everything from scratch

---

## Set up GitHub Pages from this repo

Follow GitHub’s official documentation for configuring a publishing source for GitHub Pages. citeturn5view0

Common setup for a static site:
1. Go to your repo on GitHub → **Settings** → **Pages**
2. Under **Build and deployment**, choose **Deploy from a branch**
3. Select your branch (often `main`) and folder (`/(root)`), then **Save** citeturn5view0

If you later add a custom build step, GitHub Pages can also be deployed via **GitHub Actions**. citeturn5view0
