import { AlertTriangle, Check, X } from "lucide-react";

/** Small inline status mark (replaces ✓ ⚠ ✕ text symbols): sits on the text line, takes the text colour. */
export function Sym({ k }: { k: "ok" | "warn" | "bad" }) {
  const cls = "me-1 inline-block h-3.5 w-3.5 shrink-0 -translate-y-px align-middle";
  return k === "ok" ? <Check aria-hidden className={cls} strokeWidth={2.5} /> : k === "warn" ? <AlertTriangle aria-hidden className={cls} /> : <X aria-hidden className={cls} strokeWidth={2.5} />;
}
