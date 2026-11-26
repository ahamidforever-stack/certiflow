# CertiFlow architecture

## Components

| Layer | Component | Tech | Phase |
|---|---|---|---|
| Model | Document model + agent contracts | Pydantic (`certiflow/model.py`) | 1 |
| Language | Language Profiles, Pair Settings | JSON now, PostgreSQL later, same schema (`certiflow/profiles/`) | 1 (data), 3 (DB) |
| Assets | Templates, stamps, signatures + access rules | `certiflow/assets.py` (manifest now, DB + MinIO later) | 1 |
| Builder | Word renderer | python-docx + direct OOXML (`builder/docx_builder.py`) | 1 |
| Builder | PDF: LibreOffice convert, source stamping, merge, verify | LibreOffice headless, pdftoppm, reportlab, pypdf, pypdfium2 (`builder/pdf_builder.py`) | 1 |
| Builder | Package, disclosures, zip | `builder/package.py` | 1 |
| QA (deterministic) | Leftover-script scan, stray punctuation, figure match | `qa/scan.py` | 1 |
| Agents | Intake, Glossary, Translator, Proofreader, QA, Formatter | Anthropic SDK, tool-use JSON schemas, one module + prompt file each | 2 |
| Orchestration | Graph, QA loop, human interrupt, checkpoints | LangGraph + Postgres checkpointer, inside Celery workers | 2-3 |
| API / UI | Jobs, review editor, release gate, admin | FastAPI, React/TS/Vite/Tailwind, SSE | 3-5 |
| Observability | Audit table + traces | Postgres + self-hosted Langfuse | 2-5 |

## Data flow

```
upload ─► Intake (render, OCR, vision check) ─► Glossary (batch-wide, user confirms once)
       ─► Translator ─► Proofreader ─► QA ──blocker──► back to Translator/Proofreader (max 2 loops, then human)
       ─► Formatter ─► [human Final Review: LangGraph interrupt] ─► Builder ─► verify ─► release
```

Agents only exchange the `Document` model. The Builder is plain code; the model never writes XML or binary.

## Builder details

* **Two renders of one model.** The release `.docx` uses each profile's Word font (Sakkal Majalla, Times New Roman, ...).
  The PDF is converted from a second, identical render that uses the profile's open font (Amiri, Liberation Serif,
  Noto). LibreOffice cannot use proprietary Word fonts. Liberation Serif is metric-compatible with Times New Roman,
  so Latin-target pages paginate identically. Arabic pages may break lines differently between Word and the PDF
  (Amiri vs Sakkal Majalla metrics). See "Changes to the brief".
* **Direction** comes from the target profile only. RTL: `w:bidi` paragraphs, `w:bidiVisual` tables, `w:rtl` runs,
  `cs` font slot + `w:lang w:bidi`. Tokens (identifiers, numbers, dates, emails, URLs, Latin acronyms) are split
  into their own runs, wrapped in LRM marks (or Unicode isolates, a build option) and tagged `noProof`. LTR targets isolate
  RTL-script stretches with RLM. Numbered-item labels are isolated runs, so numbering survives RTL.
* **Seal.** Signature and stamp go in as *inline* pictures at the top of every footer (primary, first-page and even
  footers when the template uses them). Inline footer content grows the footer, so body text can never run under
  the seal. A 1 pt white marker (`CFSEAL`) is written next to them.
* **Source pages.** Rendered at 130 dpi, turned upright (Intake rotation, then landscape to portrait), fitted to the
  translation page size, embedded as JPEG q80 (grayscale when the scan is grey). Stamp and signature are drawn at the
  exact size found in the translation footer. The position is the footer position unless another spot covers less
  ink. Candidates are scored `ink + 0.03 × distance`. If the best spot still covers ink (>0.4 % of seal area), the
  page goes into the disclosure list.
* **Release gate** (`verify_certified_pdf`): page count = translation + source pages, and on every page the
  marker text plus a stamp image and a signature image at the expected physical size (±4 %, matched by width and
  aspect through pdfium). Any failure raises `ReleaseBlocked`.
* **Interleaved order**: in interleaved mode the Builder starts each source page's blocks on a new page with a
  hidden `CFSPnnn` marker. The merger maps translation pages to source pages from those markers and falls back to
  translation-then-source (with a disclosure) if the mapping is not monotonic and complete.

## Document model (summary)

`Document{id, title, source_language, target_language, document_type, pages[PageInfo], glossary[GlossaryEntry], blocks[Block]}`

`Block{id, type, source_page, source_text, translated_text, runs[InlineRun]?, direction?, status, confidence,
flags[Flag], history[HistoryEntry], layout(Layout), level, label, rows[TableRow], column_widths, note_kind,
note_scope(inline|page_end|document_end), unreadable_reason, multilingual_duplicate}`

Block types: heading, paragraph, numbered_item, bullet, table, kv_table, note, page_break, signature_block,
unreadable. `InlineRun{text, kind(text|identifier|number|date|email|url|name), direction?, bold, italic}`.
Full JSON Schema: `certiflow schema`.

## Changes to the brief (proposed)

1. **Arabic Word/PDF font parity.** Sakkal Majalla is a proprietary Microsoft font and cannot ship in the Linux
   image unless the office supplies a licensed copy. Default: Amiri in the PDF. Content and structure match, but
   line breaks can differ. If you provide a licensed TTF, the profile's `pdf_font` switches to it with no code change.
2. **Claude Agent SDK in Intake.** It runs a CLI subprocess per call, which is heavy inside Celery workers. I propose a
   plain Messages-API tool-use loop (tools: crop, zoom-render, OCR region) with the same behaviour. The Agent SDK stays
   behind the same interface as an option.
3. **Langfuse vs "no document content in logs".** Traces would contain document text. Run Langfuse self-hosted
   only, on the same encrypted storage and retention as documents, or with input/output masking on. The same applies to
   the audit table's stored prompts and responses.
4. **"Same footer position" vs "least ink".** These can conflict on source pages. Implemented as: footer position by
   default, moved only when that clearly reduces overlap, and disclosed when no clean spot exists.
5. **PyMuPDF is not used** (AGPL). pypdfium2 (BSD/Apache) is used for geometry checks.
