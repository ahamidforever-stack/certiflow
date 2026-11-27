# CertiFlow technical specification

| | |
|---|---|
| Product | CertiFlow: certified translation platform for Shoreline Legal Translation (Dubai) |
| Document | Technical specification and handover, version 1.0 (end of Phase 3) |
| Repository | `github.com/ahamidforever-stack/certiflow` (private) |
| Branches | `main` holds Phases 1 and 2. `claude/phase3-web-app` holds Phase 3 (web app, Docker) and is not merged yet. |
| Requirements | `docs/BRIEF.md` (the original brief, verbatim) |
| Related docs | `README.md`, `docs/DEVELOPER_GUIDE.md`, `docs/ARCHITECTURE.md`, `docs/PROMPT_VERSIONING.md`, `docs/openapi.json`, `docs/document.schema.json` |

---

## 1. Product overview

The office translates official documents (certificates, contracts, medical records, correspondence) and issues
**certified translations**: a Word file and a PDF on the office letterhead, signed and stamped by a certified
translator. Today one person does everything by hand. CertiFlow automates the work with a pipeline of specialised
Claude agents, and keeps a **human certified translator in control of the release**.

**Input:** one or more source documents per job (PDF, scans, photos, Word), a language pair (any pair, per job or per
document), and the stamp to apply (Certified or Office).

**Output per document:**
- `NN_Title_<LANG>.docx`: the translation on the office template, with signature and stamp on every page
- `NN_Title_<LANG>.pdf`: one integrated file, the translation pages followed by the source pages, every page signed
  and stamped at the same size
- `disclosures.txt`: unreadable parts, text hidden under stamps, duplicates translated once, dense pages
- for batches, a zip of everything

**Roles:**

| Role | Can do |
|---|---|
| `certified_translator` | Create jobs, sign with their own signature, apply their own certified stamp and the office stamp, approve releases of jobs they sign |
| `reviewer` | Sign in, view; cannot create jobs or approve (owns no stamp or signature) |
| `admin` | Everything, including approving any job; sees all jobs |

**Lifecycle of a job:**
```
upload ─► Intake (OCR + vision) ─► Glossary ─► [human: confirm glossary]
       ─► Translator ─► Proofreader ─► QA ──blocker──► Translator (fix) ─► … (max 2 loops)
       ─► Formatter ─► [human: final review + approval by certified translator]
       ─► Builder (Word + PDF + seal) ─► verification gate ─► release (downloads)
```

---

## 2. Status: requirements against implementation

Legend: ✅ done and tested · 🟡 partial / different from brief (see notes) · ⬜ not started (planned phase)

| Brief section | Requirement | Status | Notes |
|---|---|---|---|
| 0.1 | Any language pair, nothing hard-coded, 17 languages, LTR and RTL | ✅ | Language Profiles (JSON) + Pair Settings; tested on en>ar, ar>en, fr>en, en>de, es>ar, ru>en |
| 1 | Word on template, seal on every page | ✅ | Seal position learned from the office's approved outputs |
| 1 | One integrated PDF, translation then source, every page sealed | ✅ | Verification gate blocks a release with any unsealed page |
| 1 | Page order option "interleaved" (only when mapping reliable) | ✅ | Falls back to translation-then-source, with a disclosure |
| 1 | Batch: one pair per document + zip | ✅ | |
| 2 | Stamp choice required, no default; rights checked | ✅ | UI, API (422/403) and pipeline |
| 2 | Asset Library (admin-managed) | 🟡 | JSON manifest + `setup-office` command; admin UI is Phase 5 |
| 3 | Agents: Intake, Glossary, Translator, Proofreader, QA, Formatter | ✅ | Prompt quality not yet tuned on real API runs (see §13) |
| 3 | Builder deterministic, never LLM-written XML | ✅ | |
| 3 | Human final review with side-by-side editor | 🟡 | Approval gate works; editor is a read-only preview; the side-by-side editor is Phase 4 |
| 3 | QA loop max 2, then flag for human | ✅ | Unresolved blockers block the release |
| 3 | Chunking with overlap, shared glossary | ✅ | Units of at most 40 blocks or 20 pages, 3 blocks of context, recombined into one document (§5.5) |
| 3 | Glossary confirmed once per batch | ✅ | One glossary per job; per-pair glossaries in mixed batches are open |
| 3.1 | LangGraph with conditional loop + interrupt + Postgres checkpointer | 🟡 | Graph + interrupts + Postgres/SQLite checkpointer ✅. The QA loop and per-document parallelism run inside the `process_all` node (code-level loop, thread pool), not as graph edges |
| 3.1 | Anthropic SDK, structured outputs, validation retry | ✅ | JSON outputs (`output_config.format`), not forced tool use (forced `tool_choice` is rejected by current models) |
| 3.1 | Claude Agent SDK for hard scans | 🟡 | Replaced by a plain "zoom" Messages call on cropped regions (lighter in Celery workers) |
| 3.1 | Langfuse tracing | ⬜ | Own audit log is complete; Langfuse is Phase 5 |
| 3.1 | Prompt caching | ✅ | Whole system prompt is the cached prefix |
| 3.1 | Batch API "bulk, lower cost" | ⬜ | Phase 5 |
| 3.1 | Models per agent from settings | ✅ | `config/agents.json`; no model name in code |
| 3.1 | Streaming, backoff, resumable stages | ✅ | |
| 3.1 | Celery/Redis workers | ✅ | Thread runner for dev/tests |
| 3.1 | Mock client for offline tests | ✅ | `MockClient`, `RecordingClient`, deterministic agent stand-ins |
| 4 | Language-neutral document model with runs | ✅ | Pydantic; JSON Schema in `docs/document.schema.json` |
| 5 | Translation/formatting rules | ✅ | In prompts (`common_rules.v1.md`) and the Builder |
| 5.1 | Language Profiles editable by admins | 🟡 | JSON files; DB + admin UI is Phase 5 |
| 5.1 | Arabic Sakkal Majalla 14 pt | 🟡 | **13 pt**: matched to the office's approved translations |
| 5.2 | Pair Settings | ✅ | `profiles/data/pairs.json` |
| 6 | Builder: RTL, bidi isolation, fonts, proofing language, templates per pair | ✅ | |
| 6 | Source pages: 130 dpi, upright, fitted, sealed, least-ink placement | ✅ | Plus "band" mode (office convention: scan fitted above a seal band, no overlap) |
| 6 | 24-page scan ≤ 12 MB | ✅ | about 2.5 MB in tests |
| 6 | Verification gate | ✅ | |
| 7 | FastAPI, Celery/Redis, PostgreSQL, SQLAlchemy, Alembic | ✅ | |
| 7 | React/TS/Vite/Tailwind, EN/AR with RTL UI | ✅ | |
| 7 | S3/MinIO storage | ⬜ | Shared volume `/data` today (Phase 5) |
| 7 | SSE progress | ✅ | |
| 7 | Docker Compose with LibreOffice, Tesseract packs, fonts | ✅ | Built and run end to end |
| 7 | Screens: new job, pipeline view, release | ✅ | |
| 7 | Screens: side-by-side editor, PDF preview, admin, audit view | ⬜ | Phases 4 and 5 |
| 8 | Encryption at rest, retention/auto-delete, per-client access | ⬜ | Phase 5 (TLS via reverse proxy at deployment) |
| 8 | API key server-side only | ✅ | |
| 8 | Release only after certified approval; open blockers block | ✅ | |
| 9 | Builder tests across the pair matrix, stamp overlap tests | ✅ | 64 tests |
| 9 | Golden set per pair + scoring harness | ✅ | `certiflow golden run|score` |

---

## 3. Architecture

```
            browser (React/TS/Tailwind, EN/AR, RTL)
               │  HttpOnly signed cookie + X-CertiFlow header; SSE
               ▼
        FastAPI  certiflow/web/app.py ──────────► PostgreSQL (users, jobs, documents, events, LangGraph checkpoints)
               │ runner.submit(job, resume)
               ▼
            Redis ──► Celery worker(s)  certiflow/web/tasks.py
                          │ runner.advance()
                          ▼
              pipeline Job (LangGraph)  certiflow/pipeline/job.py
               │  agents (certiflow/agents)  ──► Claude API (Anthropic SDK, structured JSON)
               │  OCR (tesseract), rendering (pdftoppm)
               └► Builder (certiflow/builder): python-docx + OOXML ─► LibreOffice ─► pypdf/reportlab/pdfium
                          │
                   shared volume /data/jobs/<job_id>/ (uploads, stage files, audit.jsonl, release/)
```

**Tech stack:** Python 3.12, Pydantic 2, python-docx, LibreOffice (headless), Poppler, Tesseract 5, reportlab, pypdf,
pypdfium2, OpenCV (image prep), Anthropic SDK, LangGraph (+ SQLite/PostgreSQL checkpointers), FastAPI, SQLAlchemy 2,
Alembic, Celery 5 + Redis, PostgreSQL 16, React 18 + TypeScript + Vite + Tailwind 3. Docker image: Ubuntu 24.04.

**Deliberately not used:**
- **CrewAI, AutoGen, LangChain chains/agents:** forbidden by the brief.
- **PyMuPDF:** its AGPL licence; pypdfium2 is used instead.

---

## 4. Domain model

### 4.1 Document model (`certiflow/model.py`)
Every agent reads and writes this model; the Builder renders it.
- `Document{id, title, source_language, target_language, document_type, pages[PageInfo], glossary[GlossaryEntry], blocks[Block]}`
- `Block{id, type, source_page, source_text, translated_text, runs[InlineRun]?, direction?, status, confidence, flags[Flag], history[HistoryEntry], layout(Layout), level, label, rows[TableRow], column_widths, note_kind, note_scope(inline|page_end|document_end), unreadable_reason, multilingual_duplicate}`
- **Block types:** heading (level 1 = title, 2 = shaded section bar, 3 = sub-heading), paragraph, numbered_item,
  bullet, table, kv_table (label/value pairs, 2/4/6 columns), note (rendered as `//…//`), page_break,
  signature_block, unreadable (illegible | covered_by_stamp | truncated).
- `InlineRun{text, kind(text|identifier|number|date|email|url|name), direction?, bold, italic, color?, size_pt?}`:
  non-text runs are isolated with bidi marks against the paragraph direction.
- `TableCell{source_text, translated_text, runs?, header, colspan, bold, fill?, size_pt?, align?, blocks?}`: `blocks`
  gives rich cell content (paragraphs with their own layout).
- `Layout{align, bold, font_scale, size_pt, keep_with_next, space_before_pt, space_after_pt, indent_level, indent_twips, fill}`:
  the Formatter's output; overrides the house style per block.
- `JobSpec{stamp (required: certified|office), user_id (signing translator), template_id, pdf_page_order, notes}`.
- The JSON Schema export is `docs/document.schema.json` (`certiflow schema`).

### 4.2 Language Profiles and Pair Settings (`certiflow/profiles/`)
- **Profiles:** one JSON file per language in `profiles/data/<code>.json` (17 shipped; regenerate the defaults with
  `python -m certiflow.profiles.seed`). Fields:
  - code, names, script, direction, `word_tag` (proofing language)
  - `font_slot` (ascii | cs | eastAsia), `word_font`, `pdf_font` + `pdf_font_fallback`
  - body size, heading scale, line spacing, justify
  - digit style, quote marks
  - transliteration standard, name rule, `no_foreign_script`
  - `ocr_pack`, vision notes, `style_guide` (injected into prompts)
  - `labels` (note marks, unreadable labels, heading for repeated stamps)
- **Pair Settings:** `profiles/data/pairs.json`, optional per (source, target) pair: template, transliteration,
  `no_foreign_script`, agent models, conventions. `resolve_pair()` merges the two profiles with the pair settings.
- **Adding a language:** add `<code>.json`, install the fonts and the Tesseract pack. No code change.

### 4.3 House style (`certiflow/house.py`)
The office's layout, stored as data and attached to the template asset (`house_style`). Sizes are deltas from the
profile's body size. The Shoreline defaults, measured from the office's approved translations:

| Setting | Value |
|---|---|
| Body | 13 pt Sakkal Majalla (Arabic) |
| Title | +2 pt, centred |
| Section heading | +1 pt, bold, shaded bar `D9E2F3` |
| Field labels | `F2F2F2`, bold |
| Notes | −2 pt, italic, `1F3864`, written `//text//` |
| Numbering | `‎1‎.‏` + 2 spaces (digits isolated) |
| Bullets | `•` + 2 spaces, indent 500 twips |
| Table cell margins | 90/40 twips |
| Spacer paragraph after each table | 14 pt |

### 4.4 Asset Library (`certiflow/assets.py`, manifest `assets/<office>/library.json`, git-ignored)
- `users[]{id, name, role, company}`: library users map 1:1 to web users by `username`.
- `assets[]`, each with an `id`, a `name`, an `active` flag and a `path`. Asset types:
  - `template`
  - `stamp_certified` (owned by a user)
  - `stamp_office` (owned by the company)
  - `signature` (owned by a user)
- Stamps and signatures also carry `width_mm`.
- Template-only fields:

| Field | Meaning |
|---|---|
| `seal_layout` | Ink centres and widths in mm, measured from the approved outputs |
| `strip_footer_images` | SHA-1 of seal images baked into the template, removed at build |
| `margins_mm` | Page margin overrides (for example the 60.85 mm bottom margin) |
| `house_style` | The office layout (§4.3) |
| `source_layout` | `{mode: band, area_mm, seal}` for source pages |

- **Rights:**
  - Certified stamp and signature: their owner, or an admin.
  - Office stamp: the office's certified translators.
  - Stamp and signature PNGs must have transparency. `setup-office` removes paper backgrounds from scans
    automatically (`imageprep.py`).

---

## 5. Agent pipeline (`certiflow/agents`, `certiflow/pipeline/job.py`)

### 5.1 Agents

| Agent | Default model (config) | Input | Output contract (`contracts.py`) | Applied by code |
|---|---|---|---|---|
| Intake | claude-sonnet-5-5 | page image (≤1600 px) + Tesseract draft (300 dpi) + low-confidence lines + end of the previous page | `IntakePageOut`: blocks, languages, rotation, artefacts removed, uncertain regions | blocks, page inventory, joins across page breaks, document-end notes, low-confidence flags |
| Intake zoom | claude-sonnet-5-5 | 2× crop of each uncertain region | `ZoomOut` | replaces the reading if more confident; flags covered/illegible |
| Glossary | claude-opus-5-5 | all source text of the batch | `GlossaryOut` | proposed list; a human confirms it |
| Translator | claude-opus-5-5, effort high | units of ≤40 blocks / ≤20 pages + 3 blocks of context + fix requests (§5.5) | `TranslatorOut` | text, table cells (shape checked → blocker), labels, history |
| Proofreader | claude-opus-5-5 | source + translation | `ProofreaderOut` (tracked changes with category and reason) | one history entry per change |
| QA | claude-opus-5-5 | source + translation + automated findings | `QAOut` (blocker / major / minor) | flags on blocks |
| Formatter | claude-sonnet-5-5 | types + excerpts | `FormatterOut` | type/level/alignment/widths, page break before an apostille |

**Automated QA** runs before the model's QA, with no model call (`qa/scan.py`):

| Check | Severity |
|---|---|
| Figures missing from the translation | blocker |
| Figures added to the translation | blocker |
| Identifiers not kept exactly as written | blocker |
| Empty translations | blocker |
| Leftover source-script text (allow-list: identifiers, underscores, quoted labels, glossary) | major |
| Stray punctuation | minor |

### 5.2 Model calls (`certiflow/llm/client.py`)

Every call uses:
- **structured JSON output** (`output_config.format`), with a strict schema generated from the Pydantic contracts
  (all objects closed, all properties required, nullable for optional values)
- **adaptive thinking**, with effort set per agent
- **streaming**
- **prompt caching:** the system prompt is cached
- **the server-side refusal fallback** (`fallbacks: "default"`, beta header)
- **backoff** on 429, 5xx and connection errors

**Validation retry.** If the output fails validation, the full assistant reply goes back to the model with the error,
up to 2 times. The reply is sent back unchanged because edited history is rejected.

**The API key** is read from `CERTIFLOW_ANTHROPIC_API_KEY`, falling back to `ANTHROPIC_API_KEY`. Hosted coding
sessions do not pass `ANTHROPIC_API_KEY` through.

**Clients:**
- `AnthropicClient`: the real API.
- `MockClient` (handlers or recorded replies) and `RecordingClient` (records real replies for offline replay).
- `llm/mock_agents.py`: deterministic stand-ins for all agents. They produce pseudo-translations and are for tests
  only.

### 5.3 Prompts (`certiflow/agents/prompts/<agent>/v1.md`, `common_rules.v1.md`)
- **Placeholders only, no language written in:** `{source_language}`, `{target_language}`, `{style_guide}`,
  `{name_rule}`, `{transliteration_standard}`, `{foreign_script_rule}`, `{pair_conventions}`, `{glossary}`,
  `{rules}`.
- **Versioning rules:** `docs/PROMPT_VERSIONING.md`. Files are immutable once used; a change is a new version.
  Promotion needs the golden score.

### 5.4 Orchestration
- **LangGraph graph:** `intake_all → glossary → confirm_glossary (interrupt) → process_all → review (interrupt) → release`.
- **Checkpointer:** PostgreSQL when `CERTIFLOW_CHECKPOINT_DSN` is set, otherwise a SQLite file per job.
- **`process_all`:** runs each document in a thread pool (`max_parallel_documents`). Per document: translate →
  proofread → QA → fix loop (max 2) → format.
- **Resumable stages:** every stage writes `docs/<doc>.<stage>.json` and skips work already on disk, so a crash
  resumes at the failed stage.
- **Release:** checks the approver's role, blocks on any unresolved blocker, builds each package, writes the
  disclosures and the zip, and records audit events.
- **Audit:** `jobs/<id>/audit.jsonl`. One record per model call (agent, model, prompt version, effort, usage with
  cached tokens, cost, latency, retries, request id, user prompt, response) plus stage, approval and release events.
  The audit holds document text, so it follows the same confidentiality rules as the documents.

### 5.5 Large documents (splitting and combining)
Any length works: 5 pages or 300. Nothing changes for the user, who still gets **one** Word file and **one** PDF per
document.

1. **Reading:** Intake reads every page separately (OCR plus vision), so length does not matter at this step.
2. **Splitting into units:** Translator, Proofreader and QA work in **translation units**, in document order. A unit
   closes when it reaches **40 blocks** (`pipeline.chunk_blocks`) or would span more than **20 source pages**
   (`pipeline.chunk_max_pages`), whichever comes first. Dense pages make smaller units, which keeps each model call
   well inside its output limit. Both limits are settings in `config/agents.json`.
3. **Consistency across units:**
   - every unit carries the job's **confirmed glossary**, so names and terms are identical everywhere
   - each unit also gets the **last 3 translated blocks** of the previous unit as context, so a sentence or term
     continues correctly across the boundary
   - paragraphs split by a page break were already joined at Intake
4. **Combining:** every unit writes its results back into the **same document model**, in original order. The
   Formatter and the Builder then work on the **whole document at once**, which produces one translation, one Word
   file and one integrated PDF.
5. **Failures:** a unit that fails is retried on its own; finished units are kept on disk, so a long job resumes where
   it stopped. The QA fix loop re-translates only the blocks with blockers, not whole units.

Units of one document run **in sequence** (each needs the previous unit's ending as context). Different documents in
a batch run in parallel. Possible later optimisation: run units in parallel with a glossary-only context, trading a
little continuity for speed on very long documents.

---

## 6. Builder (`certiflow/builder`)

### 6.1 Word (`docx_builder.py`, `seal_docx.py`)
- **Template body:** the body is cleared; header, footers, page size and margins are kept, with margins optionally
  overridden.
- **Two renders of one model:**
  - `word`: the profile's Word font, for the release `.docx`
  - `pdf`: the profile's PDF font if installed (for example the licensed Sakkal Majalla), otherwise the fallback
    (Amiri)
  - Liberation Serif is metric-compatible with Times New Roman, so English PDFs paginate the same as Word.
- **RTL output:**
  - `w:bidi` paragraphs and `w:bidiVisual` tables
  - `w:rtl` runs, and the `cs` font and size slots
  - `w:lang w:bidi` (proofing language)
  - Tokens are isolated with LRM marks (or Unicode isolates).
  - LTR targets isolate RTL stretches with RLM.
- **Proofing:** every run carries `w:lang`; identifiers are `noProof`.
- **Seal (anchored mode):**
  - The baked-in seal images are stripped from all footers.
  - The job's stamp and the signer's signature are drawn as floating images at the page position measured from the
    approved outputs, in every active footer (default, even, first).
  - The top of the seal is never above the body bottom margin.
  - Fallback when a template has no measured layout: inline images at the top of the footer.

### 6.2 PDF (`pdf_builder.py`, `package.py`)
1. **Conversion:** LibreOffice headless, with a private profile per call. Then an invisible marker (render mode 3)
   goes on every translation page. The marker is not in the Word file: a visible marker once showed on the footer.
2. **Text-under-seal check:** any character box intersecting the seal images on a translation page blocks the
   release.
3. **Source pages:**
   - rendered at 130 dpi with pdftoppm (images pass straight through)
   - rotated upright (Intake rotation, then landscape to portrait)
   - saved as JPEG q80, greyscale when the scan is grey
   - placed in one of two modes:

| Mode | Behaviour |
|---|---|
| `band` (office convention) | The scan is fitted into the area above a 49.7 mm band; the seal sits in the band at fixed positions, so no overlap |
| `overlay` (default without a template layout) | The scan fills the page; the seal goes at the footer position, or wherever covers the least ink (`ink + 0.03 × distance`); pages where ink is still covered are disclosed |

4. **Merge:** pypdf, removing duplicate objects. Interleaved order uses per-source-page markers and falls back when
   the mapping is not monotonic.
5. **Verification gate (`verify_certified_pdf`):**
   - The page count must equal translation pages plus source pages.
   - Every page must carry the marker, plus a stamp image and a signature image at the expected physical size (±4 %,
     matched through pdfium).
   - Any failure raises `ReleaseBlocked`.
6. **Naming and output:** `NN_Title_<LANG>.docx/.pdf`, `disclosures.txt`, `<batch>.zip`.

---

## 7. Office setup and golden set

**`certiflow setup-office`:**
- Removes paper backgrounds from the stamp and signature scans (transparent PNG; specks and scanner lines dropped).
- Imports the template.
- **With `--reference-docx`** (an approved output), it takes from it:
  - the seal size and position: ink centre and ink width
  - the margins
  - the exact placement of the template's floating footer graphics (it fixes the template's odd-page footer offset)
- **With `--reference-pdf`**, it takes the source-page band layout.
- It writes `library.json`.

**Golden set:** `inputs/golden_set/<src>-<tgt>/<case>/approved.docx` plus an optional `approved.pdf` and an optional
`source.*` (otherwise the source is extracted from the approved PDF).

| Command | What it does |
|---|---|
| `certiflow golden run` | Imports each approved file into the model (`golden.py`: layout recorded only where it deviates from the house style), rebuilds it, and compares the Word body element by element (text, bidi marks, bold/italic, size, colour, fills, spacing, alignment). Also compares translation page counts. **All 3 office cases are identical.** |
| `certiflow golden score` | Runs the real pipeline on each case's source and scores against the approved translation (figure recall, identifier recall, length ratio, leftover script, open blockers); fails below the thresholds. |

---

## 8. Web application (`certiflow/web`, `web/`)

### 8.1 Configuration (environment)

| Variable | Default | Purpose |
|---|---|---|
| `CERTIFLOW_DATA_DIR` | `data` | Jobs, uploads, release files, dev SQLite |
| `CERTIFLOW_DATABASE_URL` | SQLite in data dir | e.g. `postgresql+psycopg://user:pw@host/certiflow` |
| `CERTIFLOW_CHECKPOINT_DSN` | (none) | PostgreSQL DSN for LangGraph checkpoints |
| `CERTIFLOW_QUEUE` | `thread` | `thread` (dev) or `celery` |
| `CERTIFLOW_REDIS_URL` | `redis://localhost:6379/0` | Celery broker |
| `CERTIFLOW_LLM` | `anthropic` | `anthropic` or `mock` (offline pseudo-translation) |
| `CERTIFLOW_ANTHROPIC_API_KEY` | (none) | Claude API key (server only) |
| `CERTIFLOW_LIBRARY` | `assets/shoreline/library.json` | Asset Library manifest |
| `CERTIFLOW_SECRET_KEY` | generated per install in dev | Session signing key (**set in production**) |
| `CERTIFLOW_SECURE_COOKIES` | `0` | `1` behind HTTPS |
| `CERTIFLOW_SESSION_HOURS` | `12` | Session length |
| `CERTIFLOW_MAX_UPLOAD_MB` | `80` | Per-file upload limit |
| `CERTIFLOW_STATIC_DIR` | `web/dist` | Built frontend |
| `CERTIFLOW_SETTINGS` | `config/agents.json` | Agent/model settings |
| `CERTIFLOW_WORKER_CONCURRENCY` | `2` | Celery concurrency (Docker) |

### 8.2 Database (`web/db.py`, Alembic `certiflow/migrations`)
- **`users`:** id, username (= library user id), name, role, password_hash (scrypt), active, ui_language, created_at.
- **`jobs`:** id (`JYYYYMMDD-xxxxxx`), created_by (the signer), title, languages, stamp, page_order, document_type,
  notes, status, stage, error, cost_usd, approved_by, approved_at, timestamps.
- **`job_documents`:** job_id, idx, doc_key (`d01`…), title, filename, per-document languages.
- **`job_events`:** job_id, at, kind, data (JSON). Status changes for SSE; never document text.
- **Migrations:** ship inside the package. `certiflow web init-db` applies them, and the Docker entrypoint runs it at
  start.

**Job status machine:**
```
queued → running → waiting_glossary → (queued) → running → waiting_review → (queued) → releasing → released
                 ↘ failed (retry → queued)          waiting_review ← ReleaseBlocked (error shown)
```

### 8.3 API (`docs/openapi.json` is the full machine-readable spec; interactive docs at `/api/docs`)
All state-changing requests need the header `X-CertiFlow: 1` (CSRF guard). Sessions are an HttpOnly, SameSite=Strict
cookie signed with HMAC-SHA256.

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/api/auth/login` | anyone | `{username, password}` → sets the cookie |
| POST | `/api/auth/logout` | user | clears the cookie |
| GET | `/api/me` · POST `/api/me/prefs` | user | profile; UI language `en`/`ar` |
| GET | `/api/languages` | user | profiles: code, names, direction |
| GET | `/api/stamps` · `/api/stamps/{choice}/image` | user | stamp options this user may apply (with reasons when not), and the PNG |
| GET | `/api/recent-pairs` | user | last 5 language pairs |
| POST | `/api/jobs` | certified translator, admin | multipart: `files[]`, `source_language` (or `auto`), `target_language`, **`stamp` (required)**, `page_order`, `document_type`, `notes`, `overrides` (JSON `{index: {source_language, target_language}}`). Word files are converted to PDF. 422/403/413 on invalid input |
| GET | `/api/jobs` | user | own jobs (admin: all) |
| GET | `/api/jobs/{id}` | creator, approver, admin | detail: per-document stage, open flags, cost per agent; `files` only once released |
| GET | `/api/jobs/{id}/events` | same | SSE: `progress` (audit records without document text), `status`, `end` |
| GET | `/api/jobs/{id}/glossary` · POST `…/glossary/confirm` | same | proposed or confirmed glossary; confirming resumes the job |
| GET | `/api/jobs/{id}/documents/{dNN}` | same | latest model JSON of a document (review preview) |
| POST | `/api/jobs/{id}/approve` | the signer or an admin | `{note}`; resumes into release |
| POST | `/api/jobs/{id}/retry` | same | for `failed` jobs |
| GET | `/api/jobs/{id}/files/{name}` | same | download; 409 before release; path traversal blocked |
| GET | `/api/health` | anyone | liveness |

### 8.4 Frontend (`web/src`)

**Screens:**
- **Sign-in.**
- **Jobs list:** polls every 5 s.
- **New job:**
  - drag-and-drop upload
  - language selects with auto-detect, a swap button and recent pairs
  - per-document override
  - document type, page order, notes
  - stamp cards with images, **no default**; Start stays disabled until a stamp is chosen
- **Job page:**
  - live progress over SSE
  - per-document stage bars and cost per step
  - glossary table (edit, add, remove, confirm)
  - review preview with flagged blocks highlighted
  - approve with a note
  - downloads after release
  - error display with retry

**i18n:** `src/i18n.tsx`, with English and Arabic messages. `dir` and `lang` are set on `<html>`, and the
layout uses logical Tailwind classes (`ms-`, `pe-`, `text-start`). User text uses `dir="auto"`. The choice is
persisted per user (`/api/me/prefs`). Adding a UI language means adding a message block.

**API client and fonts:** `src/api.ts` (typed). The app makes no external calls: system fonts only (Segoe UI and
Tahoma for Arabic on Windows).

---

## 9. Security and confidentiality

**In place:**
- **Secrets:** the API key is server-side only, never sent to the browser.
- **Passwords and sessions:**
  - passwords hashed with scrypt
  - signed session cookies: HttpOnly, SameSite=Strict, Secure behind HTTPS
  - a CSRF header on all mutations
- **Access:**
  - per-job access checks (creator, approver, admin)
  - stamp rights checked at job creation and again at release
  - release only after approval by a certified translator
  - unresolved QA blockers block the release
  - every page verified before files become downloadable
- **Data handling:**
  - no document text in SSE events or server logs (errors show type and message only)
  - uploads limited by type and size; file names sanitised
  - downloads restricted to the job's release folder
- **Containers:** run as a non-root user.
- **Keeping confidential files out of git:** office assets, fonts, golden samples and `.env` are git-ignored (checked
  before every push).

**Gaps:**
- **Phase 5 items:**
  - rate limiting and lockout on login
  - session revocation (tokens are stateless; logout only clears the cookie)
  - encryption at rest for `/data` and the database (use encrypted volumes or disks at the cloud provider at minimum)
  - retention and auto-deletion of jobs and audit logs
  - per-client access groups
  - an audit log UI
  - backups
- **Deployment item:** TLS terminated at a reverse proxy (Caddy or nginx).

**Data residency:** files stay on the office's server, which can be in a UAE cloud region. Model calls send text to
Anthropic, whose servers are not in the UAE. The office must confirm this is acceptable for its clients.

---

## 10. Deployment

**Image (`Dockerfile`):** multi-stage.
- Stage 1, Node 22: builds the frontend.
- Stage 2, Ubuntu 24.04 with the Python venv:
  - LibreOffice Writer, Poppler, Tesseract and 17 language packs
  - Liberation, Amiri, Noto and Noto CJK fonts
- The entrypoint runs `init-db`, then uvicorn (`web`) or Celery (`worker`).
- Licensed fonts from `/fonts` are installed at start; an unreadable font gives a warning, not a crash.
- The build accepts an optional `--secret id=ca` for builds behind an inspecting proxy; it is not needed on a normal
  server.

**Compose (`docker-compose.yml`):** `postgres` (16), `redis` (7), `api`, `worker`.
- Volumes:
  - `pgdata`
  - `data` (shared by api and worker)
  - `./office` (read-only: office assets and fonts)
- The api binds to `127.0.0.1:8000`; put a TLS reverse proxy in front of it.

**First deployment:**
```bash
cp .env.example .env            # set POSTGRES_PASSWORD, CERTIFLOW_SECRET_KEY, CERTIFLOW_ANTHROPIC_API_KEY, CERTIFLOW_SECURE_COOKIES=1
mkdir -p office && unzip office_assets.zip -d office   # assets/shoreline/library.json, stamps, signature, template, assets/fonts/*.ttf
chmod -R a+rX office
docker compose up -d --build
docker compose exec api certiflow web create-user amir.gomaa --role certified_translator --name "Amir Gomaa"
```

**Hosting recommendation:** a UAE cloud region (Azure UAE North, AWS me-central-1 or Oracle Dubai/Abu Dhabi),
4 vCPU / 16 GB RAM / 100 GB SSD, with encrypted disks, daily snapshots and a domain such as
`app.shoreline-translation.com`.

**Verified:** the image builds; the four containers start; a job runs from upload to download through a separate
Celery worker container; checkpoints are stored in PostgreSQL; Sakkal Majalla is used in the PDF.

---

## 11. Testing

`pytest -q` runs **64 tests**, offline on the mock client, with real OCR, LibreOffice and the Builder. About 90 s.

| File | Covers |
|---|---|
| `test_model_and_assets.py` | model validation, stamp required, stamp rights, profiles, transparent PNG check |
| `test_docx_builder.py` | pair matrix (en>ar, ar>en, fr>en, en>de, es>ar, ru>en) × word/pdf fonts: direction, bidi isolation, numbering, fonts, proofing language, footer seal, template preserved |
| `test_pdf_package.py` | full packages per pair, verification gate (blocks an unstamped page), same seal size on every page, no text under the seal, interleaved order, 24-page size budget, least-ink placement, office stamp |
| `test_office_assets.py` | background removal, template seal import, anchored seal on odd/even pages, RTL identifiers read left-to-right in the rendered PDF |
| `test_golden.py` | builder ↔ importer round trip; the office golden set rebuilds exactly with matching page counts (skipped without the confidential files) |
| `test_pipeline.py` | strict schemas, end to end for 3 pairs (incl. an RTL source), QA loop fixes an injected error, persistent blockers block the release, only certified translators approve, crash resume, real-client request shape, large documents split into units and recombined |
| `test_web.py` | auth + CSRF, reference endpoints, stamp required and checked, full web lifecycle (gates, approve, downloads, SSE without document text, job isolation), Word source + per-document pairs |

**Frontend:** `npm run build` type-checks with `strict`. A Playwright walkthrough (upload, stamp, glossary,
review, approve, download, in EN and AR) was run manually; it is not yet in the suite.

**Recommended CI (Phase 5):** pytest plus the frontend build on every PR. The golden run goes in a protected job that
holds the office assets as secrets.

---

## 12. Roadmap

**Phase 4: review editor and release gate**
- Side-by-side editor:
  - source page image (with block positions from Intake) next to the translated blocks
  - each side in its own direction
  - in-place editing that writes `docs/<doc>.reviewed.json` and history entries
- Tracked changes from the Proofreader: accept or reject per change.
- QA flags: resolve with a comment; blockers must be resolved before approval.
- Re-run one agent on selected blocks (translator/proofreader/QA with an instruction).
- Rendered PDF preview with the chosen stamp before approval (build without the release, or a watermarked preview).
- Audit log view per job.

**Phase 5: hardening**
- Admin screens:
  - users and roles
  - the Asset Library in the database (upload stamps/signatures/templates; runs `setup-office` logic)
  - Language Profiles and Pair Settings in the database
  - prompt versions and model settings
  - glossary memory per client
- Usage and cost dashboard.
- Batch API ("bulk, lower cost").
- Langfuse tracing.
- Storage, encryption and retention:
  - MinIO/S3 storage
  - encryption at rest
  - retention and auto-deletion
  - backups
- Security: login rate limiting, session revocation, per-client access groups.
- Packaging and CI: OCR packs installable on demand, CI pipeline.

**Known limitations and technical debt**
- **Prompts** are v1 and not yet tuned against real API output. The first `golden score` run is in progress.
- **Glossary:** one per job, even with mixed language pairs in a batch.
- **QA loop and per-document parallelism** live inside one graph node, not as LangGraph edges or branches. This is
  functionally equivalent and resumable, but the graph view is coarser than the brief describes.
- **Intake zoom** is a plain Messages API call, not the Claude Agent SDK.
- **Auto-detect** OCRs with a fixed set of packs (en, ar, fr, de, es, ru) before the language is known.
- **SSE** reads the job's audit file, so the API and workers must share the `/data` volume.
- **Bold:** Sakkal Majalla Bold (`majallab.ttf`) is not supplied, so LibreOffice synthesises bold (slightly heavier
  than Word).
- **The asset library manifest** is JSON; it moves to the database with the admin UI.

---

## 13. Office-specific decisions (Shoreline)

- **Translator and stamps:** the certified translator is Amir Gomaa (licence 659), id `amir.gomaa`. The certified
  stamp carries his name and licence; the office stamp reads "DUBAI - U.A.E.".
- **Seal size:** stamp ink width 58.3 mm, signature 51.4 mm, matching the approved outputs. The bottom margin is
  60.85 mm.
- **Template fixes:** the template's even-page footer held a baked-in seal, which is stripped. Its odd-page footer
  placed the address bar 4.3 mm off, which is corrected by `setup-office`.
- **Fonts:** Arabic PDF output uses Sakkal Majalla (a licensed Microsoft font supplied by the office; licence
  coverage for server use is to be confirmed by the office).
- **Golden set:** three approved EN>AR cases (email thread, treatment records, CCTV report). The email thread has no
  source document.
- **Confidential files:** office assets and samples are never committed; they are delivered separately to authorised
  people only.
