# Product brief (original requirements)

This is the original brief from the office, kept verbatim as the source of the requirements. `docs/SPEC.md` describes
what is built, how it maps to this brief, and where the implementation deliberately differs.

---

## 0. Role

Act as a senior full-stack web developer and AI systems architect. Build a production-quality web platform called
CertiFlow (working name) for a certified translation office in Dubai (Shoreline Legal Translation). The platform takes
a source document (PDF, scan, image, Word), runs it through a pipeline of specialised Claude agents, and outputs a
certified translation as Word (.docx) and PDF, stamped and signed on the office template.

Work in phases. After each phase, run the tests, show me what works, and wait for my go-ahead only if a decision is
needed. Do not stop to ask about things that have a sensible default listed here.

### 0.1 Language pairs are variable (core requirement)

The platform is not built for one language pair. The source language and target language are chosen per job (or per
document inside a batch), for example English to Arabic, Arabic to English, French to English, English to German,
Spanish to Arabic, Turkish to English, Russian to English. Any pair that Claude can translate must work.

Design consequences, applied everywhere below:

- No language is hard-coded in agent prompts, the Builder, the UI logic, or the tests. Every language-specific
  behaviour comes from a Language Profile (section 5.1) and the Language Pair Settings (section 5.2).
- Prompts use placeholders such as {source_language} and {target_language}, filled at run time.
- Adding a new language or pair must be an admin configuration task (new profile, fonts, OCR pack, glossary), not a
  code change.
- Supported from day one: Arabic, English, French, German, Spanish, Italian, Portuguese, Turkish, Russian, Persian,
  Urdu, Hebrew, Chinese, Japanese, Korean, Hindi, Dutch. Both directions (left-to-right and right-to-left) must be
  supported for source and target.

## 1. The problem and the standing deliverable

Today the process is manual: one person translates, proofreads, checks, formats and assembles the files. The platform
must automate this with one agent per stage, while keeping a human certified translator in control of the final
release.

For every job the system generates two files:

- **Word file (.docx)** built on the office template (header, footer, contact block). Signature and stamp sit in the
  footer of every page.
- **PDF file (one integrated file):** a single PDF that contains both the certified translation and the original
  source document. The translation pages come first, then the original source pages directly after them in the same
  file. Every page of the PDF, translation pages and source pages alike, is signed and stamped with the stamp chosen
  for the job, at exactly the same physical size and in the same footer position, so the whole file reads as one
  certified package. The source pages are fitted to the same page size as the translation pages. Never output the
  source as a separate file, and never leave a source page without stamp and signature.

Add a job setting PDF page order: "translation then source" (default), or "interleaved" (each translated page followed
by the source page it came from, only where the page mapping is reliable). Default must be used unless the user
changes it.

Batch jobs (many documents) produce one pair per document plus a zip of everything.

## 2. Stamp selection (required feature)

- On every job, the user must choose the stamp: Certified stamp or Office stamp. There is no default. If the user has
  not chosen, the job cannot start (the UI blocks it, the API returns a validation error).
- Certified stamp = the translator's personal certified oval stamp (name and licence number).
- Office stamp = the company oval stamp (for example "DUBAI - U.A.E.").
- Stamp and signature images live in an admin-managed Asset Library (upload PNG with transparent background, name,
  type, active flag, owner). Each stamp is tied to a user or company, and only authorised users can apply it.
- The chosen stamp is recorded in the job audit log and printed nowhere else in the document text.

## 3. The agent pipeline

Use the Anthropic API (Claude) with a clear separation: each agent has its own system prompt, input schema, output
schema, and model setting. Agents communicate only through a shared structured document model (section 4), never
through free text. Make the model per agent configurable in settings (default to the strongest model for Translator
and QA, a faster one for Formatter checks).

| # | Agent | Responsibility | Output |
|---|---|---|---|
| 0 | Intake agent | Inspect pages (render images), detect the language(s) of each page (a document can mix languages, and may repeat the same text in several languages), page count, orientation, stamps, signatures, handwriting, tables. For scans run OCR (tesseract, source language) at 200 to 300 dpi, then vision-check low-confidence regions and anything under a stamp by cropping at higher resolution. | Page inventory and draft source blocks with confidence scores |
| 1 | Translator agent | Translate block by block from {source_language} into {target_language}, applying the universal rules and the Language Profile of the target (section 5) and the job glossary. | Translated blocks |
| 2 | Proofreader agent | Independent pass, sees source and translation. Fixes grammar, terminology consistency, names, and register. Returns tracked changes with a reason per change, not a silent rewrite. | Corrected blocks plus change list |
| 3 | QA agent | Verifies against the source: every number, date, name, amount, reference and ID matches; nothing missing, nothing added; order preserved; stamp and signature notes present; no leftover source-language text; correct handling of unreadable parts. Returns a structured report with severity (blocker, major, minor) and block IDs. Blockers send the job back to the Translator or Proofreader (max 2 loops, then flag for human). | QA report |
| 4 | Formatter agent | Decides layout from the content: headings, field/value tables, numbered lists, signature blocks, page breaks, what is repeated once at the end. Output is layout instructions in the document model, not raw docx XML. | Layout-annotated model |
| 5 | Builder (deterministic code, not an LLM) | Renders the Word and PDF files from the model. Never let an LLM write binary or XML directly. | .docx, .pdf, zip |
| 6 | Final Review (human gate) | A certified translator reviews side by side, edits, and approves. Only after approval does the stamp and signature get applied to the final output. | Released files |

Pipeline rules:

- Agents 1 to 4 run per document; for long documents split into chunks (by page or section) with an overlapping
  context window and a shared glossary so terminology stays consistent across chunks.
- Run independent documents in a batch in parallel; run stages of one document sequentially.
- Every agent call stores prompt, response, model, tokens, cost, duration, and retry count in the audit log.
- Structured outputs only (JSON validated with a schema). On invalid output, retry with the validation error fed back.
- Add a Glossary agent/step at the start of each batch: extract recurring names, acronyms and terms across all
  documents in the batch, let the user confirm them once, then pass the glossary to all agents.

### 3.1 Technology choices for the AI layer (mandatory)

Use established frameworks where they add real value, and keep the agent logic itself explicit and auditable.

Frameworks to use:

- **LangGraph** for orchestration of the agent pipeline: each agent is a graph node, the QA-to-Translator/Proofreader
  loop is a conditional edge with a loop limit, batch documents run as parallel branches, and the human Final Review
  is an interrupt (human-in-the-loop) that pauses the graph until the certified translator approves. Use its
  checkpointer (PostgreSQL) so a job survives restarts and resumes at the failed stage, and so every state is
  replayable for the audit log.
- **Anthropic Python SDK** (Messages API) for every model call, used inside the graph nodes (through
  langchain-anthropic only if LangGraph needs it; otherwise call the SDK directly).
- **Pydantic** for the document model and all agent contracts.
- **Claude Agent SDK** as an optional sub-agent inside the Intake node, for hard scans: it can crop, zoom and re-read
  unclear or stamp-covered regions on its own with a tool set limited to image crop, OCR and page render.
- **Langfuse** (self-hostable) for tracing, prompt versioning and cost tracking, in addition to our own audit table.
- **Temporal** is the allowed upgrade path if job volume or durability needs outgrow LangGraph checkpointing; keep
  stages idempotent so the move needs no rewrite.

Frameworks not to use: CrewAI, AutoGen and LangChain chains or agents (LCEL pipelines, ReAct agents). They hide
prompts and control flow; LangGraph is used only as a graph and state engine, and every prompt stays in our own
versioned prompt files.

- One agent = one module (one graph node) with its own system prompt file (versioned), input and output schema,
  model setting, and retry policy.
- **Structured output:** use tool use with a JSON schema to force valid output. Define the document model and every
  agent contract in Pydantic. On validation failure, feed the error back and retry (max 2), then flag the block for
  human review.
- **Vision and PDF input:** the Intake agent sends page images to Claude to read stamps, handwriting and stamp-covered
  text. Tesseract OCR runs first as a cheap draft; Claude vision verifies low-confidence regions.
- **Prompt caching:** cache the long, stable parts (language profile style guide, glossary, rules) so chunks and
  documents reuse them.
- **Batch API:** use it for non-urgent bulk jobs (a "bulk, lower cost" option on the new-job screen); use normal calls
  for urgent jobs.
- **Models:** configurable per agent in admin settings. Default to the strongest available model for Translator and
  QA, and a faster, cheaper one for Intake classification and Formatter checks. Never hard-code a model name in code;
  read it from settings.
- **Streaming and progress:** stream long outputs and publish stage events (WebSocket or server-sent events) to the
  pipeline view.
- **Rate limits and resilience:** exponential backoff with jitter, per-job concurrency limits, idempotent stage retries
  so a crashed job resumes at the failed stage.
- **Execution:** run the LangGraph graphs inside Celery or RQ workers with Redis, so many jobs run in parallel. Design
  the stages as idempotent steps.
- **Observability:** log every call (agent, prompt version, model, tokens in and out, cached tokens, cost, latency,
  retries) to our own audit table, and send traces to Langfuse.
- **Documents are built by ordinary code, never by the model:** python-docx (plus direct XML where needed) for Word,
  LibreOffice headless for PDF conversion, pdftoppm for rendering, pypdf for merging, tesseract for OCR.
- **Abstraction for testing:** wrap the Anthropic client behind a small interface so a mock client can replay recorded
  responses in tests, and so the model provider could be swapped later without touching the agents.

## 4. Structured document model (core design)

The model is language-neutral: it stores source_language, target_language and a direction per block.

Define a JSON schema that every agent reads and writes. Minimum block types:

- heading, paragraph, numbered_item, bullet
- table (rows, cells, header flag, column widths) and kv_table for field/value pairs
- note for descriptions of stamps, seals, signatures, logos, photos, barcodes, handwriting (rendered inside // //)
- page_break, signature_block
- unreadable (reason: illegible, covered by stamp, truncated)

Each block carries: id, source_page, source_text, translated_text, status, confidence, flags, and history (who changed
it and why). Inline runs mark isolated tokens (identifiers, numbers, dates, emails, URLs) so the RTL builder can wrap
them correctly.

## 5. Translation and formatting rules (bake into the agent prompts and the Builder)

These come from real certified work and are mandatory:

- Do not add any text of your own: no explanations, no headings that are not in the source. Keep source order and
  structure. Truncated source text is marked as truncated, never completed.
- Describe every stamp, seal, signature, hologram, revenue stamp, barcode label, photo and handwritten note inside
  // // in the target language, including legible text, numbers, colours and shape. Mark unreadable or hidden parts
  as unclear or covered. Never guess.
- If the same stamp or signature with identical wording repeats across pages, describe it once at the end of the
  document under a short heading. Stamps that differ per page are described at the end of their own page.
- Remove page numbers and paper serial lines. Let text flow continuously and join sentences split by page breaks.
  Keep a page break only before an apostille.
- When the document repeats the same text in several languages, translate it once.
- Script and language handling comes from the Language Profile (5.1), never from hard-coded text. Typical behaviours
  the profile controls: text direction, fonts, justification, digit style (matching the source's digits unless the
  profile says otherwise), quotation marks, date and number conventions (kept as written in the source unless the
  user asks to localise), and how names are handled.
- **Names and terms:** when the target script differs from the source (for example Latin to Arabic, Cyrillic to
  Latin), transliterate names of people, companies, streets and places into the target script using the profile's
  transliteration standard (for example BGN/PCGN or ISO 9, or the common Arabic rendering). When the script is the
  same (French to English, English to German), keep names as written and translate only the descriptive parts.
  Translate stamp wording. Keep as written only identifiers: ID and tax numbers, serial and reference numbers,
  verification codes, URLs, emails, hashes. Acronyms are translated, expanded or transliterated according to the
  profile and the per-job glossary, so the same acronym is always rendered the same way. For targets with a
  no-foreign-script rule (for example Arabic only), do not leave source-script text next to the translation.
- **Mixed direction text:** when the target is right-to-left (Arabic, Hebrew, Persian, Urdu), wrap every Latin or
  numeric run in bidi isolates (LRM/RLM handling) so numbering, dates and identifiers never reorder. When the target is
  left-to-right but the source contains right-to-left names or identifiers, isolate those runs the same way.
- Keep the layout organised: tables for field/value data, clean headings, readable font sizes, numbering that
  survives RTL.
- Make a per-job disclosure list automatically (not inside the document): parts hidden under stamps, unreadable parts,
  duplicate multilingual lines translated once, and a warning that the stamp overlay may cover a few lines on dense
  source pages.

### 5.1 Language Profiles

Each supported language has a profile stored in the database and editable by admins, with at least:

- code, display name, script, direction (ltr or rtl)
- Word font (complex-script font for rtl scripts, east-asian font for Chinese, Japanese, Korean) and the PDF fallback
  font (embedded open font such as Noto or Amiri)
- body size, line spacing, justification rule
- digit style, quotation marks, list and numbering style
- transliteration standard and name-handling rule
- OCR pack name (tesseract) and vision fallback notes
- the style guide text injected into Translator, Proofreader and QA prompts (formal legal register, terminology
  conventions, how to write "stamp", "seal", "signature" notes, common legal formulae)
- default labels used by the Builder (for example the word used in stamp notes and "unreadable" markers)

Ship profiles for the languages listed in 0.1, with Arabic (Sakkal Majalla 14pt Word, Amiri PDF fallback, justified,
bidiVisual tables) and English (Times New Roman) fully tuned from the rules in this brief.

### 5.2 Language Pair Settings

An optional override layer per pair (source to target), because some behaviour depends on the pair and not on one
language alone: default template, transliteration rule, glossary memory, which agent models to use, whether the
target must contain no source-script text, and any client-specific conventions. If no override exists, the two
profiles are combined.

## 6. Output builder requirements

**Word**

- Build on the uploaded office .docx template; preserve header, footer, contact block, page size and margins. Allow
  several templates and bind them to a language pair or to a target language (for example one for Arabic output and
  another for English output). If the template's header or footer is in a different direction from the target, keep
  it as is.
- Put signature and stamp images in the footer of every page, with the bottom margin large enough that text never
  overlaps them.
- Direction is driven by the target profile. For right-to-left targets use a real RTL implementation: bidi paragraphs,
  bidiVisual tables, correct run language and complex-script font settings. For left-to-right targets use normal
  paragraphs and tables. For Chinese, Japanese and Korean set the east-asian font and language tags. Set the correct
  proofing language on every run.
- Use python-docx plus direct XML where needed (or docx-js if you judge it better; justify the choice).

**PDF**

- Convert the Word file with LibreOffice headless so Word and PDF match.
- Render source pages (pdftoppm, around 130 dpi), rotate landscape pages upright, fit to the translation page size
  (right-to-left sources work the same way), and draw stamp and signature at the same physical size as in the
  translation footer. Choose the position by finding the least ink overlap so the stamp covers as little source text
  as possible.
- Embed source pages as JPEG (quality about 80) to keep file size reasonable. Target: a 24-page scanned source should
  not exceed about 12 MB.
- Merge with pypdf or equivalent into the single integrated PDF.
- After merging, run an automated check: the page count equals translation pages plus source pages, and every page
  has the stamp and signature in place (detect them by image position or a hidden marker). The release is blocked if
  any page fails.

**Zip**

- One folder per batch, files named NN_Title_<TargetLangCode>.docx and .pdf (for example _AR, _EN, _DE), plus a
  disclosures.txt.

## 7. Web application

Suggested stack (change it only with a reason):

- **Backend:** Python 3.12, FastAPI, Celery or RQ with Redis for the job queue, PostgreSQL, SQLAlchemy, Alembic.
- **Frontend:** React with TypeScript, Vite, Tailwind, full RTL support in the UI itself, with an interface language
  switch (English and Arabic first, others addable through translation files). The review editor must show each side
  in its own direction, so an Arabic source with an English target (or the reverse) displays correctly side by side.
- **Storage:** S3-compatible object storage (MinIO locally).
- **Real-time progress:** WebSocket or server-sent events.
- **Packaging:** Docker Compose for local and production; include LibreOffice, tesseract with OCR language packs for
  every supported language (installable on demand from the admin screen), poppler, and the fonts for every language
  profile (Noto families, Amiri, and a CJK font) in the image.

Screens:

- **New job:** drag and drop one or many files; choose source language (or auto-detect) and target language from the
  full list, with a per-document override inside a batch and a swap button; remember recent pairs; stamp selector
  (required, no default); document type hint; optional notes; template choice.
- **Pipeline view:** live status per document and per agent (queued, running, done, needs attention), with timings and
  cost.
- **Side-by-side review editor:** source page image on one side, translated blocks on the other, block-level flags
  from Proofreader and QA, accept or reject changes, edit text, re-run a single agent on a selected block, glossary
  panel.
- **Preview:** rendered PDF preview exactly as it will be released, with the chosen stamp.
- **Release:** approve, generate Word and PDF and zip, download, and view the disclosure list.
- **Admin:** users and roles (admin, certified translator, reviewer), asset library (templates, stamps, signatures),
  glossary memory per client, agent prompts and model settings (versioned), usage and cost dashboard.
- **Audit log** per job.

## 8. Safety, confidentiality and control

- Documents are confidential legal files: encrypt at rest and in transit, per-client access control, configurable
  retention with auto-deletion, no document content in application logs.
- Store the Anthropic API key only in server environment variables; never expose it to the browser.
- The stamp and signature are applied only after a certified translator approves the final review. Block the release
  if any QA blocker is open. Record who approved and when.
- Stamp images may only be used by the user they belong to or by admins.
- Show the confidence and unreadable flags prominently: the system must never silently guess.

## 9. Quality and testing

- Unit tests for the builder in both directions (numbering, bidi isolation, tables, mixed-direction runs), stamp
  placement, and schema validation. Run the same tests across a matrix of pairs, at minimum: English to Arabic, Arabic
  to English, French to English, English to German, Spanish to Arabic, Russian to English.
- A golden test set per language pair: sample source documents with approved translations, starting with English to
  Arabic; the harness must accept a new pair by just adding a folder. Build a regression harness that runs the
  pipeline and scores the output (number/date/name match rate, leftover Latin text, missing blocks) and fails the build
  below a threshold.
- Automated scan for leftover source-language words (for example Latin text in Arabic output, or French in English
  output) and stray punctuation in the target text, using the profile's allow-list for identifiers.
- Render every output page to an image in tests and check that nothing overlaps the stamp area.
- Include a mock Claude client so the whole pipeline can run offline in tests.

## 10. Phases and deliverables

- **Phase 1, core engine (CLI):** document model, Builder (docx and PDF with stamp choice), source-page stamping.
  Prove it by regenerating one existing certified translation from a hand-written model file.
- **Phase 2, agents and language profiles:** the Language Profile system, Intake with OCR, Translator, Proofreader, QA
  loop, Formatter, glossary step. Run end to end from the command line on sample documents in at least three
  different pairs, including one right-to-left source and one left-to-right to left-to-right pair.
- **Phase 3, web app:** upload, stamp selector, pipeline view, queue, downloads, zip, auth.
- **Phase 4, review editor and release gate:** side-by-side editor, tracked changes, approvals, audit log.
- **Phase 5, hardening:** admin screens, cost dashboard, retention, backups, Docker packaging, documentation,
  regression suite.

At the end of each phase: what was built, how to run it, what is tested, and what is still missing. Write a README,
an architecture document, and a prompt-versioning guide.

If any requirement above is not feasible as written, say so plainly and propose the closest alternative instead of
silently dropping it.
