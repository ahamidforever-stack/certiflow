import { forwardRef, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Link2, Link2Off, Maximize2, ZoomIn, ZoomOut } from "lucide-react";
import { api, type DocBlock } from "../../api";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import { hasBlocker, openFlags } from "./helpers";

interface Props {
  jobId: string; doc: string; lang: string; blocks: DocBlock[]; pages: number[];
  selected: string | null; hovered: string | null; follow: boolean;
  onFollow: (v: boolean) => void; onHover: (id: string | null) => void; onPick: (id: string) => void;
}

// The scanned source pages with a box over every block. Boxes are coloured by what needs checking.
const SourcePane = forwardRef<HTMLDivElement, Props>(function SourcePane(
  { jobId, doc, lang, blocks, pages, selected, hovered, follow, onFollow, onHover, onPick }, scrollRef) {
  const { t } = useI18n();
  const [zoom, setZoom] = useState(100);
  const [page, setPage] = useState(pages[0] ?? 1);
  const innerRef = useRef<HTMLDivElement | null>(null);

  // Which page is in view (for the page counter).
  useEffect(() => {
    const root = innerRef.current;
    if (!root) return;
    const io = new IntersectionObserver((entries) => {
      const vis = entries.filter((e) => e.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (vis) setPage(Number((vis.target as HTMLElement).dataset.page));
    }, { root, threshold: [0.25, 0.5, 0.75] });
    root.querySelectorAll("[data-page]").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [pages, zoom]);

  const goPage = (n: number) => document.getElementById(`src-page-${n}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  const idx = pages.indexOf(page);

  return (
    <section className="flex h-full min-h-0 flex-col bg-slate-100/70" aria-label={t("rvSourcePane")}>
      <header className="flex h-11 shrink-0 items-center gap-1 border-b border-slate-200/80 bg-surface px-2">
        <h2 className="px-1.5 text-sm font-medium text-slate-700">
          {t("rvSourcePane")} <span className="font-mono text-[11px] uppercase text-slate-400" dir="ltr">{lang}</span>
        </h2>
        <div className="ms-auto flex items-center gap-0.5">
          <button className="icon-btn h-8 w-8" aria-label={t("edPrevPage")} disabled={idx <= 0} onClick={() => goPage(pages[idx - 1])}>
            <ChevronLeft className="h-4 w-4 rtl:-scale-x-100" /></button>
          <span className="min-w-[3.25rem] text-center text-xs tabular-nums text-slate-600" dir="ltr">{pages.length ? t("edPageOf", { n: page, total: pages.length }) : "–"}</span>
          <button className="icon-btn h-8 w-8" aria-label={t("edNextPage")} disabled={idx < 0 || idx >= pages.length - 1} onClick={() => goPage(pages[idx + 1])}>
            <ChevronRight className="h-4 w-4 rtl:-scale-x-100" /></button>
          <span className="mx-1 h-4 w-px bg-slate-200" />
          <button className="icon-btn h-8 w-8" aria-label={t("edZoomOut")} disabled={zoom <= 50} onClick={() => setZoom((z) => Math.max(50, z - 25))}><ZoomOut className="h-4 w-4" /></button>
          <button className="min-w-[3rem] rounded-md px-1 py-1 text-xs tabular-nums text-slate-600 hover:bg-slate-100" title={t("edFit")} onClick={() => setZoom(100)} dir="ltr">{zoom}%</button>
          <button className="icon-btn h-8 w-8" aria-label={t("edZoomIn")} disabled={zoom >= 250} onClick={() => setZoom((z) => Math.min(250, z + 25))}><ZoomIn className="h-4 w-4" /></button>
          <button className="icon-btn hidden h-8 w-8 xl:inline-flex" aria-label={t("edFit")} onClick={() => setZoom(100)}><Maximize2 className="h-3.5 w-3.5" /></button>
          <span className="mx-1 h-4 w-px bg-slate-200" />
          <button onClick={() => onFollow(!follow)} title={t("edFollowHint")} aria-pressed={follow}
            className={cn("flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs font-medium transition",
              follow ? "bg-brand-50 text-brand-600" : "text-slate-500 hover:bg-slate-100")}>
            {follow ? <Link2 className="h-3.5 w-3.5" /> : <Link2Off className="h-3.5 w-3.5" />}<span className="hidden xl:inline">{t("edFollow")}</span>
          </button>
        </div>
      </header>

      <div ref={(el) => { innerRef.current = el; if (typeof scrollRef === "function") scrollRef(el); else if (scrollRef) scrollRef.current = el; }}
        className="min-h-0 flex-1 overflow-auto p-4">
        {pages.length === 0 && <p className="p-4 text-sm text-slate-500">{t("rvNoPages")}</p>}
        <div className="mx-auto space-y-4" style={{ width: `${zoom}%`, maxWidth: zoom <= 100 ? "56rem" : undefined }}>
          {pages.map((n) => (
            <figure key={n} id={`src-page-${n}`} data-page={n} className="scroll-mt-3">
              <figcaption className="mb-1.5 text-[11px] text-slate-500">{t("rvPage")} <bdi>{n}</bdi></figcaption>
              {/* The page image is not mirrored in RTL, so boxes are positioned from the physical left edge. */}
              <div className="relative overflow-hidden rounded-[3px] bg-white shadow-paper ring-1 ring-slate-900/5" dir="ltr">
                <img src={api.pageImage(jobId, doc, n)} alt={`${t("rvPage")} ${n}`} className="block w-full select-none" loading="lazy" draggable={false} />
                {blocks.filter((b) => b.source_page === n && b.bbox?.length === 4).map((b) => {
                  const [x0, y0, x1, y1] = b.bbox!;
                  const on = selected === b.id;
                  const hover = hovered === b.id;
                  const tone = hasBlocker(b) ? "border-red-500/80 bg-red-500/[0.07]" : openFlags(b).length ? "border-amber-500/80 bg-amber-400/[0.08]" : "border-transparent";
                  return (
                    <button key={b.id} id={`src-${b.id}`} aria-label={`${b.id}`} title={b.id}
                      onClick={() => onPick(b.id)} onMouseEnter={() => onHover(b.id)} onMouseLeave={() => onHover(null)}
                      className={cn("absolute rounded-[3px] border-2 transition-colors duration-150 focus-visible:ring-0",
                        on ? "border-brand-500 bg-brand-500/[0.12] shadow-[0_0_0_4px_rgb(var(--c-brand-500)/0.15)]" : hover ? "border-brand-400/80 bg-brand-500/[0.06]" : cn(tone, "hover:border-brand-400/60"))}
                      style={{ left: `${x0 / 10}%`, top: `${y0 / 10}%`, width: `${(x1 - x0) / 10}%`, height: `${(y1 - y0) / 10}%` }} />
                  );
                })}
              </div>
            </figure>
          ))}
        </div>
      </div>
    </section>
  );
});

export default SourcePane;
