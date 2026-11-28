# Developer guide

Start with `docs/SPEC.md`, which covers what exists, how it fits together, and what is open. This guide covers how to
work on the code.

## 1. Getting the code

```bash
git clone https://github.com/ahamidforever-stack/certiflow.git
cd certiflow
git checkout claude/phase3-web-app     # Phase 3 (web app); main has Phases 1–2 until this branch is merged
```

**Confidential office files** (template, stamps, signature, licensed font, approved samples) are **not in git**. You
can do almost all development with the generated placeholder samples (`certiflow samples samples`). If the office
gives you its files, unpack them so they create `assets/` and `inputs/` in the repo root. Both folders are
git-ignored. Never commit them.

## 2. Local setup (Linux, macOS or WSL)

**System packages** (Ubuntu names):
```bash
sudo apt-get install -y libreoffice-writer-nogui poppler-utils fontconfig \
  tesseract-ocr tesseract-ocr-ara tesseract-ocr-eng tesseract-ocr-fra tesseract-ocr-deu tesseract-ocr-spa tesseract-ocr-rus \
  fonts-liberation fonts-hosny-amiri fonts-noto-core fonts-noto-cjk postgresql redis-server
```

**Python 3.12+ and Node 22:**
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[web,dev]"
(cd web && npm ci)
certiflow samples samples                    # placeholder template, stamps, signature, source scans
certiflow fonts install assets/fonts         # only if you have the office's licensed fonts
```

## 3. Running

**Engine only (CLI):**
```bash
certiflow build samples/models/en_ar_good_standing.json --source samples/sources/en_good_standing.pdf \
  --stamp certified --user translator1 --library samples/assets/library.json --out out/demo
certiflow translate samples/sources/en_good_standing.pdf --from en --to ar --stamp office --user translator1 \
  --library samples/assets/library.json --job-dir out/jobs/J1 --mock      # --mock = offline pseudo-translation
certiflow job confirm-glossary out/jobs/J1 --by translator1 --mock
certiflow job approve out/jobs/J1 --by translator1 --mock
```

**Web app (dev):** SQLite, in-process runner, mock model:
```bash
export CERTIFLOW_LIBRARY=samples/assets/library.json CERTIFLOW_LLM=mock
certiflow web init-db
certiflow web create-user translator1 --role certified_translator --name "J. Doe"
certiflow web serve --port 8000              # API + built frontend (run `cd web && npm run build` first)
# frontend hot reload: cd web && npm run dev   (proxies /api to :8000) → http://localhost:5173
```
For real translations, set `CERTIFLOW_LLM=anthropic` and `CERTIFLOW_ANTHROPIC_API_KEY=...`.

**Production-like stack:**
- Locally: PostgreSQL + Redis + `celery -A certiflow.web.tasks worker` with `CERTIFLOW_QUEUE=celery`.
- In Docker: `docker compose up -d --build` (see `docker-compose.yml`, `.env.example`, SPEC §10).

## 4. Tests

```bash
pytest -q                       # 65 tests, ~5 min, offline (needs LibreOffice + Tesseract)
pytest -q tests/test_web.py     # web API only
(cd web && npm run build)       # strict TypeScript check + production build
(cd web && npm run e2e)         # Playwright walkthrough: upload → glossary → review editor → approve → audit
                                #   (own server on :8765, mock LLM, throw-away data; first time: npx playwright install chromium)
certiflow golden run inputs/golden_set --library assets/shoreline/library.json --user amir.gomaa      # exact rebuild check (office files)
certiflow golden score inputs/golden_set --library assets/shoreline/library.json --user amir.gomaa   # real pipeline vs approved (API key, costs money)
```

**Skipped tests:** tests that need the confidential office files skip themselves when the files are absent.

## 5. Code map

```
certiflow/
  model.py               document model + JobSpec (Pydantic)            ← the contract between everything
  profiles/              Language Profiles (data/*.json), Pair Settings, seed.py
  house.py               office house style (data)
  textdir.py             scripts, run segmentation, bidi isolation
  assets.py              Asset Library + stamp rights
  imageprep.py           stamp/signature background removal
  templates.py           template import: baked seal, seal layout, footer graphic alignment, source band
  office_setup.py        `setup-office` (raw scans + template + approved reference → library.json)
  fonts.py               licensed font install/availability
  ocr.py                 page rendering + Tesseract
  builder/
    docx_builder.py      model → .docx (RTL/LTR, house style, tables, notes, numbering)
    seal_docx.py         signature + stamp in footers (anchored / inline)
    pdf_builder.py       LibreOffice, source pages (band/overlay), merge, marker, verification gate
    package.py           one certified package per document; disclosures; zip
  qa/scan.py             automated QA checks (figures, identifiers, scripts, punctuation)
  agents/
    contracts.py         agent output schemas
    base.py              prompt loading, language placeholders, model call + audit record
    steps.py             intake, glossary, translate, proofread, qa, format_document
    prompts/             versioned prompt files
  llm/
    client.py            LLMClient interface, AnthropicClient, MockClient, RecordingClient, strict_schema
    mock_agents.py       deterministic offline agents (tests)
  pipeline/job.py        LangGraph job graph, stages, gates, release, status
  golden.py              approved .docx → model, formatting-aware compare, golden run/score
  settings.py            config/agents.json loader (models, effort, pricing, pipeline knobs)
  web/
    config.py            environment settings
    db.py                SQLAlchemy models
    auth.py              scrypt + signed cookie
    app.py               FastAPI app (API + static frontend)
    runner.py            advance(job, resume) on thread pool or Celery
    tasks.py             Celery app
  migrations/            Alembic (ships inside the package)
  cli.py                 the `certiflow` command
web/                     React + TypeScript + Vite + Tailwind frontend (src/pages, src/i18n.tsx, src/api.ts)
config/agents.json       models per agent, effort, pricing, pipeline settings
docs/                    BRIEF, SPEC, ARCHITECTURE, PROMPT_VERSIONING, DEVELOPER_GUIDE, openapi.json, schema
tests/                   pytest suites
Dockerfile, docker-compose.yml, docker/entrypoint.sh, .env.example
```

## 6. Conventions

**Language-neutral code**
- Never write a language, model name or font in code. They live in profiles, `config/agents.json` and assets.
- A new language is data: a profile JSON, the font and the OCR pack.

**Models and the Builder**
- **The model never edits the Document.** Agents return their contract, code applies it, and every change appends a
  `HistoryEntry`.
- **The Builder is deterministic.** No model output goes into XML or binaries directly.

**Prompts and stages**
- **Prompts are versioned files.** Never edit a used version; add `v2.md` and switch it in `config/agents.json`.
  Promote a version only after `golden score` (`docs/PROMPT_VERSIONING.md`).
- **Pipeline stages are idempotent:** read the stage file if present, write it when done.

**Confidentiality**
- No document text in logs or in SSE events.
- Audit files and job folders are confidential data.
- Before every push, check that `git status` shows no `assets/`, `inputs/`, `office/`, `.env` or `*.ttf` files.

**UI**
- Use logical Tailwind classes (`ms-`, `pe-`, `text-start`), never `left` or `right`.
- Any user-entered or document text gets `dir="auto"`.
- All strings go through `t()` in `i18n.tsx`, with both English and Arabic.

**Database**
- Schema changes need a migration:
  `CERTIFLOW_DATA_DIR=/tmp/x alembic revision --autogenerate -m "..."`, then `certiflow web init-db`.
- `alembic check` must report no pending changes.

**Commits:** small and descriptive. Keep `main` releasable and work on feature branches with PRs.

## 7. Phase 4: review editor (done)

- **Review logic:** `certiflow/review.py` (edit a block, accept/reject an agent change, resolve a flag). Pure functions;
  every text change appends a `HistoryEntry`. The API saves the result as `docs/<doc>.reviewed.json`.
- **API** (`certiflow/web/app.py`), all only while the job is `waiting_review`:
  - `PUT …/documents/{dNN}/blocks/{block}`, `POST …/blocks/{block}/changes/{n}/{accept|reject}`,
    `POST …/blocks/{block}/flags/{n}/resolve` (a blocker needs a comment)
  - `GET …/documents/{dNN}/pages/{n}.png` (source page, rendered once into `pages/`)
  - `POST …/documents/{dNN}/rerun` (translator, proofreader or QA on chosen blocks; job status `reworking` meanwhile)
  - `GET …/documents/{dNN}/preview.pdf` (stamped, watermarked; only the watermarked file is kept, in `preview/`)
  - `GET /api/jobs/{id}/audit` (whitelisted fields only: never prompts, responses or instructions)
  - Approval is refused (409) while a blocker is open.
- **Block positions:** `Block.bbox` (0-1000 grid) from the intake contract. The prompt `intake/v2.md` asks for it, but
  v1 stays active until `golden score` passes with v2 (`docs/PROMPT_VERSIONING.md`).
- **UI:** `web/src/pages/Review.tsx` (side-by-side editor), `Audit.tsx`, the approval confirmation in `JobView.tsx`.
- **Tests:** `tests/test_web.py` (review, re-run, preview, audit) and `web/e2e/walkthrough.spec.ts`.

## 8. Phase 5: hardening (in progress, branch `claude/phase5-hardening`)

- **Step 1, sign-in limits and sessions (done):** `login_attempts` and `user_sessions` tables (migration 0002).
  The cookie carries a session id; `_session()` in `web/app.py` checks the row on every request. Endpoints:
  `GET /api/me/sessions`, `POST /api/me/sessions/revoke-others`. Screen: `web/src/pages/Account.tsx`.
  Rules: SPEC §8. After upgrading, everyone signs in once again (old cookies have no session id).
- **Step 2, user administration (done):** admins only. `GET/POST /api/admin/users`, `PATCH /api/admin/users/{id}`
  (name, role, active), `POST …/{id}/password`, `…/{id}/unlock`, `…/{id}/sessions/revoke`, `GET /api/admin/events`.
  Every change is written to `admin_events` (migration 0003; never a password). Guards: an admin cannot change their
  own role or deactivate themselves, and the last active admin cannot be removed. Deactivating a user or setting a new
  password signs them out everywhere. Screen: `web/src/pages/Users.tsx` (menu "Users", admins only).
- **Step 3, usage and cost dashboard (done):** `web/usage.py`. `sync_job()` copies a job's `llm_call` records (numbers
  only) from `audit.jsonl` into the `llm_usage` table and stores the job's page count (`jobs.pages`, from Intake);
  the runner calls it whenever it updates `jobs.cost_usd`. `certiflow web init-db` backfills older jobs once
  (migration 0004). `GET /api/admin/usage?days=7|30|90|365` returns tiles (today, 7 days, this month), per day, per
  agent, per model, per user (job creator), top jobs and the average cost per page. Days follow
  `CERTIFLOW_TIMEZONE` (default `Asia/Dubai`). Screen: `web/src/pages/Usage.tsx` (menu "Costs", admins only).
- **Step 4, Asset Library administration (done):** `web/assets_admin.py`. Admins upload certified stamps and
  signatures (per translator), the office stamp and Word templates on the "Stamps & templates" screen
  (`web/src/pages/Assets.tsx`). Endpoints: `GET /api/admin/assets`, `GET /api/admin/assets/{id}/file`,
  `POST /api/admin/assets/image` (kind, file, owner, width_mm), `POST /api/admin/assets/template` (file, language,
  pair, optional `reference_docx`/`reference_pdf`), `PATCH /api/admin/assets/{id}` (active, name, width_mm).
  Same processing as `setup-office` (background removal; template import with an optional approved sample).
  Files are never overwritten: each upload gets a new file and id, and the asset it replaces is switched off but
  kept. The manifest is written atomically under a lock. The bundled `samples/` library is read-only. The library's
  user list follows the web accounts (create/rename/role change, and when a stamp is assigned).
  **Decision:** the manifest stays a JSON file on the shared volume rather than moving to the database, so workers
  and the CLI keep reading one source; revisit together with S3/MinIO storage.
- **Step 5, glossary memory, model settings, languages (done):**
  - *Glossary memory per client:* `jobs.client` and the `client_terms` table (migration 0005). New job takes an
    optional client name; the API writes that client's terms for the job's target language(s) to
    `glossary.memory.json` in the job folder. `Job.remembered_terms()` seeds the glossary step with the terms whose
    source text occurs in the batch (pre-confirmed); the agent only adds new ones (no prompt change). Confirming a
    glossary upserts its terms for the client and the pair Intake detected. Client names match case- and
    space-insensitively (`client_key`). API: `/api/clients`, `/api/glossary-memory[/terms]`. Screen: "Glossaries"
    (certified translators and admins).
  - *Model settings:* admin changes are written to `<data>/settings/agents.json`, laid over `config/agents.json` by
    `settings.load()` (re-read when the file changes). Model (must have a price), effort, prompt version (files in
    `agents/prompts/<agent>/`), max tokens; QA rounds and documents in parallel. Screen: Admin → AI models.
  - *Languages and pairs:* admin changes go to `<data>/settings/languages.json`, laid over
    `profiles/data/*.json` (fonts, sizes, digits, quote marks, style guide, name rule, transliteration, scan notes;
    pair rules, template, source-script rule). The log records which prompt-facing texts changed, never their text.
    Screen: Admin → Languages (shows whether each PDF font is installed).
  - Admin pages are grouped under one "Admin" menu entry with tabs. Pipeline stage files are written atomically.

