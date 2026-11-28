import { useState, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { Sparkles, X } from "lucide-react";
import { useI18n } from "../../i18n";

function Shell({ open, onOpenChange, title, children, wide }: { open: boolean; onOpenChange: (v: boolean) => void; title: string; children: ReactNode; wide?: boolean }) {
  const { t, dir } = useI18n();
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-slate-950/30 backdrop-blur-[2px] animate-fade-in" />
        <Dialog.Content dir={dir} aria-describedby={undefined}
          className={`fixed inset-x-3 top-[14vh] z-50 mx-auto rounded-2xl border border-slate-200 bg-raised p-5 shadow-float animate-fade-in focus:outline-none ${wide ? "max-w-xl" : "max-w-md"}`}>
          <div className="mb-4 flex items-center">
            <Dialog.Title className="font-serif text-lg text-slate-900">{title}</Dialog.Title>
            <Dialog.Close className="icon-btn ms-auto h-8 w-8" aria-label={t("usClose")}><X className="h-4 w-4" /></Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function ShortcutsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const { t } = useI18n();
  const rows: [string[], string][] = [
    [["J"], "sc_next"], [["K"], "sc_prev"], [["A"], "sc_accept"], [["R"], "sc_reject"],
    [["Ctrl", "S"], "sc_save"], [["Ctrl", "↵"], "sc_saveBlock"], [["Esc"], "sc_leave"], [["["], "sc_checklist"], [["?"], "sc_help"],
  ];
  return (
    <Shell open={open} onOpenChange={onOpenChange} title={t("edShortcuts")}>
      <dl className="divide-y divide-slate-100">
        {rows.map(([keys, k]) => (
          <div key={k} className="flex items-center gap-4 py-2 text-sm">
            <dt className="flex-1 text-slate-700">{t(k)}</dt>
            <dd className="flex gap-1" dir="ltr">{keys.map((x) => <kbd key={x} className="kbd h-6 min-w-[1.5rem] text-xs">{x}</kbd>)}</dd>
          </div>
        ))}
      </dl>
    </Shell>
  );
}

export function RerunDialog({ open, onOpenChange, count, dirty, onRun }: {
  open: boolean; onOpenChange: (v: boolean) => void; count: number; dirty: boolean; onRun: (agent: string, instruction: string) => Promise<unknown>;
}) {
  const { t } = useI18n();
  const [agent, setAgent] = useState("translator");
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Shell open={open} onOpenChange={onOpenChange} title={t("rvRerunTitle")} wide>
      <form onSubmit={(e) => { e.preventDefault(); setBusy(true); onRun(agent, instruction).finally(() => { setBusy(false); onOpenChange(false); }); }}>
        <fieldset className="mb-4">
          <legend className="label">{t("rvRerunAgent")}</legend>
          <div className="grid grid-cols-3 gap-2">
            {["translator", "proofreader", "qa"].map((a) => (
              <label key={a} className={`flex cursor-pointer items-center justify-center rounded-lg border px-3 py-2 text-sm transition has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-brand-500/40 ${agent === a ? "border-brand-500 bg-brand-50 font-medium text-brand-700" : "border-slate-200 text-slate-600 hover:border-slate-300"}`}>
                <input type="radio" name="agent" value={a} checked={agent === a} onChange={() => setAgent(a)} className="sr-only" />
                {t(`agent_${a}`)}
              </label>
            ))}
          </div>
        </fieldset>
        <label className="label" htmlFor="rr-ins">{t("rvRerunInstruction")}</label>
        <textarea id="rr-ins" className="input min-h-[5rem] resize-y" dir="auto" maxLength={2000} value={instruction}
          placeholder={t("rvRerunInstructionPh")} onChange={(e) => setInstruction(e.target.value)} />
        <p className="mt-2 text-xs text-slate-500">{dirty ? t("rvRerunSaveFirst") : t("rvRerunHint")}</p>
        <div className="mt-5 flex justify-end gap-2">
          <Dialog.Close className="btn-quiet" type="button">{t("rvCancel")}</Dialog.Close>
          <button className="btn-primary" disabled={busy || dirty}><Sparkles className="h-4 w-4" />{t("rvRerunRun", { n: count })}</button>
        </div>
      </form>
    </Shell>
  );
}
