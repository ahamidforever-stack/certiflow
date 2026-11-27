# Handoff: status and next steps

Read this first in a new session.

## Status
- **Phase 1** (document model, Word/PDF builder, stamping, release verification) is done.
- **Phase 2** (agents, prompts, LangGraph pipeline, QA loop, audit, golden harness) is done: 67 tests pass with the office files.
- The golden set (3 approved EN>AR translations from the office) rebuilds exactly at Word level. PDF page counts match
  when Sakkal Majalla is installed. The header, footer and seal positions match the approved PDFs on every page.
- **First real API runs done (2026-11-27).** Golden score passes on cases 02 and 03 with intake v3 + translator v2
  (now active in `config/agents.json`); case 01 is skipped until its source arrives. Phase 3 (web app) has not started.

| Run | Prompts | 02 figs/ids/length/blockers | 03 figs/ids/length/blockers | Cost 02 + 03 |
|---|---|---|---|---|
| v1 | all v1 | 80% / 100% / x0.86 / 69 | 100% / 100% / x1.68 / 0 | $2.75 + $0.48 |
| v4 (active) | intake v3, translator v2 | 98% / 100% / x0.87 / 0 PASS | 100% / 100% / x1.10 / 0 PASS | $1.33 + $0.47 |

  (v1 re-scored with the corrected checks.) What fixed it: the deterministic checks no longer treat doses, vitals,
  clock times and chemical symbols as identifiers; Arabic units and times follow the approved translations
  (`profiles/data/ar.json`); translator v2 drops markup symbols printed in a source (`#`, `**`); intake v3 describes
  photos in one short sentence.
- **Known layout gap:** intake does not read table layout the same way every run. In the active run it read the
  case 02 nursing notes as a 2-column table (approved: one full-width cell; earlier run: a paragraph). The builder
  now widens a plain-table column that holds most of the text, but rows never split (house layout), so that draft
  is 15 pages against 12 approved, with a mostly empty page 6. The golden score does not measure page count yet.
- **Drafts for review:** the pipeline stops at the translator-approval gate, so golden outputs carry no seal. Never run
  `job approve` on the user's behalf: approval records the certified translator's sign-off and applies the stamp.

## Office files (confidential, never committed)
The user uploads `certiflow_office_assets.zip`. From the repository root:
```bash
unzip -o certiflow_office_assets.zip      # creates assets/ and inputs/ (both git-ignored)
certiflow fonts install assets/fonts      # Sakkal Majalla for Arabic PDFs
certiflow fonts status
```
- `assets/shoreline/library.json` holds the office template, the stamps (certified/office), the signature of the
  translator `amir.gomaa`, the seal layout, the margins and the source-page band, all taken from the approved outputs.
- `inputs/golden_set/en-ar/` holds the approved cases. Case 01 has no source document yet.

### If the user uploads the original files instead of the zip
Zip attachments may not reach the session. The user then attaches the loose files: the template (`Source_templete.docx`),
three JPGs (signature, certified stamp with the translator's name and licence 659, office stamp "DUBAI - U.A.E."),
`majalla.ttf`, and the approved samples (`*_AR.docx` and `*_AR.pdf`). Find them under `/root/.claude/uploads/`, look at
the three images to tell them apart, then rebuild the office setup.

The files are numbered: `01_template_Shoreline.docx`, `02_signature.jpg`, `03_stamp_certified.jpg`, `04_stamp_office.jpg`,
`05_majalla.ttf`, `06_sample1_email_thread_AR.docx` (case 01), `07_`/`08_sample2_treatment_records_AR.docx/.pdf`
(case 02), and `09_`/`10_sample3_cctv_report_AR.docx/.pdf` (case 03). The same files may also come as
`office_files_all.zip`.
```bash
mkdir -p inputs/raw assets/fonts inputs/golden_set/en-ar/{01_cctv_email_thread,02_treatment_records,03_cctv_service_report}
cp <template>.docx inputs/shoreline_template.docx
cp <signature>.jpg inputs/raw/signature.jpg; cp <certified>.jpg inputs/raw/stamp_certified.jpg; cp <office>.jpg inputs/raw/stamp_office.jpg
cp <majalla>.ttf assets/fonts/majalla.ttf && certiflow fonts install assets/fonts
# approved samples: <case>/approved.docx and <case>/approved.pdf (case 01 has a .docx only)
certiflow setup-office --template inputs/shoreline_template.docx --signature inputs/raw/signature.jpg \
  --certified-stamp inputs/raw/stamp_certified.jpg --office-stamp inputs/raw/stamp_office.jpg \
  --translator-id amir.gomaa --translator-name "Amir Gomaa" --out assets/shoreline \
  --reference-docx inputs/golden_set/en-ar/03_cctv_service_report/approved.docx \
  --reference-pdf inputs/golden_set/en-ar/03_cctv_service_report/approved.pdf \
  --certified-width-mm 58.3 --office-width-mm 58.3 --signature-width-mm 51.4
certiflow golden run inputs/golden_set --library assets/shoreline/library.json --user amir.gomaa   # expect 3x PASS
```
(The earlier setup used sharper copies of the certified stamp and signature taken from inside the template, at
`word/media/image2.png` and `image3.png`. Extract them with `unzip -p` and pass them instead of the JPGs for better print quality.)

## First thing to run with the API key
The key is in the environment variable `CERTIFLOW_ANTHROPIC_API_KEY` (cloud environment "certiflow"). Hosted
sessions do not pass `ANTHROPIC_API_KEY` to commands, so CertiFlow reads its own variable first
(`certiflow/llm/client.py: api_key_from_env`). Check it with `test -n "$CERTIFLOW_ANTHROPIC_API_KEY" && echo set`.
Never ask the user to paste keys in chat.
```bash
python3 -m pytest -q tests                                   # 57 pass with the office files, some skip without
certiflow golden score inputs/golden_set --library assets/shoreline/library.json --user amir.gomaa --out out/score_v1
```
Report per case: figure and identifier recall, length ratio, leftover script, open blockers, and cost (from
`out/score_v1/<pair>/<case>/audit.jsonl`). Send the Word/PDF outputs next to the approved versions, then tune the
prompts (`docs/PROMPT_VERSIONING.md`: new versions, never edit v1 in place).

## Decisions already made with the user
- **Stamp choice:** required per job, no default (Certified = Amir Gomaa licence 659, or Office). The stamp is applied
  only after a certified translator approves.
- **Seal size and position:** stamp 58.3 mm, signature 51.4 mm, both from the approved outputs. The template's
  baked-in seal is stripped. The seal sits on every page.
- **Source pages:** "band" mode: the scan is fitted above a 50 mm band and the seal sits in the band.
- **Arabic house style:** 13 pt Sakkal Majalla, section bars D9E2F3, label cells F2F2F2, notes in italic 11 pt
  1F3864, and the `‎1‎.‏` numbering. All stored as data (`certiflow/house.py`, `profiles/data/ar.json`).
- **Models:** in `config/agents.json`. Opus 5.5 for the translator, proofreader, QA and glossary; Sonnet 5.5 for intake
  and the formatter. Server-side refusal fallback is on.

## Open items for the user
- The source document for golden case 01 (the email thread).
- `majallab.ttf` (Sakkal Majalla Bold) for exact bold in PDFs.
- Confirm the Microsoft font licence covers server use.
- Rotate the API key: earlier keys were exposed in chat.

## Next phase
Phase 3, the web app: FastAPI, Celery/Redis, PostgreSQL checkpointer, React/TS/Tailwind with RTL UI, upload, the
stamp selector, the pipeline view with SSE, downloads and auth. Work on a branch and open a PR when done.
