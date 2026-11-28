import { useMemo } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, FileUp, RotateCw } from "lucide-react";
import type { Job } from "../api";
import { useAuth } from "../App";
import { useI18n } from "../i18n";
import { useJobs } from "../lib/useJobs";
import { STEPS, bucketOf, greetingKey, jobTime, nextAction, progressOf, timeAgo } from "../lib/jobs";
import { SealMark, SealRing } from "../components/Seal";
import { StatusChip } from "../components/Status";
import { cn } from "../lib/cn";

// The desk: what needs the translator now, what the agents are doing, what was just certified.
export default function Home() {
  const { t } = useI18n();
  const { user } = useAuth();
  const { jobs, error, refresh } = useJobs();
  const g = useMemo(() => {
    const all = [...(jobs ?? [])].sort((a, b) => jobTime(b).getTime() - jobTime(a).getTime());
    return { needs: all.filter((j) => bucketOf(j) === "needs"), progress: all.filter((j) => bucketOf(j) === "progress"),
      done: all.filter((j) => bucketOf(j) === "done").slice(0, 6) };
  }, [jobs]);
  const first = (user?.name ?? "").split(/\s+/)[0];

  return (
    <div className="animate-fade-in space-y-10">
      <header className="flex flex-wrap items-end gap-4">
        <div className="min-w-0">
          <h1 className="page-title text-3xl" dir="auto">{t(greetingKey(), { name: first })}</h1>
          <p className="mt-1.5 text-[15px] text-slate-500">
            {jobs === null ? " " : g.needs.length ? t("deskSummary", { n: g.needs.length }) : t("deskSummaryNone")}
          </p>
        </div>
      </header>

      {error && jobs === null && (
        <div role="alert" className="flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          {t("loadError")}
          <button className="btn-ghost btn-sm ms-auto" onClick={refresh}><RotateCw className="h-3.5 w-3.5" />{t("retry")}</button>
        </div>
      )}

      <StartCard first={jobs !== null && jobs.length === 0} />

      {jobs === null ? <DeskSkeleton /> : jobs.length === 0 ? null : (
        <>
          <Section title={t("deskNeedsYou")} count={g.needs.length} accent>
            {g.needs.length ? (
              <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">{g.needs.map((j) => <NeedsCard key={j.id} job={j} />)}</div>
            ) : <Quiet>{t("deskAllClear")}</Quiet>}
          </Section>

          <Section title={t("deskInProgress")} count={g.progress.length}>
            {g.progress.length ? (
              <div className="panel divide-y divide-slate-100">{g.progress.map((j) => <RunningRow key={j.id} job={j} />)}</div>
            ) : <Quiet>{t("deskNoneRunning")}</Quiet>}
          </Section>

          <Section title={t("deskReleased")} action={<Link to="/jobs" className="text-sm text-brand-500 hover:underline">{t("navAllJobs")}</Link>}>
            {g.done.length ? (
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{g.done.map((j) => <ReleasedTile key={j.id} job={j} />)}</div>
            ) : <Quiet>{t("deskNoneReleased")}</Quiet>}
          </Section>
        </>
      )}
    </div>
  );
}

function StartCard({ first }: { first: boolean }) {
  const { t } = useI18n();
  return (
    <Link to="/new"
      className="group relative flex items-center gap-5 overflow-hidden rounded-2xl border border-dashed border-slate-300 bg-surface px-6 py-6 transition hover:border-brand-400 hover:shadow-paper sm:px-8">
      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600 transition group-hover:bg-brand-600 group-hover:text-white">
        <FileUp className="h-6 w-6" />
      </span>
      <span className="min-w-0">
        <span className="block font-serif text-lg text-slate-900">{t(first ? "deskFirstTitle" : "deskNewTitle")}</span>
        <span className="mt-0.5 block max-w-2xl text-sm leading-relaxed text-slate-500">{t(first ? "deskFirstHint" : "deskNewHint")}</span>
      </span>
      <ArrowRight className="ms-auto hidden h-5 w-5 shrink-0 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-brand-500 rtl:-scale-x-100 rtl:group-hover:-translate-x-0.5 sm:block" />
      <SealMark size={150} className="pointer-events-none absolute -top-16 end-16 opacity-[0.05] dark:hidden" />
    </Link>
  );
}

function Section({ title, count, accent, action, children }: { title: string; count?: number; accent?: boolean; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section>
      <div className="mb-3 flex items-center gap-2">
        <h2 className="eyebrow">{title}</h2>
        {!!count && <span className={cn("rounded-full px-1.5 text-[11px] font-semibold leading-5", accent ? "bg-seal-100 text-seal-700" : "bg-slate-200/70 text-slate-600")}>{count}</span>}
        <span className="ms-2 h-px flex-1 bg-slate-200" />
        {action}
      </div>
      {children}
    </section>
  );
}

const Quiet = ({ children }: { children: React.ReactNode }) => <p className="py-2 text-sm text-slate-500">{children}</p>;

function Meta({ job }: { job: Job }) {
  const { t } = useI18n();
  return (
    <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-500">
      {job.client && <bdi className="truncate">{job.client}</bdi>}
      {job.client && <span aria-hidden>·</span>}
      <bdi className="font-mono uppercase" dir="ltr">{job.source_language} → {job.target_language}</bdi>
      <span aria-hidden>·</span>
      <span>{timeAgo(jobTime(job), t)}</span>
    </div>
  );
}

function NeedsCard({ job }: { job: Job }) {
  const { t } = useI18n();
  const p = progressOf(job);
  const act = nextAction(job);
  const failed = p.tone === "fail";
  return (
    <article className={cn("card flex min-w-0 flex-wrap items-center gap-x-4 gap-y-3 p-4 transition hover:-translate-y-px hover:shadow-float",
      failed ? "border-red-200" : "border-seal-200/80")}>
      <SealRing progress={p} size={48} />
      <div className="min-w-0 flex-1">
        <Link to={`/jobs/${job.id}`} className="block truncate font-medium text-slate-900 hover:underline"><bdi>{job.title}</bdi></Link>
        <Meta job={job} />
        <div className="mt-2"><StatusChip status={job.status} /></div>
      </div>
      <Link to={act.to} className={cn(failed ? "btn-ghost" : "btn-primary", "btn-sm w-full shrink-0 sm:w-auto")}>
        {t(act.label)}<ArrowRight className="h-3.5 w-3.5 rtl:-scale-x-100" />
      </Link>
    </article>
  );
}

function RunningRow({ job }: { job: Job }) {
  const { t } = useI18n();
  const p = progressOf(job);
  return (
    <Link to={`/jobs/${job.id}`} className="flex items-center gap-4 px-4 py-3 transition first:rounded-t-xl last:rounded-b-xl hover:bg-slate-50">
      <SealRing progress={p} size={36} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-slate-900"><bdi>{job.title}</bdi></div>
        <Meta job={job} />
      </div>
      <div className="hidden w-64 shrink-0 md:block">
        <div className="flex gap-1" aria-hidden>
          {STEPS.map((s, i) => (
            <span key={s} className={cn("h-1.5 flex-1 rounded-full",
              i < p.done ? "bg-brand-600 dark:bg-brand-500" : i === p.active ? "animate-pulse bg-brand-300" : "bg-slate-200")} />
          ))}
        </div>
        <div className="mt-1.5 flex items-center gap-1.5 text-xs text-slate-600">
          <span className="relative flex h-1.5 w-1.5"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-400 opacity-60" /><span className="relative h-1.5 w-1.5 rounded-full bg-brand-500" /></span>
          {t(STEPS[p.active ?? 0])}…
        </div>
      </div>
    </Link>
  );
}

function ReleasedTile({ job }: { job: Job }) {
  const { t } = useI18n();
  return (
    <Link to={`/jobs/${job.id}`} className="panel flex items-center gap-3 p-3 transition hover:border-seal-300 hover:shadow-paper">
      <SealRing progress={progressOf(job)} size={30} />
      <div className="min-w-0">
        <div className="truncate text-sm font-medium text-slate-900"><bdi>{job.title}</bdi></div>
        <div className="text-xs text-slate-500">{timeAgo(jobTime(job), t)}</div>
      </div>
    </Link>
  );
}

function DeskSkeleton() {
  return (
    <div className="space-y-8" aria-hidden>
      {[0, 1].map((s) => (
        <div key={s}>
          <div className="skeleton mb-3 h-3 w-28" />
          <div className="grid gap-3 md:grid-cols-2">{[0, 1].map((i) => <div key={i} className="skeleton h-24 rounded-xl" />)}</div>
        </div>
      ))}
    </div>
  );
}
