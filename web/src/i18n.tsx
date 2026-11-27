import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

// Interface languages. To add one: copy the `en` block, translate it, and add the code to LANGS.
const en = {
  appName: "CertiFlow",
  office: "Shoreline Legal Translation",
  signIn: "Sign in", username: "Username", password: "Password", signOut: "Sign out",
  wrongLogin: "Wrong username or password.",
  jobs: "Jobs", newJob: "New job", noJobs: "No jobs yet. Start one with “New job”.",
  title: "Title", pair: "Languages", stamp: "Stamp", status: "Status", created: "Created", cost: "Cost",
  certified: "Certified stamp", officeStamp: "Office stamp",
  // new job
  sourceDocs: "Source documents", dropHere: "Drop files here or click to choose",
  dropHint: "PDF, scans or photos (JPG, PNG, TIFF), or Word. Several files make a batch.",
  from: "From", to: "To", autoDetect: "Detect automatically", swap: "Swap languages", recent: "Recent pairs",
  perDocument: "Languages for this document", sameAsJob: "Same as the job",
  chooseStamp: "Stamp", chooseStampHint: "Required. Choose which stamp is applied to every page after approval.",
  notAvailable: "Not available to you",
  docType: "Document type (optional)", docTypePh: "e.g. birth certificate, contract, medical report",
  notes: "Notes for this job (optional)",
  pageOrder: "PDF page order", orderTS: "Translation, then source", orderIL: "Each translated page next to its source page",
  start: "Start translation", startHintFiles: "Add at least one document.", startHintStamp: "Choose a stamp to start.",
  remove: "Remove",
  // job page
  back: "All jobs", documents: "Documents", progress: "Live progress", files: "Release files", download: "Download",
  costByAgent: "Cost by step", waitingGlossary: "Confirm the glossary",
  glossaryHint: "These names and terms will be translated the same way in every document of this job. Correct or remove entries, then confirm.",
  source: "Source", target: "Translation", kind: "Type", addRow: "Add entry", confirmGlossary: "Confirm glossary",
  emptyGlossary: "No recurring names or terms were found. You can add entries or confirm as is.",
  waitingReview: "Final review", reviewHint: "Check the translation. The stamp and signature are applied only when a certified translator approves.",
  approve: "Approve and release", approveNote: "Note (optional)", onlySigner: "Only the signing certified translator or an admin can approve.",
  openFlags: "open flag(s)", blockers: "blocker(s)", retry: "Retry", failed: "Failed",
  translation: "Translation preview", showMore: "Show all", showLess: "Show less", noPreview: "No preview yet.",
  editorSoon: "Side-by-side editing arrives in the next phase; this preview is read-only.",
  releasedOn: "Released", disclosures: "Disclosures",
  st_queued: "Queued", st_running: "Working", st_waiting_glossary: "Glossary to confirm", st_waiting_review: "Ready for review",
  st_releasing: "Releasing", st_released: "Released", st_failed: "Failed", st_blocked: "Blocked",
  stage_queued: "Queued", stage_intake: "Read", stage_translated: "Translated", stage_proofread: "Proofread",
  stage_qa: "Checked", stage_formatted: "Laid out", stage_reviewed: "Reviewed",
  ev_llm_call: "{agent} finished", ev_stage_done: "{stage}: done",
  sd_intake: "Reading", sd_proofread: "Proofreading", sd_qa_format: "Quality check and layout", ev_glossary_confirmed: "Glossary confirmed",
  ev_qa_loop: "Quality check sent {n} block(s) back for correction", ev_approved: "Approved by {by}",
  ev_released: "Released {pdf}", ev_llm_error: "{agent} error, retrying", ev_status: "Status: {status}",
  agent_intake: "Reading pages", agent_intake_zoom: "Re-reading an unclear area", agent_glossary: "Glossary",
  agent_translator: "Translation", agent_proofreader: "Proofreading", agent_qa: "Quality check", agent_formatter: "Layout",
  language: "العربية",
};
type Messages = typeof en;

const ar: Messages = {
  appName: "سيرتي فلو",
  office: "شورلاين للترجمة القانونية",
  signIn: "تسجيل الدخول", username: "اسم المستخدم", password: "كلمة المرور", signOut: "تسجيل الخروج",
  wrongLogin: "اسم المستخدم أو كلمة المرور غير صحيحة.",
  jobs: "المهام", newJob: "مهمة جديدة", noJobs: "لا توجد مهام بعد. ابدأ بالضغط على «مهمة جديدة».",
  title: "العنوان", pair: "اللغتان", stamp: "الختم", status: "الحالة", created: "تاريخ الإنشاء", cost: "التكلفة",
  certified: "الختم المعتمد", officeStamp: "ختم المكتب",
  sourceDocs: "المستندات الأصلية", dropHere: "اسحب الملفات إلى هنا أو اضغط للاختيار",
  dropHint: "ملفات PDF أو صور ممسوحة (JPG وPNG وTIFF) أو ملفات وورد. عدة ملفات تشكّل دفعة واحدة.",
  from: "من", to: "إلى", autoDetect: "تحديد تلقائي", swap: "تبديل اللغتين", recent: "أزواج مستخدمة مؤخراً",
  perDocument: "لغتا هذا المستند", sameAsJob: "كما في المهمة",
  chooseStamp: "الختم", chooseStampHint: "إلزامي. اختر الختم الذي يوضع على كل صفحة بعد الاعتماد.",
  notAvailable: "غير متاح لك",
  docType: "نوع المستند (اختياري)", docTypePh: "مثال: شهادة ميلاد، عقد، تقرير طبي",
  notes: "ملاحظات على المهمة (اختياري)",
  pageOrder: "ترتيب صفحات PDF", orderTS: "الترجمة ثم الأصل", orderIL: "كل صفحة مترجمة بجانب صفحتها الأصلية",
  start: "ابدأ الترجمة", startHintFiles: "أضف مستنداً واحداً على الأقل.", startHintStamp: "اختر الختم للبدء.",
  remove: "حذف",
  back: "كل المهام", documents: "المستندات", progress: "سير العمل مباشرة", files: "ملفات الإصدار", download: "تنزيل",
  costByAgent: "التكلفة حسب المرحلة", waitingGlossary: "اعتماد مسرد المصطلحات",
  glossaryHint: "ستُترجم هذه الأسماء والمصطلحات بالطريقة نفسها في جميع مستندات المهمة. صحّح أو احذف ما يلزم ثم اعتمد.",
  source: "الأصل", target: "الترجمة", kind: "النوع", addRow: "إضافة بند", confirmGlossary: "اعتماد المسرد",
  emptyGlossary: "لم تُعثر على أسماء أو مصطلحات متكررة. يمكنك إضافة بنود أو الاعتماد كما هو.",
  waitingReview: "المراجعة النهائية", reviewHint: "راجع الترجمة. لا يوضع الختم والتوقيع إلا بعد اعتماد مترجم معتمد.",
  approve: "اعتماد وإصدار", approveNote: "ملاحظة (اختياري)", onlySigner: "الاعتماد للمترجم المعتمد الموقِّع أو لمسؤول النظام فقط.",
  openFlags: "ملاحظات مفتوحة", blockers: "عوائق", retry: "إعادة المحاولة", failed: "فشلت",
  translation: "معاينة الترجمة", showMore: "عرض الكل", showLess: "عرض أقل", noPreview: "لا توجد معاينة بعد.",
  editorSoon: "يتوفر التحرير جنباً إلى جنب في المرحلة التالية؛ هذه المعاينة للقراءة فقط.",
  releasedOn: "صدرت في", disclosures: "الإفصاحات",
  st_queued: "في الانتظار", st_running: "قيد العمل", st_waiting_glossary: "المسرد بانتظار الاعتماد", st_waiting_review: "جاهزة للمراجعة",
  st_releasing: "جارٍ الإصدار", st_released: "صدرت", st_failed: "فشلت", st_blocked: "متوقفة",
  stage_queued: "في الانتظار", stage_intake: "قُرئت", stage_translated: "تُرجمت", stage_proofread: "دُققت",
  stage_qa: "فُحصت", stage_formatted: "نُسّقت", stage_reviewed: "رُوجعت",
  ev_llm_call: "انتهت مرحلة {agent}", ev_stage_done: "اكتملت مرحلة {stage}",
  sd_intake: "القراءة", sd_proofread: "التدقيق", sd_qa_format: "فحص الجودة والتنسيق", ev_glossary_confirmed: "اعتُمد المسرد",
  ev_qa_loop: "أعاد فحص الجودة {n} فقرة للتصحيح", ev_approved: "اعتمدها {by}",
  ev_released: "صدر الملف {pdf}", ev_llm_error: "خطأ في مرحلة {agent}، جارٍ إعادة المحاولة", ev_status: "الحالة: {status}",
  agent_intake: "قراءة الصفحات", agent_intake_zoom: "إعادة قراءة منطقة غير واضحة", agent_glossary: "المسرد",
  agent_translator: "الترجمة", agent_proofreader: "التدقيق", agent_qa: "فحص الجودة", agent_formatter: "التنسيق",
  language: "English",
};

const LANGS = { en, ar } as const;
export type UiLang = keyof typeof LANGS;
export type MsgKey = keyof Messages;

interface Ctx { lang: UiLang; dir: "ltr" | "rtl"; t: (k: MsgKey | string, vars?: Record<string, string | number>) => string; setLang: (l: UiLang) => void }
const I18n = createContext<Ctx | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<UiLang>(() => (localStorageGet("cf_lang") as UiLang) || "en");
  const dir = lang === "ar" ? "rtl" : "ltr";
  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = dir;
    localStorageSet("cf_lang", lang);
  }, [lang, dir]);
  const value = useMemo<Ctx>(() => ({
    lang, dir, setLang,
    t: (k, vars) => {
      let s = (LANGS[lang] as Record<string, string>)[k] ?? (en as Record<string, string>)[k] ?? k;
      if (vars) for (const [a, b] of Object.entries(vars)) s = s.replace(`{${a}}`, String(b));
      return s;
    },
  }), [lang, dir]);
  return <I18n.Provider value={value}>{children}</I18n.Provider>;
}

export function useI18n(): Ctx {
  const c = useContext(I18n);
  if (!c) throw new Error("I18nProvider missing");
  return c;
}

function localStorageGet(k: string): string | null { try { return window.localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k: string, v: string) { try { window.localStorage.setItem(k, v); } catch { /* private mode */ } }
