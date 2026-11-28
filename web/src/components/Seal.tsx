import { useId } from "react";
import { STEPS, type Progress } from "../lib/jobs";
import { useI18n } from "../i18n";
import { cn } from "../lib/cn";

// The CertiFlow signature: a job's seven steps drawn as a ring around a seal. As the agents and the translator
// work, the ring fills; when the translation is certified the ring becomes a gold stamp.

/** Scalloped stamp edge (like an embossed seal) as an SVG path centred on (c, c). */
function scallop(c: number, r: number, bumps = 18, depth = 0.07) {
  const pts: string[] = [];
  const n = bumps * 8;
  for (let i = 0; i <= n; i++) {
    const a = (i / n) * Math.PI * 2;
    const rr = r * (1 - depth / 2 + (depth / 2) * Math.cos(a * bumps));
    pts.push(`${(c + rr * Math.cos(a)).toFixed(2)},${(c + rr * Math.sin(a)).toFixed(2)}`);
  }
  return `M${pts.join("L")}Z`;
}

function arc(c: number, r: number, a0: number, a1: number) {
  const p = (a: number) => `${(c + r * Math.cos(a)).toFixed(2)} ${(c + r * Math.sin(a)).toFixed(2)}`;
  return `M ${p(a0)} A ${r} ${r} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${p(a1)}`;
}

const TONE_STROKE: Record<Progress["tone"], string> = {
  run: "stroke-brand-500", you: "stroke-seal-500", fail: "stroke-red-500", done: "stroke-seal-500",
};

export function SealRing({ progress, size = 40, className, label = true }: { progress: Progress; size?: number; className?: string; label?: boolean }) {
  const { t } = useI18n();
  const id = useId();
  const sw = Math.max(2, size / 11);
  const c = size / 2;
  const r = c - sw / 2 - 0.5;
  const n = STEPS.length;
  const gap = size < 28 ? 0.32 : 0.16; // radians
  const certified = progress.tone === "done";
  const stepName = progress.active != null ? t(STEPS[progress.active]) : t("stepSeal");
  const aria = certified ? t("st_released") : t("progressOf", { n: (progress.active ?? progress.done) + 1, total: n, step: stepName });
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className={cn("shrink-0", className)}
      role={label ? "img" : undefined} aria-label={label ? aria : undefined} aria-hidden={label ? undefined : true}>
      {label && <title>{aria}</title>}
      {certified ? (
        <g>
          <path d={scallop(c, c - 0.5)} className="fill-seal-500" />
          <circle cx={c} cy={c} r={c * 0.68} className="fill-none stroke-white/60" strokeWidth={Math.max(0.75, size / 48)} strokeDasharray={size > 30 ? "1.5 2" : undefined} />
          <path d={`M ${c - c * 0.32} ${c + c * 0.02} l ${c * 0.22} ${c * 0.22} l ${c * 0.42} ${-c * 0.46}`}
            className="fill-none stroke-white" strokeWidth={Math.max(1.6, size / 14)} strokeLinecap="round" strokeLinejoin="round" />
        </g>
      ) : (
        <g>
          {STEPS.map((_, i) => {
            const a0 = -Math.PI / 2 + (i / n) * Math.PI * 2 + gap / 2;
            const a1 = -Math.PI / 2 + ((i + 1) / n) * Math.PI * 2 - gap / 2;
            const isDone = i < progress.done;
            const isActive = progress.active === i;
            return (
              <path key={i} d={arc(c, r, a0, a1)} strokeWidth={sw} strokeLinecap="round" fill="none"
                className={cn(isDone ? "stroke-brand-600 dark:stroke-brand-500" : isActive ? TONE_STROKE[progress.tone] : "stroke-slate-200",
                  isActive && progress.tone !== "fail" && "animate-pulse")} />
            );
          })}
          {size >= 36 && (
            <g aria-hidden>
              <defs><clipPath id={`${id}c`}><circle cx={c} cy={c} r={r - sw * 1.2} /></clipPath></defs>
              <text x={c} y={c} textAnchor="middle" dominantBaseline="central" clipPath={`url(#${id}c)`}
                className={cn("font-sans font-semibold", progress.tone === "you" ? "fill-seal-600" : progress.tone === "fail" ? "fill-red-600" : "fill-slate-600")}
                style={{ fontSize: size * 0.28 }}>
                {progress.tone === "fail" ? "!" : `${Math.min(progress.done + 1, n)}`}
              </text>
            </g>
          )}
        </g>
      )}
    </svg>
  );
}

/** The app mark: a navy seal with a gold scalloped rim and a check. */
export function SealMark({ size = 32, className }: { size?: number; className?: string }) {
  const c = size / 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className={cn("shrink-0", className)} aria-hidden>
      <path d={scallop(c, c - 0.5, 16, 0.09)} className="fill-seal-500" />
      <circle cx={c} cy={c} r={c * 0.74} className="fill-brand-600" />
      <circle cx={c} cy={c} r={c * 0.6} className="fill-none stroke-seal-300/70" strokeWidth={Math.max(0.6, size / 60)} />
      <path d={`M ${c - c * 0.3} ${c + c * 0.02} l ${c * 0.2} ${c * 0.2} l ${c * 0.4} ${-c * 0.44}`}
        className="fill-none stroke-white" strokeWidth={Math.max(1.6, size / 13)} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
