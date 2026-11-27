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
  // review editor
  rvOpenEditor: "Open the review editor", rvBackToJob: "Back to the job", rvSourcePane: "Source", rvTargetPane: "Translation",
  rvPage: "Page", rvNoPages: "No source page images for this document.", rvLoadError: "The document could not be loaded.",
  rvBlockersOpen: "{n} blocking issue(s) to resolve before approval", rvNoBlockers: "No blocking issues",
  rvPendingChanges: "{n} change(s) by the agents to check", rvAcceptAll: "Accept all changes", rvSaveAll: "Save all",
  rvSave: "Save", rvCancel: "Cancel", rvSave_saved: "Saved", rvSave_saving: "Saving…", rvSave_dirty: "Unsaved changes",
  rvSave_error: "Not saved", rvReadOnly: "This job is not waiting for review, so the editor is read-only.",
  rvLeaveConfirm: "You have unsaved changes. Leave without saving?", rvApproveOnJob: "Approval and release are on the job page.",
  rvShowOnPage: "Show on the source page", rvDuplicate: "Same text in another language", rvCell: "row {r}, column {c}",
  rvTranslationOf: "Translation of block {id}", rvChangeBy: "Change by {agent}", rvAccept: "Accept", rvReject: "Reject",
  rvResolve: "Resolve", rvComment: "Comment", rvCommentRequired: "Comment (required for a blocking issue)",
  rvCommentOptional: "Comment (optional)", rvResolvedBy: "Resolved by {by}",
  rvApproveBlocked: "Approval is not possible: {n} blocking issue(s) are still open. Resolve them in the review editor.",
  rvPreview: "Preview PDF", rvPreviewHint: "Watermarked PDF with the chosen stamp. Building it can take up to a minute.",
  rvPreviewSaveFirst: "Save your changes first.", rvPick: "Select block {id} for a re-run",
  rvRerunTitle: "Run an agent again", rvRerunAgent: "Agent", rvRerunInstruction: "Instruction (optional)",
  rvRerunInstructionPh: "e.g. use the formal register, keep the passport number as written",
  rvRerunRun: "Run on {n} block(s)", rvRerunHint: "The new text comes back as changes you can accept or reject. The model call costs money.",
  rvRerunSaveFirst: "Save your changes first.", rvReworking: "An agent is working on the selected blocks. Editing is paused until it finishes.",
  st_reworking: "Agent re-run",
  apConfirmTitle: "Confirm approval", apConfirm: "Approve and release",
  apConfirmText: "After approval the stamp and signature are applied and the release files are built. The translation can no longer be edited.",
  auOpen: "Audit log", auTitle: "Audit log", auHint: "Every step of this job: who or which agent did it, and when. Document text is never shown here.",
  auLoadError: "The audit log could not be loaded.", auEmpty: "Nothing to show for this filter.",
  auF_all: "All", auF_people: "People", auF_agents: "Agents and system", auCalls: "{n} model calls",
  auWhen: "When", auWho: "Who", auWhat: "What", auDetails: "Details", auSystem: "System",
  au_created: "Created the job", au_status: "Status: {status}", au_llm_call: "Model call: {agent}", au_llm_error: "Model error: {agent}",
  au_stage_done: "Finished: {stage}", au_qa_loop: "Quality check sent {n} block(s) back for correction",
  au_glossary_confirmed: "Confirmed the glossary", au_approved: "Approved the translation", au_released: "Released the certified files",
  au_review_edit: "Edited a block", au_review_change: "{action} an agent change", au_review_flag: "Resolved a QA flag",
  au_rerun_started: "Re-run started: {agent} on {n} block(s)", au_rerun_done: "Re-run finished: {agent}",
  au_preview_built: "Built a watermarked preview", au_act_accept: "Accepted", au_act_reject: "Rejected", au_act_resolve: "Resolved",
  sev_blocker: "Blocking", sev_major: "Major", sev_minor: "Minor", sev_info: "Info",
  bt_heading: "Heading", bt_paragraph: "Paragraph", bt_numbered_item: "Numbered item", bt_bullet: "Bullet", bt_table: "Table",
  bt_kv_table: "Form table", bt_note: "Note", bt_page_break: "Page break", bt_signature_block: "Signature block", bt_unreadable: "Unreadable",
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
  rvOpenEditor: "فتح محرر المراجعة", rvBackToJob: "العودة إلى المهمة", rvSourcePane: "الأصل", rvTargetPane: "الترجمة",
  rvPage: "صفحة", rvNoPages: "لا توجد صور لصفحات الأصل في هذا المستند.", rvLoadError: "تعذّر تحميل المستند.",
  rvBlockersOpen: "{n} من العوائق يجب حلّها قبل الاعتماد", rvNoBlockers: "لا توجد عوائق",
  rvPendingChanges: "{n} من التعديلات الآلية بانتظار المراجعة", rvAcceptAll: "قبول كل التعديلات", rvSaveAll: "حفظ الكل",
  rvSave: "حفظ", rvCancel: "إلغاء", rvSave_saved: "محفوظ", rvSave_saving: "جارٍ الحفظ…", rvSave_dirty: "تعديلات غير محفوظة",
  rvSave_error: "لم يُحفظ", rvReadOnly: "هذه المهمة ليست بانتظار المراجعة، لذا المحرر للقراءة فقط.",
  rvLeaveConfirm: "لديك تعديلات غير محفوظة. هل تريد المغادرة دون حفظ؟", rvApproveOnJob: "الاعتماد والإصدار من صفحة المهمة.",
  rvShowOnPage: "إظهار الموضع في صفحة الأصل", rvDuplicate: "النص نفسه بلغة أخرى", rvCell: "الصف {r}، العمود {c}",
  rvTranslationOf: "ترجمة الفقرة {id}", rvChangeBy: "تعديل من {agent}", rvAccept: "قبول", rvReject: "رفض",
  rvResolve: "معالجة", rvComment: "تعليق", rvCommentRequired: "تعليق (إلزامي للعائق)",
  rvCommentOptional: "تعليق (اختياري)", rvResolvedBy: "عالجها {by}",
  rvApproveBlocked: "لا يمكن الاعتماد: ما زال هناك {n} من العوائق المفتوحة. عالجها في محرر المراجعة.",
  rvPreview: "معاينة PDF", rvPreviewHint: "ملف PDF عليه علامة مائية بالختم المختار. قد يستغرق إعداده حتى دقيقة.",
  rvPreviewSaveFirst: "احفظ تعديلاتك أولاً.", rvPick: "تحديد الفقرة {id} لإعادة المعالجة",
  rvRerunTitle: "إعادة تشغيل مرحلة آلية", rvRerunAgent: "المرحلة", rvRerunInstruction: "توجيه (اختياري)",
  rvRerunInstructionPh: "مثال: استخدم الأسلوب الرسمي، واترك رقم الجواز كما هو",
  rvRerunRun: "تشغيل على {n} من الفقرات", rvRerunHint: "يعود النص الجديد تعديلاتٍ يمكنك قبولها أو رفضها. استدعاء النموذج له تكلفة.",
  rvRerunSaveFirst: "احفظ تعديلاتك أولاً.", rvReworking: "تعمل مرحلة آلية على الفقرات المحددة. التحرير متوقف حتى تنتهي.",
  st_reworking: "إعادة معالجة آلية",
  apConfirmTitle: "تأكيد الاعتماد", apConfirm: "اعتماد وإصدار",
  apConfirmText: "بعد الاعتماد يوضع الختم والتوقيع وتُعدّ ملفات الإصدار، ولا يعود تعديل الترجمة ممكناً.",
  auOpen: "سجل التدقيق", auTitle: "سجل التدقيق", auHint: "كل خطوة في هذه المهمة: من قام بها أو أي مرحلة آلية، ومتى. لا يُعرض نص المستند هنا أبداً.",
  auLoadError: "تعذّر تحميل سجل التدقيق.", auEmpty: "لا شيء لعرضه بهذا التصفية.",
  auF_all: "الكل", auF_people: "الأشخاص", auF_agents: "المراحل الآلية والنظام", auCalls: "{n} من استدعاءات النموذج",
  auWhen: "الوقت", auWho: "المنفّذ", auWhat: "الإجراء", auDetails: "التفاصيل", auSystem: "النظام",
  au_created: "أنشأ المهمة", au_status: "الحالة: {status}", au_llm_call: "استدعاء النموذج: {agent}", au_llm_error: "خطأ في النموذج: {agent}",
  au_stage_done: "اكتملت: {stage}", au_qa_loop: "أعاد فحص الجودة {n} من الفقرات للتصحيح",
  au_glossary_confirmed: "اعتمد المسرد", au_approved: "اعتمد الترجمة", au_released: "أصدر الملفات المعتمدة",
  au_review_edit: "عدّل فقرة", au_review_change: "{action} تعديلاً آلياً", au_review_flag: "عالج ملاحظة فحص الجودة",
  au_rerun_started: "بدأت إعادة المعالجة: {agent} على {n} من الفقرات", au_rerun_done: "انتهت إعادة المعالجة: {agent}",
  au_preview_built: "أعدّ معاينة بعلامة مائية", au_act_accept: "قَبِل", au_act_reject: "رَفَض", au_act_resolve: "عالج",
  sev_blocker: "عائق", sev_major: "مهم", sev_minor: "بسيط", sev_info: "للعلم",
  bt_heading: "عنوان", bt_paragraph: "فقرة", bt_numbered_item: "بند مرقّم", bt_bullet: "نقطة", bt_table: "جدول",
  bt_kv_table: "جدول بيانات", bt_note: "ملاحظة", bt_page_break: "فاصل صفحة", bt_signature_block: "خانة التوقيع", bt_unreadable: "غير مقروء",
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
