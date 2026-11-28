import type { Job } from "../api";

// The seven steps a certified translation goes through, as shown to people (the seal ring, the desk cards).
export const STEPS = ["stepRead", "stepGlossary", "stepTranslate", "stepProofread", "stepCheck", "stepReview", "stepSeal"] as const;

export type Tone = "run" | "you" | "fail" | "done";
export interface Progress { done: number; active: number | null; tone: Tone }

// Pipeline stage of the job -> number of finished steps.
const STAGE_DONE: Record<string, number> = { queued: 0, intake: 1, translated: 3, proofread: 4, qa: 4, formatted: 5, reviewed: 6 };

export function progressOf(job: Pick<Job, "status" | "stage">): Progress {
  const fromStage = Math.min(STAGE_DONE[job.stage] ?? 0, 6);
  switch (job.status) {
    case "released": return { done: 7, active: null, tone: "done" };
    case "releasing": return { done: 6, active: 6, tone: "run" };
    case "waiting_review": return { done: 5, active: 5, tone: "you" };
    case "waiting_glossary": return { done: 1, active: 1, tone: "you" };
    case "reworking": return { done: 5, active: 5, tone: "run" };
    case "failed": case "blocked": return { done: fromStage, active: fromStage, tone: "fail" };
    case "queued": return { done: 0, active: 0, tone: "run" };
    default: return { done: fromStage, active: fromStage, tone: "run" };
  }
}

export type Bucket = "needs" | "progress" | "done";
export function bucketOf(job: Job): Bucket {
  if (["waiting_glossary", "waiting_review", "failed", "blocked"].includes(job.status)) return "needs";
  if (job.status === "released") return "done";
  return "progress";
}

/** The one action a person takes next on a job that needs them. */
export function nextAction(job: Job): { label: string; to: string } {
  if (job.status === "waiting_glossary") return { label: "actConfirmGlossary", to: `/jobs/${job.id}#glossary` };
  if (job.status === "waiting_review") {
    const first = job.documents?.[0]?.key;
    return { label: "actReview", to: first ? `/jobs/${job.id}/review/${first}` : `/jobs/${job.id}` };
  }
  if (job.status === "failed" || job.status === "blocked") return { label: "actRetry", to: `/jobs/${job.id}` };
  return { label: "actOpen", to: `/jobs/${job.id}` };
}

export const jobTime = (j: Job) => new Date(j.approved_at || j.created_at);

/** "Today", "Yesterday" or "Earlier", in the browser's time zone. */
export function dayGroup(d: Date, now = new Date()): "navToday" | "navYesterday" | "navEarlier" {
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (d.getTime() >= start) return "navToday";
  if (d.getTime() >= start - 86_400_000) return "navYesterday";
  return "navEarlier";
}

export function timeAgo(d: Date, t: (k: string, v?: Record<string, string | number>) => string, now = Date.now()): string {
  const s = Math.max(0, (now - d.getTime()) / 1000);
  if (s < 60) return t("ago_now");
  if (s < 3600) return t("ago_min", { n: Math.floor(s / 60) });
  if (s < 86_400) return t("ago_hour", { n: Math.floor(s / 3600) });
  return t("ago_day", { n: Math.floor(s / 86_400) });
}

export function greetingKey(h = new Date().getHours()) {
  return h < 12 ? "greetMorning" : h < 18 ? "greetAfternoon" : "greetEvening";
}
