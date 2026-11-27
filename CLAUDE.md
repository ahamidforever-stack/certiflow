# CertiFlow

Certified-translation pipeline for Shoreline Legal Translation (Dubai): upload → OCR/intake → glossary → translate →
proofread → QA → human review → stamped Word/PDF release. Python engine + FastAPI + React/TS/Tailwind (EN/AR, RTL).

Read first: `docs/HANDOFF.md` (status, office files, decisions), `docs/DEVELOPER_GUIDE.md` (code map, conventions),
`docs/SPEC.md` (spec + roadmap, §12 = Phase 4/5).

## Run, see, test
- **Run the app:** `./dev.sh` → http://localhost:5173 (API :8000, Vite proxies `/api`). Settings and API key come from
  `.env.dev` (git-ignored; template `.env.dev.example`). Default is `CERTIFLOW_LLM=mock` (free, offline).
  The user usually has it running already: check `ss -ltn | grep -E ':8000|:5173'` before starting it; `dev.sh`
  kills whatever holds those ports, so never restart it while the user is using it without telling them.
- **See the UI:** `node web/scripts/shot.mjs /path [/path2] [--lang ar] [--mobile]` → PNGs in `out/shots/`, then Read
  them. Signs in as `claude-dev` (credentials in `.env.dev`). Check every UI change in **both EN and AR**.
- **Tests:** `.venv/bin/python -m pytest -q` (~2.5 min, offline) · `pytest -q tests/test_web.py` (API only) ·
  `cd web && npx tsc -b` (types) · `cd web && npm run build`.
- **Python:** always the project venv: `. .venv/bin/activate` or `.venv/bin/...`.
- Skills: `certiflow-verify` (full check after a change), `certiflow-ui` (design rules for screens).

## Rules that must not be broken
- **Confidential:** never commit `assets/`, `inputs/`, `office/`, `.env*` (except `*.example`), `*.ttf`, job data
  (`data/`, `out/`). Check `git status` before every commit. No document text in logs, SSE events or commit messages.
- **Never ask for or echo API keys in chat.** The key lives in `.env.dev` (`CERTIFLOW_ANTHROPIC_API_KEY`).
- **No real API calls without telling the user first** (they cost money). Use `CERTIFLOW_LLM=mock` for testing.
- **Language-neutral code:** no language, model name or font hard-coded; they live in `certiflow/profiles/data`,
  `config/agents.json` and the asset library.
- **The model never edits the Document directly:** agents return their contract, code applies it, each change appends
  a `HistoryEntry`. The Builder is deterministic.
- **Prompts are versioned:** never edit a used prompt version; add `vN+1.md` and switch it in `config/agents.json`.
- **Stamp:** chosen per job, no default; applied only after a certified translator approves.
- **DB schema change → Alembic migration** (`docs/DEVELOPER_GUIDE.md` §6); `alembic check` must be clean.
- **UI:** logical Tailwind classes (`ms-`/`me-`/`ps-`/`pe-`/`start`/`end`, never `left`/`right`), `dir="auto"` on
  user/document text, every string through `t()` in `web/src/i18n.tsx` with **both** `en` and `ar`.

## Workflow
- One branch per phase from `main` (`claude/phase4-review-editor`, …); small descriptive commits; PR to `main`.
  The user merges PRs on GitHub. Commit/push only when the user asks.
- The user is not a native English speaker: explain in short, plain sentences, give exact commands to run.
