"""Regenerate the shipped profile files: ``python -m certiflow.profiles.seed``.

After seeding, profiles are data. Admins edit the JSON (later: the database);
this script only exists to produce the day-one set.
"""
from __future__ import annotations

import json

from . import DATA_DIR

LEGAL = ("Use a formal legal register. Translate faithfully and completely; never add, explain, summarise "
         "or complete text. Keep the source order and structure. Keep identifiers (ID, tax, serial and "
         "reference numbers, verification codes, URLs, emails, hashes) exactly as written. Keep dates and "
         "numbers as written in the source unless the job asks to localise them.")


def L(ill, cov, tru, rep):
    return {"unreadable_illegible": ill, "unreadable_covered_by_stamp": cov,
            "unreadable_truncated": tru, "repeated_notes_heading": rep}


LATIN_FONT = ("Times New Roman", "Liberation Serif")   # Liberation Serif is metric-compatible with TNR

P = [
    dict(code="ar", display_name="Arabic", native_name="العربية", script="Arab", direction="rtl", word_tag="ar-AE",
         font_slot="cs", word_font="Sakkal Majalla", pdf_font="Amiri", body_size_pt=13, heading_scale=1.15,
         line_spacing=1.0, digit_style="as_source", quote_marks=["«", "»"],
         transliteration_standard="common Arabic rendering (UAE official usage where known)",
         name_rule="Transliterate names of people, companies, streets and places into Arabic script. Use the "
                   "glossary rendering when one exists so a name is always written the same way.",
         no_foreign_script=True, ocr_pack="ara",
         vision_notes="Check diacritics-free OCR output against the image; stamps are often blue ovals with curved text.",
         style_guide=LEGAL + " Write Modern Standard Arabic in the register of UAE courts and notaries. "
         "Do not leave any Latin-script text next to the Arabic except identifiers. Describe stamps as "
         "// ختم ... // , seals as // خاتم ... // , signatures as // توقيع // , handwriting as // بخط اليد: ... // . "
         "Use common legal formulae: «حرر في» for 'done at', «صورة طبق الأصل» for 'true copy', «الموقع أدناه» for "
         "'the undersigned'.",
         labels=L("// غير مقروء //", "// غير واضح بسبب الختم //", "// النص مبتور في الأصل //", "الأختام والتواقيع الواردة في جميع الصفحات")),
    dict(code="en", display_name="English", native_name="English", script="Latn", direction="ltr", word_tag="en-GB",
         font_slot="ascii", word_font=LATIN_FONT[0], pdf_font=LATIN_FONT[1], body_size_pt=12,
         transliteration_standard="BGN/PCGN for Cyrillic and Persian; common English rendering for Arabic names, "
                                  "following the passport spelling when it appears in the document",
         name_rule="When the source is in Latin script, keep names exactly as written. Otherwise transliterate, "
                   "preferring any Latin spelling that appears in the document itself (passport, MRZ).",
         ocr_pack="eng",
         style_guide=LEGAL + " Use British legal English as used in UAE certified translations. Describe stamps as "
         "// Stamp: ... // , seals as // Seal: ... // , signatures as // Signature // , handwriting as "
         "// Handwritten: ... // , including legible text, numbers, colour and shape.",
         labels=L("// illegible //", "// unclear, covered by stamp //", "// text truncated in the original //", "Stamps and signatures appearing on all pages")),
    dict(code="fr", display_name="French", native_name="Français", script="Latn", direction="ltr", word_tag="fr-FR",
         font_slot="ascii", word_font=LATIN_FONT[0], pdf_font=LATIN_FONT[1], quote_marks=["« ", " »"],
         ocr_pack="fra", name_rule="Keep Latin-script names as written; transliterate others.",
         transliteration_standard="usage français courant",
         style_guide=LEGAL + " Use French legal register. Notes: // Cachet : ... // , // Sceau : ... // , // Signature // .",
         labels=L("// illisible //", "// illisible, recouvert par le cachet //", "// texte tronqué dans l'original //", "Cachets et signatures figurant sur toutes les pages")),
    dict(code="de", display_name="German", native_name="Deutsch", script="Latn", direction="ltr", word_tag="de-DE",
         font_slot="ascii", word_font=LATIN_FONT[0], pdf_font=LATIN_FONT[1], quote_marks=["„", "“"],
         ocr_pack="deu", name_rule="Keep Latin-script names as written; transliterate others (DIN 31635 for Arabic).",
         transliteration_standard="DIN 31635 / ISO 9",
         style_guide=LEGAL + " Use German legal register. Notes: // Stempel: ... // , // Siegel: ... // , // Unterschrift // .",
         labels=L("// unleserlich //", "// unleserlich, vom Stempel verdeckt //", "// Text im Original abgeschnitten //", "Stempel und Unterschriften auf allen Seiten")),
    dict(code="es", display_name="Spanish", native_name="Español", script="Latn", direction="ltr", word_tag="es-ES",
         font_slot="ascii", word_font=LATIN_FONT[0], pdf_font=LATIN_FONT[1], quote_marks=["«", "»"],
         ocr_pack="spa", name_rule="Keep Latin-script names as written; transliterate others.",
         style_guide=LEGAL + " Use Spanish legal register. Notes: // Sello: ... // , // Firma // .",
         labels=L("// ilegible //", "// ilegible, cubierto por el sello //", "// texto truncado en el original //", "Sellos y firmas que figuran en todas las páginas")),
    dict(code="it", display_name="Italian", native_name="Italiano", script="Latn", direction="ltr", word_tag="it-IT",
         font_slot="ascii", word_font=LATIN_FONT[0], pdf_font=LATIN_FONT[1], quote_marks=["«", "»"],
         ocr_pack="ita", name_rule="Keep Latin-script names as written; transliterate others.",
         style_guide=LEGAL + " Use Italian legal register. Notes: // Timbro: ... // , // Firma // .",
         labels=L("// illeggibile //", "// illeggibile, coperto dal timbro //", "// testo troncato nell'originale //", "Timbri e firme presenti su tutte le pagine")),
    dict(code="pt", display_name="Portuguese", native_name="Português", script="Latn", direction="ltr", word_tag="pt-PT",
         font_slot="ascii", word_font=LATIN_FONT[0], pdf_font=LATIN_FONT[1], quote_marks=["«", "»"],
         ocr_pack="por", name_rule="Keep Latin-script names as written; transliterate others.",
         style_guide=LEGAL + " Use Portuguese legal register. Notes: // Carimbo: ... // , // Assinatura // .",
         labels=L("// ilegível //", "// ilegível, coberto pelo carimbo //", "// texto truncado no original //", "Carimbos e assinaturas constantes de todas as páginas")),
    dict(code="nl", display_name="Dutch", native_name="Nederlands", script="Latn", direction="ltr", word_tag="nl-NL",
         font_slot="ascii", word_font=LATIN_FONT[0], pdf_font=LATIN_FONT[1], quote_marks=["‘", "’"],
         ocr_pack="nld", name_rule="Keep Latin-script names as written; transliterate others.",
         style_guide=LEGAL + " Use Dutch legal register. Notes: // Stempel: ... // , // Handtekening // .",
         labels=L("// onleesbaar //", "// onleesbaar, bedekt door stempel //", "// tekst afgebroken in het origineel //", "Stempels en handtekeningen op alle pagina's")),
    dict(code="tr", display_name="Turkish", native_name="Türkçe", script="Latn", direction="ltr", word_tag="tr-TR",
         font_slot="ascii", word_font=LATIN_FONT[0], pdf_font=LATIN_FONT[1],
         ocr_pack="tur", name_rule="Keep Latin-script names as written; transliterate others.",
         style_guide=LEGAL + " Use Turkish legal register. Notes: // Mühür: ... // , // İmza // .",
         labels=L("// okunamıyor //", "// okunamıyor, mühür altında //", "// metin asılda kesik //", "Tüm sayfalarda yer alan mühür ve imzalar")),
    dict(code="ru", display_name="Russian", native_name="Русский", script="Cyrl", direction="ltr", word_tag="ru-RU",
         font_slot="ascii", word_font=LATIN_FONT[0], pdf_font=LATIN_FONT[1], quote_marks=["«", "»"],
         ocr_pack="rus", transliteration_standard="GOST 7.79-2000 (System B) for Latin to Cyrillic practical transcription",
         name_rule="Transcribe foreign names into Cyrillic using established practical transcription.",
         style_guide=LEGAL + " Use Russian official-document register. Notes: // Печать: ... // , // Подпись // .",
         labels=L("// неразборчиво //", "// неразборчиво, закрыто печатью //", "// текст в оригинале обрезан //", "Печати и подписи на всех страницах")),
    dict(code="fa", display_name="Persian", native_name="فارسی", script="Arab", direction="rtl", word_tag="fa-IR",
         font_slot="cs", word_font="Sakkal Majalla", pdf_font="Noto Naskh Arabic", body_size_pt=14,
         line_spacing=1.0, digit_style="as_source", quote_marks=["«", "»"], no_foreign_script=True,
         ocr_pack="fas", transliteration_standard="common Persian rendering",
         name_rule="Transliterate foreign names into Persian script.",
         style_guide=LEGAL + " Use formal Persian legal register. Notes: // مهر: ... // , // امضا // .",
         labels=L("// ناخوانا //", "// ناخوانا، زیر مهر //", "// متن در اصل ناقص است //", "مهرها و امضاهای مندرج در همه صفحات")),
    dict(code="ur", display_name="Urdu", native_name="اردو", script="Arab", direction="rtl", word_tag="ur-PK",
         font_slot="cs", word_font="Urdu Typesetting", pdf_font="Noto Nastaliq Urdu", body_size_pt=14,
         line_spacing=1.3, quote_marks=["“", "”"], no_foreign_script=True, ocr_pack="urd",
         name_rule="Transliterate foreign names into Urdu script.",
         style_guide=LEGAL + " Use formal Urdu legal register. Notes: // مہر: ... // , // دستخط // .",
         labels=L("// ناقابل مطالعہ //", "// ناقابل مطالعہ، مہر کے نیچے //", "// اصل میں متن نامکمل //", "تمام صفحات پر موجود مہریں اور دستخط")),
    dict(code="he", display_name="Hebrew", native_name="עברית", script="Hebr", direction="rtl", word_tag="he-IL",
         font_slot="cs", word_font="David", pdf_font="Noto Serif Hebrew", body_size_pt=12,
         quote_marks=["“", "”"], ocr_pack="heb", name_rule="Transliterate foreign names into Hebrew script.",
         style_guide=LEGAL + " Use formal Hebrew legal register. Notes: // חותמת: ... // , // חתימה // .",
         labels=L("// לא קריא //", "// לא קריא, מכוסה בחותמת //", "// הטקסט קטוע במקור //", "חותמות וחתימות המופיעות בכל העמודים")),
    dict(code="zh", display_name="Chinese (Simplified)", native_name="中文", script="Hans", direction="ltr", word_tag="zh-CN",
         font_slot="eastAsia", word_font="SimSun", pdf_font="Noto Serif CJK SC", body_size_pt=12, justify=True,
         quote_marks=["“", "”"], ocr_pack="chi_sim", name_rule="Render foreign names with standard Xinhua transcription.",
         transliteration_standard="Xinhua",
         style_guide=LEGAL + " Use formal written Chinese legal register. Notes: // 印章：... // , // 签名 // .",
         labels=L("// 无法辨认 //", "// 被印章遮盖，无法辨认 //", "// 原文截断 //", "各页均有的印章和签名")),
    dict(code="ja", display_name="Japanese", native_name="日本語", script="Jpan", direction="ltr", word_tag="ja-JP",
         font_slot="eastAsia", word_font="MS Mincho", pdf_font="Noto Serif CJK JP", body_size_pt=11,
         quote_marks=["「", "」"], ocr_pack="jpn", name_rule="Write foreign names in katakana.",
         style_guide=LEGAL + " Use formal Japanese legal register (である調). Notes: // 印：... // , // 署名 // .",
         labels=L("// 判読不能 //", "// 印影により判読不能 //", "// 原文が途切れている //", "全ページに押印・署名されているもの")),
    dict(code="ko", display_name="Korean", native_name="한국어", script="Kore", direction="ltr", word_tag="ko-KR",
         font_slot="eastAsia", word_font="Batang", pdf_font="Noto Serif CJK KR", body_size_pt=11,
         quote_marks=["“", "”"], ocr_pack="kor", name_rule="Write foreign names in Hangul (Korean loanword orthography).",
         style_guide=LEGAL + " Use formal Korean legal register. Notes: // 직인: ... // , // 서명 // .",
         labels=L("// 판독 불가 //", "// 직인에 가려 판독 불가 //", "// 원문 잘림 //", "모든 페이지에 있는 직인 및 서명")),
    dict(code="hi", display_name="Hindi", native_name="हिन्दी", script="Deva", direction="ltr", word_tag="hi-IN",
         font_slot="cs", word_font="Mangal", pdf_font="Noto Serif Devanagari", body_size_pt=12,
         quote_marks=["“", "”"], ocr_pack="hin", name_rule="Transliterate foreign names into Devanagari.",
         style_guide=LEGAL + " Use formal Hindi legal register. Notes: // मुहर: ... // , // हस्ताक्षर // .",
         labels=L("// अपठनीय //", "// मुहर के कारण अपठनीय //", "// मूल में पाठ अधूरा //", "सभी पृष्ठों पर अंकित मुहरें और हस्ताक्षर")),
]


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for p in P:
        (DATA_DIR / f"{p['code']}.json").write_text(json.dumps(p, ensure_ascii=False, indent=2) + "\n", "utf-8")
    pairs = DATA_DIR / "pairs.json"
    if not pairs.exists():
        pairs.write_text(json.dumps([
            {"source": "en", "target": "ar", "conventions": "Follow passport spelling for names when the client supplies it."}
        ], ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"wrote {len(P)} profiles to {DATA_DIR}")


if __name__ == "__main__":
    main()
