import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Usage as UsageData } from "../api";
import { StatusChip } from "../components/Status";
import { useI18n } from "../i18n";

// Admin: model usage and cost. Numbers only (from the llm_usage table); never document text.

const RANGES = [7, 30, 90, 365] as const;
const money = (v: number) => (v > 0 && v < 0.01 ? "<$0.01" : `$${v.toFixed(2)}`);
const num = (v: number) => v.toLocaleString("en-US");
const dayLabel = (d: string) => new Date(d + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });

type Bar = { label: string; from: string; cost_usd: number; calls: number };

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card p-4">
      <div className="text-sm text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-900"><bdi dir="ltr">{value}</bdi></div>
      {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

// One series (cost over time): one brand color, no legend, tooltip on hover/focus, quiet axis.
function CostChart({ bars, calls }: { bars: Bar[]; calls: (n: number) => string }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(...bars.map((b) => b.cost_usd), 0);
  const top = max > 0 ? niceCeil(max) : 1;
  const tickEvery = Math.ceil(bars.length / 8);
  return (
    <div dir="ltr" className="relative select-none">
      <div className="flex">
        <div className="flex w-14 shrink-0 flex-col justify-between pe-2 text-end text-xs text-slate-400" style={{ height: 180 }}>
          <span>{money(top)}</span><span>{money(top / 2)}</span><span>$0</span>
        </div>
        <div className="relative flex-1">
          <div className="pointer-events-none absolute inset-0 flex flex-col justify-between" style={{ height: 180 }}>
            <div className="border-t border-slate-100" /><div className="border-t border-slate-100" /><div className="border-t border-slate-200" />
          </div>
          <div className="relative flex items-end" style={{ height: 180, gap: bars.length > 60 ? 1 : 2 }} onMouseLeave={() => setHover(null)}>
            {bars.map((b, i) => (
              <button key={b.from} type="button" aria-label={`${b.label}: ${money(b.cost_usd)}`}
                className="group relative flex h-full flex-1 items-end focus:outline-none"
                onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} onBlur={() => setHover(null)}>
                <span className={`block w-full rounded-t-[4px] ${hover === i ? "bg-brand-700" : "bg-brand-600"} group-focus-visible:ring-2 group-focus-visible:ring-brand-100`}
                  style={{ height: b.cost_usd > 0 ? `max(2px, ${(b.cost_usd / top) * 100}%)` : 0 }} />
              </button>
            ))}
          </div>
          <div className="mt-1 flex text-xs text-slate-400">
            {bars.map((b, i) => (
              <span key={b.from} className="flex-1 overflow-visible whitespace-nowrap">
                {i % tickEvery === 0 && <span className={(i / tickEvery) % 2 ? "hidden sm:inline" : ""}>{b.label}</span>}
              </span>
            ))}
          </div>
          {hover !== null && (
            <div className="pointer-events-none absolute -top-2 z-10 -translate-x-1/2 -translate-y-full rounded-md bg-slate-900 px-2.5 py-1.5 text-xs text-slate-50 shadow"
              style={{ left: `${((hover + 0.5) / bars.length) * 100}%` }}>
              <div className="font-medium">{bars[hover].label}</div>
              <div>{money(bars[hover].cost_usd)} · {calls(bars[hover].calls)}</div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function niceCeil(v: number): number {
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

export default function Usage() {
  const { t } = useI18n();
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<UsageData | null>(null);
  const [err, setErr] = useState("");
  const load = () => { setErr(""); setData(null); api.adminUsage(days).then(setData).catch((e) => setErr(e.message)); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [days]);

  const weekly = days > 90;
  const bars: Bar[] = useMemo(() => {
    if (!data) return [];
    if (!weekly) return data.by_day.map((d) => ({ label: dayLabel(d.day), from: d.day, cost_usd: d.cost_usd, calls: d.calls }));
    const out: Bar[] = [];
    data.by_day.forEach((d, i) => {
      if (i % 7 === 0) out.push({ label: dayLabel(d.day), from: d.day, cost_usd: 0, calls: 0 });
      const b = out[out.length - 1];
      b.cost_usd += d.cost_usd; b.calls += d.calls;
    });
    return out;
  }, [data, weekly]);
  const maxAgent = Math.max(...(data?.by_agent ?? []).map((a) => a.cost_usd), 0);
  const allFree = !!data && data.total.calls > 0 && data.total.cost_usd === 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold text-slate-900">{t("coTitle")}</h1>
        <div role="group" aria-label={t("coRange")} className="ms-auto inline-flex rounded-lg border border-slate-300 bg-surface p-0.5">
          {RANGES.map((r) => (
            <button key={r} aria-pressed={days === r} onClick={() => setDays(r)}
              className={`rounded-md px-3 py-1 text-sm ${days === r ? "bg-brand-600 text-white" : "text-slate-700 hover:bg-slate-50"}`}>
              {r === 365 ? t("coYear") : t("coDays", { n: r })}
            </button>
          ))}
        </div>
      </div>

      {err && (
        <div role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {err} <button className="ms-2 underline" onClick={load}>{t("retry")}</button>
        </div>
      )}
      {!data && !err && <div className="card p-5 text-sm text-slate-500">…</div>}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <Tile label={t("coToday")} value={money(data.tiles.today)} />
            <Tile label={t("coWeek")} value={money(data.tiles.week)} />
            <Tile label={t("coMonth")} value={money(data.tiles.month)} />
            <Tile label={t("coPerPage")} value={data.per_page_usd === null ? "—" : money(data.per_page_usd)}
              hint={t("coPerPageHint", { n: data.pages })} />
          </div>
          {allFree && <div className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">{t("coMockHint")}</div>}

          <section className="card p-5">
            <div className="flex flex-wrap items-baseline gap-x-3">
              <h2 className="font-semibold text-slate-900">{weekly ? t("coWeekly") : t("coDaily")}</h2>
              <span className="text-sm text-slate-500">
                {t("coTotalRange", { cost: money(data.total.cost_usd), calls: num(data.total.calls), jobs: data.total.jobs })}
              </span>
            </div>
            {data.total.calls === 0 ? <p className="mt-4 text-sm text-slate-500">{t("coEmpty")}</p> : (
              <div className="mt-8"><CostChart bars={bars} calls={(n) => t("coNCalls", { n: num(n) })} /></div>
            )}
            <details className="mt-4 text-sm">
              <summary className="cursor-pointer text-brand-500 hover:underline">{t("coShowTable")}</summary>
              <div className="mt-2 max-h-64 overflow-y-auto">
                <table className="w-full">
                  <thead className="text-xs text-slate-500"><tr>
                    <th className="py-1 text-start font-medium">{t("coDay")}</th>
                    <th className="py-1 text-end font-medium">{t("coCalls")}</th>
                    <th className="py-1 text-end font-medium">{t("coCost")}</th>
                  </tr></thead>
                  <tbody className="divide-y divide-slate-100">
                    {bars.filter((b) => b.calls > 0).map((b) => (
                      <tr key={b.from}><td className="py-1"><bdi dir="ltr">{b.from}</bdi></td>
                        <td className="py-1 text-end">{num(b.calls)}</td><td className="py-1 text-end"><bdi dir="ltr">{money(b.cost_usd)}</bdi></td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          </section>

          <div className="grid gap-4 lg:grid-cols-2">
            <section className="card p-5">
              <h2 className="font-semibold text-slate-900">{t("coByAgent")}</h2>
              {data.by_agent.length === 0 ? <p className="mt-2 text-sm text-slate-500">{t("coEmpty")}</p> : (
                <ul className="mt-3 space-y-3 text-sm">
                  {data.by_agent.map((a) => (
                    <li key={a.agent}>
                      <div className="flex flex-wrap gap-x-3">
                        <span className="font-medium text-slate-800">{t(`agent_${a.agent}`)}</span>
                        <span className="text-slate-500">{t("coNCalls", { n: num(a.calls) })}</span>
                        <span className="ms-auto font-medium text-slate-900"><bdi dir="ltr">{money(a.cost_usd)}</bdi></span>
                      </div>
                      <div className="mt-1 h-2 rounded-full bg-slate-100">
                        <div className="h-2 rounded-full bg-brand-600" style={{ width: maxAgent > 0 ? `${Math.max(1, (a.cost_usd / maxAgent) * 100)}%` : 0 }} />
                      </div>
                      <div className="mt-0.5 text-xs text-slate-500">
                        {t("coTokensIn")}: <bdi>{num(a.input_tokens)}</bdi> · {t("coTokensOut")}: <bdi>{num(a.output_tokens)}</bdi> · {t("coCached")}: <bdi>{num(a.cache_read_tokens)}</bdi>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="card p-5">
              <h2 className="font-semibold text-slate-900">{t("coByUser")}</h2>
              {data.by_user.length === 0 ? <p className="mt-2 text-sm text-slate-500">{t("coEmpty")}</p> : (
                <table className="mt-3 w-full text-sm">
                  <thead className="text-xs text-slate-500"><tr>
                    <th className="py-1 text-start font-medium">{t("usName")}</th>
                    <th className="px-2 py-1 text-end font-medium">{t("coJobs")}</th>
                    <th className="py-1 text-end font-medium">{t("coCost")}</th>
                  </tr></thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.by_user.map((u) => (
                      <tr key={u.username}>
                        <td className="py-2"><bdi>{u.name}</bdi> <span className="font-mono text-xs text-slate-500"><bdi>{u.username}</bdi></span></td>
                        <td className="px-2 py-2 text-end">{u.jobs}</td>
                        <td className="py-2 ps-2 text-end font-medium"><bdi dir="ltr">{money(u.cost_usd)}</bdi></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <h2 className="mt-6 font-semibold text-slate-900">{t("coByModel")}</h2>
              <table className="mt-2 w-full text-sm">
                <tbody className="divide-y divide-slate-100">
                  {data.by_model.map((m) => (
                    <tr key={m.model}>
                      <td className="py-1.5 font-mono text-xs"><bdi>{m.model}</bdi></td>
                      <td className="px-2 py-1.5 text-end text-slate-500">{t("coNCalls", { n: num(m.calls) })}</td>
                      <td className="py-1.5 ps-2 text-end font-medium"><bdi dir="ltr">{money(m.cost_usd)}</bdi></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          </div>

          <section className="card overflow-hidden">
            <h2 className="px-5 pt-5 font-semibold text-slate-900">{t("coTopJobs")}</h2>
            {data.top_jobs.length === 0 ? <p className="px-5 pb-5 pt-2 text-sm text-slate-500">{t("coEmpty")}</p> : (
              <div className="overflow-x-auto">
                <table className="mt-3 w-full min-w-[36rem] text-sm">
                  <thead className="bg-slate-50 text-xs text-slate-500"><tr>
                    <th className="px-5 py-2 text-start font-medium">{t("coJob")}</th>
                    <th className="px-3 py-2 text-start font-medium">{t("coStartedBy")}</th>
                    <th className="px-3 py-2 text-start font-medium">{t("usStatus")}</th>
                    <th className="px-3 py-2 text-end font-medium">{t("coPages")}</th>
                    <th className="px-5 py-2 text-end font-medium">{t("coCost")}</th>
                  </tr></thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.top_jobs.map((j) => (
                      <tr key={j.id}>
                        <td className="px-5 py-2">
                          <Link to={`/jobs/${j.id}`} className="text-brand-500 hover:underline"><bdi>{j.title}</bdi></Link>
                          <div className="font-mono text-xs text-slate-500"><bdi>{j.id}</bdi></div>
                        </td>
                        <td className="px-3 py-2"><bdi>{j.by}</bdi></td>
                        <td className="px-3 py-2"><StatusChip status={j.status} /></td>
                        <td className="px-3 py-2 text-end">{j.pages ?? "—"}</td>
                        <td className="px-5 py-2 text-end font-medium"><bdi dir="ltr">{money(j.cost_usd)}</bdi></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <p className="text-xs text-slate-500">{t("coTz", { tz: data.timezone })}</p>
        </>
      )}
    </div>
  );
}
