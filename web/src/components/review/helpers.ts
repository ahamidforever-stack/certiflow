import type { DocBlock } from "../../api";

// Shared review-editor logic (no UI). An "item to check" is anything the translator must look at before approval.

export const AGENTS = new Set(["translator", "proofreader", "qa", "formatter"]);
export type Draft = { text?: string; cells?: Record<string, string> };
export type SaveState = "saved" | "saving" | "dirty" | "error";
export type Filter = "all" | "issues" | "changes" | "edited";

export const pendingChanges = (b: DocBlock) =>
  (b.history || []).map((h, i) => ({ h, i }))
    .filter(({ h }) => AGENTS.has(h.actor) && h.old != null && h.new != null && h.old !== h.new && !h.review);
export const openFlags = (b: DocBlock) => (b.flags || []).map((f, i) => ({ f, i })).filter(({ f }) => !f.resolved);
export const hasBlocker = (b: DocBlock) => openFlags(b).some(({ f }) => f.severity === "blocker");
export const hasWarning = (b: DocBlock) => openFlags(b).some(({ f }) => f.severity !== "blocker");
export const needsLook = (b: DocBlock) => openFlags(b).length > 0 || pendingChanges(b).length > 0;

export type Tone = "blocker" | "warning" | "change" | "edited" | "none";
export function toneOf(b: DocBlock, edited: boolean): Tone {
  if (hasBlocker(b)) return "blocker";
  if (hasWarning(b)) return "warning";
  if (pendingChanges(b).length) return "change";
  if (edited) return "edited";
  return "none";
}

export const TONE_BAR: Record<Tone, string> = {
  blocker: "border-s-red-500", warning: "border-s-amber-400", change: "border-s-brand-400", edited: "border-s-seal-400", none: "border-s-transparent",
};
export const TONE_DOT: Record<Tone, string> = {
  blocker: "bg-red-500", warning: "bg-amber-400", change: "bg-brand-400", edited: "bg-seal-400", none: "bg-slate-300",
};

/** True when the key event comes from a place where the user types. */
export const isTyping = (e: KeyboardEvent) => {
  const el = e.target as HTMLElement | null;
  return !!el && (el.tagName === "TEXTAREA" || el.tagName === "INPUT" || el.tagName === "SELECT" || el.isContentEditable);
};
