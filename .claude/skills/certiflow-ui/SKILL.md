---
name: certiflow-ui
description: Design rules for CertiFlow web screens (React + Tailwind, English/Arabic RTL). Use before building or changing any page or component in web/src - colors, components, layout, bilingual text, states, and the review-editor patterns for Phase 4.
---

# CertiFlow UI rules

Users: certified legal translators at a Dubai office, many working in Arabic. The UI is a calm, dense work tool,
not a marketing site. Accuracy and clarity beat decoration.

## Building blocks (reuse, don't invent)
- Colors (`web/tailwind.config.js`): `brand-600` #1F3864 primary (same navy as the office house style),
  `brand-700` hover, `brand-500` links/focus, `brand-100`/`brand-50` tints, `accent-500` only for rare highlights.
  Neutrals: Tailwind `slate`. Status: `green` ok, `amber` waiting/warning, `red` error/blocker.
- Components (`web/src/index.css`): `.card`, `.btn-primary`, `.btn-ghost`, `.input`, `.label`. Add new shared
  classes there instead of repeating long class strings. Status pills: `web/src/components/Status.tsx`.
- Layout: page content `max-w-6xl mx-auto px-4`; cards with `p-5`/`p-6`; `gap-4`/`gap-6`; text `text-sm` for UI,
  `text-slate-500` for hints. One primary button per screen area.

## Bilingual + RTL (mandatory)
- Every visible string goes through `t("key")`; add the key to **both** `en` and `ar` in `web/src/i18n.tsx`.
  Arabic must be real Arabic (formal, Modern Standard), not transliteration.
- Logical classes only: `ms-/me-`, `ps-/pe-`, `start-/end-`, `text-start/text-end`, `rounded-s/e`, `border-s/e`.
  Never `ml-/mr-/pl-/pr-/left-/right-/text-left/text-right`.
- Directional icons (arrows, chevrons) flip in RTL: `rtl:rotate-180`.
- Document and user text: `dir="auto"`. In the review editor, set `dir` and `lang` from the language profile of that
  side (source vs target), not from the UI language.
- Numbers, dates, IDs, file names inside Arabic UI: wrap in `<bdi>` or `dir="ltr"` spans so they don't scramble.

## States (every data view)
- Loading: skeleton or muted "…", never a blank area. Empty: one sentence + the next action.
- Error: red-50 box with a plain message and a retry action; never raw JSON or stack traces.
- Disabled buttons explain why (hint text under them, as on New job).
- Long jobs: show live progress (SSE), never a frozen screen.

## Phase 4 review editor patterns
- Two panes: source (page image with block highlights) and translation (editable blocks). Each pane in its own
  direction. Hovering/selecting a block highlights the matching block on the other side.
- Tracked changes: insertions green underline, deletions red strike-through, accept/reject per change + "accept all".
- QA flags: badge per block (amber warning, red blocker) and a side list; blockers disable Approve with the reason shown.
- Save state always visible ("Saved" / "Saving…" / "Unsaved changes"); confirm before leaving with unsaved edits.
- Approval is a deliberate action: show the chosen stamp and a summary before the final confirm.

## Accessibility
- Visible focus (`focus:ring-2 focus:ring-brand-100`), labels tied to inputs, buttons are `<button>`, keyboard
  reachable editor actions, contrast at least AA (no light grey text on white for important info).

## Check
After a change, screenshot it in EN, AR and mobile (`certiflow-verify` step 4) and fix what looks wrong before
reporting done.
