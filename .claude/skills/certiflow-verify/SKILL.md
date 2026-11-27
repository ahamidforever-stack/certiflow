---
name: certiflow-verify
description: Full check of a CertiFlow change before saying it is done or committing - Python tests, TypeScript build, a smoke run of the API, and screenshots of changed screens in English and Arabic. Use after finishing a feature or fix, before a commit or PR, or when the user asks "does it work?".
---

# Verify a CertiFlow change

Run the steps that match what changed. Report each result plainly (pass/fail + the error), never "should work".

## 1. Static checks (always)
```bash
cd /root/opt/projects/REPOSITORY/certiflow
.venv/bin/ruff check --select E9,F63,F7,F82,F401,F841 $(git diff --name-only main... -- '*.py' | tr '\n' ' ')   # changed Python files
(cd web && npx tsc -b)                                                                                         # if web/ changed
```

## 2. Tests
- Backend change: `.venv/bin/python -m pytest -q tests/test_web.py` first (fast), then the full suite
  `.venv/bin/python -m pytest -q` (~2.5 min, run in background). All must pass; skipped tests are OK (office files).
- New endpoint or behaviour → it needs a new test in `tests/` (follow `tests/test_web.py` patterns). Missing test = not done.
- DB model change → `.venv/bin/alembic check` reports no pending changes.

## 3. Run the app
- Is it already running? `ss -ltn | grep -E ':8000|:5173'`. If yes, use it (backend changes need a restart: tell the
  user, because `./dev.sh` kills their running copy). If not, start `./dev.sh` in the background.
- Smoke: `curl -s localhost:5173/api/health` → 200.
- Always `CERTIFLOW_LLM=mock` unless the user agreed to a paid run.

## 4. See the screens (any UI change)
```bash
node web/scripts/shot.mjs /changed/path --lang en
node web/scripts/shot.mjs /changed/path --lang ar
node web/scripts/shot.mjs /changed/path --mobile
```
Read every PNG. Check against the `certiflow-ui` skill: RTL mirroring, no clipped/overlapping text, Arabic strings
present (no English leaking into the AR screen), empty/loading/error states. Report any `BROWSER ERRORS` lines
(the 401s on `/login` are expected).
To check a flow with data, create a job with a sample (mock model):
`samples/sources/en_good_standing.pdf` via the New job page or `POST /api/jobs`.

## 5. Before commit
- `git status`: no `assets/`, `inputs/`, `office/`, `data/`, `out/`, `.env`, `.env.dev`, `*.ttf`.
- Docs updated if behaviour changed (`docs/SPEC.md`, `docs/openapi.json` for API changes, `README.md`).
- Summarise to the user: what changed, what was verified, what was not.
