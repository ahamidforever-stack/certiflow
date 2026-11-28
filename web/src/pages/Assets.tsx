import { useEffect, useState } from "react";
import { api, type AssetInfo, type AssetListing, type AssetType } from "../api";
import { useI18n } from "../i18n";

// Admin: the Asset Library (certified stamps and signatures per translator, office stamp, Word templates).
// Uploads never overwrite: the server adds a new file and switches the old one off (kept in "Earlier versions").

const CHECKER = { backgroundImage: "repeating-conic-gradient(#e2e8f0 0% 25%, #fff 0% 50%)", backgroundSize: "16px 16px" };

function Img({ a, h = "h-24" }: { a: AssetInfo; h?: string }) {
  return (
    <div className={`flex ${h} items-center justify-center rounded-lg border border-slate-200 p-2`} style={CHECKER}>
      <img src={api.assetFile(a.id)} alt={a.name} className="max-h-full max-w-full object-contain" />
    </div>
  );
}

function Err({ msg }: { msg: string }) {
  return msg ? <div role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{msg}</div> : null;
}

function ImageUpload({ kind, owner, onDone, onCancel }: { kind: AssetType; owner?: string; onDone: (a: AssetInfo) => void; onCancel: () => void }) {
  const { t } = useI18n();
  const [file, setFile] = useState<File | null>(null);
  const [width, setWidth] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const id = `up-${kind}-${owner ?? "office"}`;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;
    const fd = new FormData();
    fd.append("kind", kind); fd.append("file", file);
    if (owner) fd.append("owner", owner);
    if (width.trim()) fd.append("width_mm", width.trim());
    setBusy(true); setErr("");
    try { onDone(await api.adminAddImage(fd)); } catch (x) { setErr((x as Error).message); } finally { setBusy(false); }
  };
  return (
    <form onSubmit={submit} className="mt-3 space-y-3 rounded-lg border border-brand-100 bg-brand-50/40 p-3">
      <div>
        <label className="label" htmlFor={id}>{t("asFile")}</label>
        <input id={id} type="file" accept="image/png,image/jpeg,image/tiff,image/webp" className="block w-full text-sm"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <p className="mt-1 text-xs text-slate-500">{t("asImageHint")}</p>
      </div>
      <div>
        <label className="label" htmlFor={id + "-w"}>{t("asWidth")}</label>
        <input id={id + "-w"} type="number" min={15} max={120} step={0.1} dir="ltr" className="input max-w-[8rem]"
          value={width} onChange={(e) => setWidth(e.target.value)} />
        <p className="mt-1 text-xs text-slate-500">{t("asWidthHint")}</p>
      </div>
      <Err msg={err} />
      <div className="flex gap-2">
        <button className="btn-primary" disabled={!file || busy}>{busy ? t("asWorking") : t("asUpload")}</button>
        <button type="button" className="btn-ghost" onClick={onCancel}>{t("usCancel")}</button>
      </div>
    </form>
  );
}

function Slot({ title, a, kind, owner, editable, onAdded }: { title: string; a?: AssetInfo; kind: AssetType; owner?: string;
  editable: boolean; onAdded: (a: AssetInfo) => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <div className="min-w-0 flex-1">
      <div className="mb-1.5 flex items-center gap-2 text-sm">
        <span className="font-medium text-slate-800">{title}</span>
        {a?.width_mm && <span className="text-xs text-slate-500"><bdi dir="ltr">{a.width_mm} mm</bdi></span>}
        {editable && !open && <button className="ms-auto text-sm text-brand-500 hover:underline" onClick={() => setOpen(true)}>{a ? t("asReplace") : t("asUpload")}</button>}
      </div>
      {a ? <Img a={a} /> : (
        <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-amber-300 bg-amber-50 text-sm text-amber-800">⚠ {t("asMissing")}</div>
      )}
      {open && <ImageUpload kind={kind} owner={owner} onCancel={() => setOpen(false)} onDone={(x) => { setOpen(false); onAdded(x); }} />}
    </div>
  );
}

function TemplateForm({ onDone, onCancel }: { onDone: (a: AssetInfo) => void; onCancel: () => void }) {
  const { t } = useI18n();
  const [f, setF] = useState<{ file: File | null; name: string; language: string; pair: string; rdocx: File | null; rpdf: File | null }>(
    { file: null, name: "", language: "", pair: "", rdocx: null, rpdf: null });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!f.file) return;
    const fd = new FormData();
    fd.append("file", f.file);
    if (f.name.trim()) fd.append("name", f.name.trim());
    if (f.language.trim()) fd.append("language", f.language.trim().toLowerCase());
    if (f.pair.trim()) fd.append("pair", f.pair.trim().toLowerCase());
    if (f.rdocx) fd.append("reference_docx", f.rdocx);
    if (f.rpdf) fd.append("reference_pdf", f.rpdf);
    setBusy(true); setErr("");
    try { onDone(await api.adminAddTemplate(fd)); } catch (x) { setErr((x as Error).message); } finally { setBusy(false); }
  };
  return (
    <form onSubmit={submit} className="mt-4 space-y-4 rounded-lg border border-brand-100 bg-brand-50/40 p-4">
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label className="label" htmlFor="tp-file">{t("asFile")}</label>
          <input id="tp-file" type="file" accept=".docx" className="block w-full text-sm" onChange={(e) => setF({ ...f, file: e.target.files?.[0] ?? null })} />
          <p className="mt-1 text-xs text-slate-500">{t("asDocxHint")}</p>
        </div>
        <div>
          <label className="label" htmlFor="tp-name">{t("asName")}</label>
          <input id="tp-name" className="input" dir="auto" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        </div>
        <div>
          <label className="label" htmlFor="tp-lang">{t("asLanguage")}</label>
          <input id="tp-lang" className="input max-w-[8rem] font-mono" dir="ltr" placeholder="ar" value={f.language} onChange={(e) => setF({ ...f, language: e.target.value })} />
        </div>
        <div>
          <label className="label" htmlFor="tp-pair">{t("asPair")}</label>
          <input id="tp-pair" className="input max-w-[8rem] font-mono" dir="ltr" placeholder="en>ar" value={f.pair} onChange={(e) => setF({ ...f, pair: e.target.value })} />
          <p className="mt-1 text-xs text-slate-500">{t("asPairHint")}</p>
        </div>
      </div>
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-slate-700">{t("asReference")}</legend>
        <p className="text-xs text-slate-500">{t("asReferenceHint")}</p>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm text-slate-600">{t("asRefDocx")}
            <input type="file" accept=".docx" className="mt-1 block w-full text-sm" onChange={(e) => setF({ ...f, rdocx: e.target.files?.[0] ?? null })} />
          </label>
          <label className="text-sm text-slate-600">{t("asRefPdf")}
            <input type="file" accept=".pdf" className="mt-1 block w-full text-sm" onChange={(e) => setF({ ...f, rpdf: e.target.files?.[0] ?? null })} />
          </label>
        </div>
      </fieldset>
      <Err msg={err} />
      <div className="flex gap-2">
        <button className="btn-primary" disabled={!f.file || busy}>{busy ? t("asWorking") : t("asUpload")}</button>
        <button type="button" className="btn-ghost" onClick={onCancel}>{t("usCancel")}</button>
      </div>
    </form>
  );
}

export default function Assets() {
  const { t } = useI18n();
  const [data, setData] = useState<AssetListing | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [addTpl, setAddTpl] = useState(false);
  const load = () => { setErr(""); api.adminAssets().then(setData).catch((e) => setErr(e.message)); };
  useEffect(load, []);
  const added = () => { setMsg(t("asAdded")); load(); };
  const switchOn = async (a: AssetInfo) => {
    setMsg(""); setErr("");
    try { await api.adminUpdateAsset(a.id, { active: true }); load(); } catch (x) { setErr((x as Error).message); }
  };

  if (!data) return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-slate-900">{t("asTitle")}</h1>
      {err ? <div role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{err} <button className="ms-2 underline" onClick={load}>{t("retry")}</button></div>
        : <div className="card p-5 text-sm text-slate-500">…</div>}
    </div>
  );

  const active = (type: AssetType, owner?: string) => data.assets.find((a) => a.type === type && a.active && (!owner || a.owner_user === owner));
  // translators: web accounts with that role plus any translator only known to the library
  const people = new Map<string, string>();
  data.accounts.forEach((u) => people.set(u.username, u.name));
  data.users.filter((u) => u.role === "certified_translator").forEach((u) => { if (!people.has(u.id)) people.set(u.id, u.name); });
  const templates = data.assets.filter((a) => a.type === "template" && a.active);
  const history = data.assets.filter((a) => !a.active);
  const kindLabel = (a: AssetInfo) => ({ template: t("asTemplates"), stamp_certified: t("asCertified"), stamp_office: t("asOffice"), signature: t("asSignature") })[a.type];
  const binding = (a: AssetInfo) => a.pair ?? a.language ?? null;

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-slate-900">{t("asTitle")}</h1>
      {!data.editable && <div className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-800">{t("asReadOnly")}</div>}
      {msg && <div role="status" className="rounded-md bg-green-50 px-3 py-2 text-sm text-green-800">{msg} <span className="text-green-700">{t("asTransparentNote")}</span></div>}
      <Err msg={err} />

      <section className="card p-5">
        <h2 className="font-semibold text-slate-900">{t("asTranslators")}</h2>
        <p className="mt-1 text-sm text-slate-500">{t("asTranslatorsHint")}</p>
        <div className="mt-4 space-y-4">
          {[...people.entries()].map(([id, name]) => {
            const st = active("stamp_certified", id), sig = active("signature", id);
            return (
              <div key={id} className="rounded-lg border border-slate-200 p-4">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <span className="font-medium text-slate-900"><bdi>{name}</bdi></span>
                  <span className="font-mono text-xs text-slate-500"><bdi>{id}</bdi></span>
                  {st && sig ? <span className="ms-auto rounded-full bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">✓ {t("asCanCertify")}</span>
                    : <span className="ms-auto rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">⚠ {t("asCannotCertify")}</span>}
                </div>
                <div className="flex flex-col gap-4 sm:flex-row">
                  <Slot title={t("asCertified")} a={st} kind="stamp_certified" owner={id} editable={data.editable} onAdded={added} />
                  <Slot title={t("asSignature")} a={sig} kind="signature" owner={id} editable={data.editable} onAdded={added} />
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="card p-5">
        <h2 className="font-semibold text-slate-900">{t("asOffice")}</h2>
        <p className="mb-3 mt-1 text-sm text-slate-500">{t("asOfficeHint")}</p>
        <div className="max-w-sm"><Slot title={t("asOffice")} a={active("stamp_office")} kind="stamp_office" editable={data.editable} onAdded={added} /></div>
      </section>

      <section className="card p-5">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="font-semibold text-slate-900">{t("asTemplates")}</h2>
            <p className="mt-1 text-sm text-slate-500">{t("asTemplatesHint")}</p>
          </div>
          {data.editable && !addTpl && <button className="btn-ghost" onClick={() => setAddTpl(true)}>+ {t("asAddTemplate")}</button>}
        </div>
        {addTpl && <TemplateForm onCancel={() => setAddTpl(false)} onDone={() => { setAddTpl(false); added(); }} />}
        {templates.length === 0 ? <p className="mt-3 text-sm text-amber-800">⚠ {t("asMissing")}</p> : (
          <ul className="mt-3 divide-y divide-slate-100">
            {templates.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-3 text-sm">
                <span className="text-lg" aria-hidden>📄</span>
                <div className="min-w-0 flex-1">
                  <div className="font-medium text-slate-900"><bdi>{a.name}</bdi></div>
                  <div className="text-xs text-slate-500">
                    {t("asBinding")}: {binding(a) ? <bdi dir="ltr" className="font-mono">{binding(a)}</bdi> : t("asAllLanguages")}
                    {a.seal_from_template && <> · {t("asSealDetected")}</>}
                  </div>
                </div>
                <a className="text-brand-500 hover:underline" href={api.assetFile(a.id)}>{t("asDownload")}</a>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card p-5">
        <h2 className="font-semibold text-slate-900">{t("asHistory")}</h2>
        <p className="mt-1 text-sm text-slate-500">{t("asHistoryHint")}</p>
        {history.length === 0 ? <p className="mt-3 text-sm text-slate-500">{t("asNoHistory")}</p> : (
          <ul className="mt-3 divide-y divide-slate-100">
            {history.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-3 py-2.5 text-sm">
                {a.type === "template" ? <span className="w-16 text-center text-lg" aria-hidden>📄</span>
                  : <div className="w-16"><Img a={a} h="h-10" /></div>}
                <div className="min-w-0 flex-1">
                  <div className="text-slate-800"><bdi>{a.name}</bdi></div>
                  <div className="text-xs text-slate-500">{kindLabel(a)} · <bdi dir="ltr" className="font-mono">{a.id}</bdi></div>
                </div>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{t("asOff")}</span>
                {data.editable && <button className="btn-ghost px-3 py-1" onClick={() => switchOn(a)}>{t("asSwitchOn")}</button>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
