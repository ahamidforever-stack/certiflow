# CertiFlow

Certified translation platform: source document → agent pipeline → human approval → signed and stamped Word +
one integrated PDF (translation pages, then the stamped source pages).

Status: **Phase 1 (core engine, CLI)**. See `docs/ARCHITECTURE.md`.

## Setup

```bash
pip install -e .[dev]
# system: LibreOffice, poppler-utils, tesseract + language packs, fonts (Amiri, Noto, Liberation) - see requirements-system.txt
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
