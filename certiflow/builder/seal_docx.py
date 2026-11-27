"""Seal (signature + stamp) in the Word footers: anchored at the template's
measured position, or inline at the top of every footer as a fallback."""
from __future__ import annotations

from docx.enum.text import WD_TAB_ALIGNMENT
from docx.oxml.ns import qn
from docx.shared import Mm, Pt

def _active_footers(docx):
    out = []
    for section in docx.sections:
        out.append((section, section.footer))
        if docx.settings.odd_and_even_pages_header_footer:
            out.append((section, section.even_page_footer))
        if section.different_first_page_header_footer:
            out.append((section, section.first_page_footer))
    return out


def _strip_baked_seal(docx, strip: list[str]):
    import hashlib
    blip_tag = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
    embed = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
    for _, ft in _active_footers(docx):
        for d in list(ft._element.iter(qn("w:drawing"))):
            blip = next(d.iter(blip_tag), None)
            if blip is None:
                continue
            part = ft.part.related_parts.get(blip.get(embed))
            if part is not None and hashlib.sha1(part.blob).hexdigest() in strip:
                run = d.getparent()
                run.getparent().remove(run)


_ANCHOR_XML = """<w:r %s><w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="%d"
 behindDoc="0" locked="1" layoutInCell="1" allowOverlap="1"><wp:simplePos x="0" y="0"/>
<wp:positionH relativeFrom="page"><wp:posOffset>%d</wp:posOffset></wp:positionH>
<wp:positionV relativeFrom="page"><wp:posOffset>%d</wp:posOffset></wp:positionV>
<wp:extent cx="%d" cy="%d"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>
<wp:docPr id="%d" name="%s"/><wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>
<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic>
<pic:nvPicPr><pic:cNvPr id="0" name="%s.png"/><pic:cNvPicPr/></pic:nvPicPr>
<pic:blipFill><a:blip r:embed="%s"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="%d" cy="%d"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
</pic:pic></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r>"""


def _anchored_seal(docx, ctx, seal: SealSpec):
    """Floating signature + stamp at the template's measured position, on every
    page. Kept below the body text area (top clamped to the bottom margin)."""
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls
    from PIL import Image
    EMU = 36000
    _strip_baked_seal(docx, seal.strip_images)
    n = 0
    for section, ft in _active_footers(docx):
        ft.is_linked_to_previous = False
        body_bottom_mm = (section.page_height - section.bottom_margin) / EMU
        par = ft.paragraphs[0] if ft.paragraphs else ft.add_paragraph()
        for key, png, width_mm in (("signature", seal.signature_png, seal.signature_width_mm),
                                   ("stamp", seal.stamp_png, seal.stamp_width_mm)):
            pos = seal.layout[key]
            with Image.open(png) as im:
                h_mm = width_mm * im.height / im.width
            top = max(pos["cy_mm"] - h_mm / 2, body_bottom_mm + 0.5)
            left = pos["cx_mm"] - width_mm / 2
            rid, _ = ft.part.get_or_add_image(str(png))
            n += 1
            xml = _ANCHOR_XML % (nsdecls("w", "wp", "a", "pic", "r"), 251700000 + n, int(left * EMU), int(top * EMU),
                                 int(width_mm * EMU), int(h_mm * EMU), 9000 + n, f"CertiFlow {key} {n}", key, rid,
                                 int(width_mm * EMU), int(h_mm * EMU))
            par._p.append(parse_xml(xml))
        _hidden_marker(par._p, ctx, seal.marker)


def install_seal(docx, ctx, seal: SealSpec):
    if seal.layout:
        return _anchored_seal(docx, ctx, seal)
    return _inline_seal(docx, ctx, seal)


def _inline_seal(docx, ctx, seal: SealSpec):
    """Signature (left) and stamp (right) as inline pictures at the top of every
    footer. Inline footer content grows the footer, so body text can never run
    underneath the seal."""
    for section in docx.sections:
        footers = [section.footer]
        if section.different_first_page_header_footer:
            footers.append(section.first_page_footer)
        if docx.settings.odd_and_even_pages_header_footer:
            footers.append(section.even_page_footer)
        text_w = section.page_width - section.left_margin - section.right_margin
        for ft in footers:
            ft.is_linked_to_previous = False
            par = ft.add_paragraph()
            # move to top of footer
            ft._element.remove(par._p)
            ft._element.insert(0, par._p)
            pf = par.paragraph_format
            pf.space_before = Pt(0)
            pf.space_after = Pt(2)
            pf.tab_stops.add_tab_stop(text_w, WD_TAB_ALIGNMENT.RIGHT)
            par.add_run().add_picture(str(seal.signature_png), width=Mm(seal.signature_width_mm))
            par.add_run("\t")
            par.add_run().add_picture(str(seal.stamp_png), width=Mm(seal.stamp_width_mm))
            _hidden_marker(par._p, ctx, seal.marker)


def _hidden_marker(p_el, ctx, text: str):
    """Invisible marker for the release check. It inherits the paragraph's font, size and language
    and only sets white colour: any own font or size would change the footer's line metrics and move
    the template's floating footer graphics (e.g. the address bar)."""
    from docx.oxml import OxmlElement
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    col = OxmlElement("w:color")
    col.set(qn("w:val"), "FFFFFF")
    rpr.append(col)
    rpr.append(OxmlElement("w:noProof"))
    r.append(rpr)
    t = OxmlElement("w:t")
    t.text = text
    r.append(t)
    p_el.append(r)


# ------------------------------------------------------------------- build

