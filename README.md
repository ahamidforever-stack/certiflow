# CertiFlow

Certified translation platform: source document → agent pipeline → human approval → signed and stamped Word +
one integrated PDF (translation pages, then the stamped source pages).

Status: **Phase 3 (web app)**. See `docs/ARCHITECTURE.md` and `docs/PROMPT_VERSIONING.md`.

## Setup

```bash
pip install -e .[dev]
# system: LibreOffice, poppler-utils, tesseract + language packs, fonts (Amiri, Noto, Liberation) - see requirements-system.txt
```

## Web app

```bash
pip install -e ".[web,dev]" && (cd web && npm ci && npm run build)
certiflow web init-db
certiflow web create-user amir.gomaa --role certified_translator --name "Amir Gomaa"   # prompts for a password
CERTIFLOW_LIBRARY=assets/shoreline/library.json certiflow web serve --port 8000
```

Open http://localhost:8000. Development defaults: SQLite in `data/` and an in-process job runner.

**Production:** `docker compose up -d --build` runs PostgreSQL, Redis, the API and Celery workers. It uses the
PostgreSQL LangGraph checkpointer. See `docker-compose.yml` and `.env.example`; office assets are mounted from `./office`.

The screens are: sign-in, the jobs list, new job, and the job page.
- **New job:** drag-and-drop upload, language pair with swap and recent pairs, a per-document language override, and
  the stamp selector with stamp images. It is required and has no default.
- **Job page:** live progress over server-sent events, the glossary confirmation, a review preview, approval by the
  signing certified translator, downloads, and cost per step.

The interface is in English and Arabic, with full right-to-left layout.

## Translate (agent pipeline)

```bash
export CERTIFLOW_ANTHROPIC_API_KEY=...  # server environment only (ANTHROPIC_API_KEY also works); never in code or the browser
certiflow translate source.pdf --from en --to ar --stamp certified --user amir.gomaa \
  --library assets/shoreline/library.json --job-dir jobs/J001
certiflow job confirm-glossary jobs/J001 --by amir.gomaa [--file edited_glossary.json]
#   review jobs/J001/docs/d01.formatted.json (Phase 4 adds the side-by-side editor)
certiflow job approve jobs/J001 --by amir.gomaa
certiflow job status jobs/J001          # stages, open flags, cost per agent
```

The pipeline runs Intake (OCR plus a vision check), then the Glossary step, where it pauses for a person to confirm.
It then runs Translator, Proofreader and QA (blockers loop back to the Translator, at most twice), then the Formatter,
and pauses again for the final review. Only after approval by a certified translator does the Builder apply the stamp
and signature. A crashed job resumes where it stopped: `certiflow job resume jobs/J001`. Add `--mock` to any command to run
offline with pseudo-translations (for testing only).

Models, effort and prompt versions per agent are in `config/agents.json`. Every call is logged to `jobs/<id>/audit.jsonl`
with the model, prompt version, tokens, cache hits, cost, latency and retries.

Score the pipeline against approved translations:

```bash
certiflow golden score inputs/golden_set --library assets/shoreline/library.json --user amir.gomaa
```

## Office setup (real template, stamps, signature)

```bash
certiflow setup-office --template inputs/shoreline_template.docx \
  --signature inputs/raw/template_signature.png --certified-stamp inputs/raw/template_stamp_certified.png \
  --office-stamp inputs/raw/stamp_office.jpg \
  --translator-id amir.gomaa --translator-name "Amir Gomaa" --out assets/shoreline
```

This removes the paper background from the scans (transparent PNG, ink colour kept, specks and scanner lines dropped).
It also finds the signature and stamp already placed in the template's footer, measures their position, and records it.
On build, those baked-in images are removed. The job's chosen stamp and the translator's signature are then placed at that
position on every page (odd and even), never above the bottom margin. `inputs/` and `assets/` are git-ignored.

## Licensed fonts (PDF)

LibreOffice can only use fonts installed on the server. Put the office's licensed font files in `assets/fonts/`
(git-ignored) and run:

```bash
certiflow fonts install assets/fonts   # e.g. majalla.ttf, majallab.ttf
certiflow fonts status                 # which PDF font each language actually uses
```

Arabic PDFs use Sakkal Majalla when it is installed and fall back to Amiri when it is not. Word files always name
Sakkal Majalla.

## Golden set (regression)

```bash
certiflow golden run inputs/golden_set --library assets/shoreline/library.json --user amir.gomaa
```

Layout: `<src>-<tgt>/<case>/approved.docx` plus an optional `approved.pdf` (the source pages are extracted from it).
Each case is imported into the model, rebuilt, and compared element by element. Translation page counts are compared too.

## Try it

```bash
certiflow samples samples                    # placeholder template, stamps, signature, source scans
certiflow build samples/models/en_ar_good_standing.json \
  --source samples/sources/en_good_standing.pdf \
  --stamp certified --user translator1 \
  --library samples/assets/library.json --out out/en_ar
certiflow build samples/models/ar_en_good_conduct.json \
  --source samples/sources/ar_good_conduct.pdf \
  --stamp office --user translator1 --order interleaved \
  --library samples/assets/library.json --out out/ar_en
certiflow profiles                           # list language profiles
certiflow schema docs/document.schema.json   # JSON Schema of the document model
```

`--stamp` is required and has no default. The build refuses to start without it, and refuses a stamp the user is not
authorised to apply.

Output: `NN_Title_<LANG>.docx`, `NN_Title_<LANG>.pdf`, `disclosures.txt` (and a zip for batches:
`certiflow batch job.json`).

## Tests

```bash
pytest -q
```

Covers: the model and job validation, stamp authorisation, profiles, and the builder across the pair matrix
(en>ar, ar>en, fr>en, en>de, es>ar, ru>en) for direction, fonts, proofing language, bidi isolation, numbering, tables and
footer seals. End to end, it checks page counts, the release verification (and that it blocks an unstamped page), identical
seal size on every page, no text under the seal, interleaved order, the 24-page/12 MB budget, least-ink placement and
the zip layout.

## Adding a language

Add `certiflow/profiles/data/<code>.json` (copy an existing profile), install its fonts and tesseract pack. No code change.
