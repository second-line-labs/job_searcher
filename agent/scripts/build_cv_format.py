"""Builds a CV in the locked format (agent/cv_format_plan.md; structure locked by the user on 2026-11-18).

    python build_cv_format.py --content agent/cv_master.json --out "<folder>/<file>.docx"

The structure lives here and cannot be changed from a content file: eleven parts in a fixed order (name, headline,
proof areas, contact, Professional Summary, Career Highlights, Core Competencies, Professional Experience, Earlier
Career, Education, Certifications with a Training line, Languages), the form of each role (company and dates,
title, scope line, at most six bullets), A4, Arial 10 pt, no tables, real heading style on the section titles.
A content file holds only wording. Tailoring a role = a copy of agent/cv_master.json with the wording changed, built
with this script. The script refuses a content file that adds, drops or reshapes a part.
After building: export the PDF through Word and check that it has two pages (CLAUDE.md section 5).
In a content file, **text** is bold and [text] is an open fact, highlighted yellow.
"""
import argparse
import io
import json
import re
import sys

import docx.opc.constants
from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_COLOR_INDEX, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

FONT = "Arial"
BLUE = RGBColor(0x0F, 0x55, 0x81)
GREY = RGBColor(0x40, 0x40, 0x40)
TEXT_WIDTH = Cm(18.0)  # A4 21.0 cm less 1.5 cm on each side
BODY = 10.0

REQUIRED = ["name", "headline", "proof_areas", "contact", "summary", "highlights", "competencies", "experience",
            "earlier_career", "education", "certifications", "training", "languages"]
OPTIONAL = ["highlights_reserve", "notes"]  # kept in the file for tailoring, never printed
HIGHLIGHTS = 4       # decision 5
COMPETENCY_LINES = 3  # decision 6
MAX_BULLETS = 6      # decision 7
MAX_EARLIER_BULLETS = 2


def check(c):
    """The lock: a content file may change wording only."""
    errors = []
    for k in REQUIRED:
        if k not in c or c[k] in ("", [], None):
            errors.append("missing part: %s" % k)
    for k in c:
        if k not in REQUIRED + OPTIONAL:
            errors.append("unknown part: %s (the structure is locked; a new section needs a decision first)" % k)
    if errors:
        return errors
    for k in ("line", "email", "linkedin"):
        if not c["contact"].get(k):
            errors.append("contact needs: %s" % k)
    if len(c["highlights"]) != HIGHLIGHTS:
        errors.append("Career Highlights must have %d lines, found %d" % (HIGHLIGHTS, len(c["highlights"])))
    if len(c["competencies"]) != COMPETENCY_LINES or not all(x.startswith("**") for x in c["competencies"]):
        errors.append("Core Competencies must be %d lines, each opening with a **label:**" % COMPETENCY_LINES)
    for r in c["experience"]:
        for k in ("company", "dates", "title", "scope", "bullets"):
            if not r.get(k):
                errors.append("experience entry %r needs: %s" % (r.get("company", "?"), k))
        if len(r.get("bullets", [])) > MAX_BULLETS:
            errors.append("%s: at most %d bullets, found %d" % (r.get("company"), MAX_BULLETS, len(r["bullets"])))
        if set(r) - {"company", "dates", "title", "scope", "bullets"}:
            errors.append("%s: unknown field %s" % (r.get("company"), sorted(set(r) - {"company", "dates", "title", "scope", "bullets"})))
    for r in c["earlier_career"]:
        for k in ("company", "dates", "title", "bullets"):
            if not r.get(k):
                errors.append("earlier career entry %r needs: %s" % (r.get("company", "?"), k))
        if len(r.get("bullets", [])) > MAX_EARLIER_BULLETS:
            errors.append("%s: at most %d bullets in Earlier Career" % (r.get("company"), MAX_EARLIER_BULLETS))
    dates = [r["dates"] for r in c["experience"] + c["earlier_career"] if r.get("dates")]
    if any(not re.match(r"^\d{2}/\d{4} – (\d{2}/\d{4}|Present)$", d) for d in dates):
        errors.append("dates must read MM/YYYY – MM/YYYY or MM/YYYY – Present: %s" % [d for d in dates if not re.match(r"^\d{2}/\d{4} – (\d{2}/\d{4}|Present)$", d)])
    return errors


def warnings(c):
    text = json.dumps(c, ensure_ascii=False)
    out = []
    if "—" in text:
        out.append("an em-dash is in the text (style rule: none)")
    def strings(x):
        if isinstance(x, str):
            yield x
        elif isinstance(x, dict):
            for v in x.values():
                yield from strings(v)
        elif isinstance(x, list):
            for v in x:
                yield from strings(v)
    if any(re.search(r"\[.+?\]", s) for k in REQUIRED for s in strings(c[k])):
        out.append("open facts in [brackets] are still in the text; they print highlighted")
    return out


def build(c, out_path, relaxed=False):
    # relaxed (2026-11-19, the user found the page too dense): more space between lines, bullets, roles and
    # sections. The text must then be shorter to stay on two pages; the structure is the same.
    sp = (lambda compact, airy: airy if relaxed else compact)
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(1.5)
    sec.top_margin, sec.bottom_margin = Cm(1.2), Cm(1.3)
    sec.header_distance, sec.footer_distance = Cm(0.6), Cm(0.6)

    def force_font(rpr_owner, name=FONT):
        """Arial by name, with the theme-font attributes removed (they would win over the name)."""
        rpr = rpr_owner.get_or_add_rPr()
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            rpr.insert(0, rf)
        for a in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
            if rf.get(qn(a)) is not None:
                del rf.attrib[qn(a)]
        for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rf.set(qn(a), name)

    defaults = doc.styles.element.find(qn("w:docDefaults"))
    if defaults is not None:
        rf = defaults.find(".//" + qn("w:rFonts"))
        if rf is not None:
            for a in list(rf.attrib):
                del rf.attrib[a]
            for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
                rf.set(qn(a), FONT)

    def style(name, size=None, bold=None, italic=None, color=None, before=0, after=0, keep_next=False, builtin=False):
        st = doc.styles[name] if builtin else doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        if not builtin:
            st.base_style = doc.styles["Normal"]
        force_font(st.element)
        st.font.name = FONT
        if size:
            st.font.size = Pt(size)
        if bold is not None:
            st.font.bold = bold
        if italic is not None:
            st.font.italic = italic
        if color is not None:
            st.font.color.rgb = color
        pf = st.paragraph_format
        pf.space_before, pf.space_after = Pt(before), Pt(after)
        pf.line_spacing = sp(1.0, 1.08)
        pf.keep_with_next = keep_next
        return st

    style("Normal", size=BODY, builtin=True)
    h1 = style("Heading 1", size=BODY + 1.5, bold=True, color=BLUE, before=sp(8, 13), after=sp(3, 4), keep_next=True, builtin=True)
    bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    for k, v in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"), ("w:color", "0F5581")):
        bottom.set(qn(k), v)
    bdr.append(bottom)
    h1.element.get_or_add_pPr().insert_element_before(
        bdr, "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct", "w:topLinePunct",
        "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind",
        "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment",
        "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange")
    lb = style("List Bullet", size=BODY, after=sp(1, 3), builtin=True)
    lb.paragraph_format.keep_together = True  # a bullet never splits across two pages
    style("CV Name", size=20, bold=True, after=1)
    style("CV Headline", size=12, bold=True, color=BLUE, after=1)
    style("CV Tagline", size=BODY, color=GREY, after=2)
    style("CV Contact", size=BODY - 0.5, after=0)
    style("CV Text", size=BODY, after=sp(2, 3))
    role = style("CV Role", size=BODY, bold=True, before=sp(5, 9), keep_next=True)
    role.paragraph_format.tab_stops.add_tab_stop(TEXT_WIDTH, WD_TAB_ALIGNMENT.RIGHT)
    style("CV Title", size=BODY, italic=True, keep_next=True)
    style("CV Scope", size=BODY, after=sp(2, 3), keep_next=True)
    style("CV Line", size=BODY, after=sp(1, 2.5))

    def runs(p, text):
        """Text with **bold** lead-ins and [open facts] highlighted."""
        for chunk in re.split(r"(\*\*.+?\*\*|\[.+?\])", text):
            if not chunk:
                continue
            if chunk.startswith("**"):
                p.add_run(chunk[2:-2]).bold = True
            elif chunk.startswith("["):
                p.add_run(chunk).font.highlight_color = WD_COLOR_INDEX.YELLOW
            else:
                p.add_run(chunk)
        return p

    def para(style_name, text):
        return runs(doc.add_paragraph(style=style_name), text)

    def heading(text):
        return doc.add_paragraph(text, style="Heading 1")

    def bullet(text):
        p = runs(doc.add_paragraph(style="List Bullet"), text)
        p.paragraph_format.left_indent = Cm(0.5)
        p.paragraph_format.first_line_indent = Cm(-0.4)
        return p

    def link(p, text, url):
        rid = p.part.relate_to(url, docx.opc.constants.RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
        h = OxmlElement("w:hyperlink")
        h.set(qn("r:id"), rid)
        r = OxmlElement("w:r")
        t = OxmlElement("w:t")
        t.text = text
        r.append(t)
        h.append(r)
        p._p.append(h)

    def field(p, instr, shown):
        for kind, val in (("begin", None), ("instr", instr), ("separate", None), ("text", shown), ("end", None)):
            r = p.add_run()
            if kind == "instr":
                el = OxmlElement("w:instrText")
                el.set(qn("xml:space"), "preserve")
                el.text = val
                r._r.append(el)
            elif kind == "text":
                r.text = val
            else:
                el = OxmlElement("w:fldChar")
                el.set(qn("w:fldCharType"), kind)
                r._r.append(el)

    def roles(entries, with_scope):
        for r in entries:
            runs(doc.add_paragraph(style="CV Role"), r["company"] + "\t" + r["dates"])
            para("CV Title", r["title"])
            if with_scope:
                para("CV Scope", "**Scope:** " + r["scope"])
            made = [bullet(b) for b in r["bullets"]]
            for p in made[:-1]:  # a role is not split across two pages (2026-11-18); the two-page check catches overflow
                p.paragraph_format.keep_with_next = True

    # 1 to 3: name, headline, proof areas, contact
    para("CV Name", c["name"])
    para("CV Headline", c["headline"])
    para("CV Tagline", c["proof_areas"])
    p = doc.add_paragraph(style="CV Contact")
    p.add_run(c["contact"]["line"] + " | ")
    link(p, c["contact"]["email"], "mailto:" + c["contact"]["email"])
    p.add_run(" | ")
    link(p, c["contact"]["linkedin"], "https://" + c["contact"]["linkedin"].rstrip("/") + "/")
    # 4 to 6
    heading("Professional Summary")
    para("CV Text", c["summary"])
    heading("Career Highlights")
    for x in c["highlights"]:
        bullet(x)
    heading("Core Competencies")
    for x in c["competencies"]:
        para("CV Line", x)
    # 7 and 8
    heading("Professional Experience")
    roles(c["experience"], True)
    heading("Earlier Career")
    roles(c["earlier_career"], False)
    # 9 to 11
    heading("Education")
    for x in c["education"]:
        para("CV Line", x)
    heading("Certifications")
    for x in c["certifications"]:
        para("CV Line", x)
    tr = para("CV Line", "**Training:** " + c["training"])
    tr.paragraph_format.space_before = Pt(BODY * 1.15)  # one empty line above the training line (user, 2026-11-18)
    heading("Languages")
    para("CV Line", c["languages"])

    f = sec.footer.paragraphs[0]
    f.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    f.add_run(c["name"] + " | Page ")
    field(f, "PAGE", "1")
    f.add_run(" of ")
    field(f, "NUMPAGES", "2")
    for r in f.runs:
        r.font.size = Pt(8)
        r.font.color.rgb = GREY
        r.font.name = FONT
    zoom = doc.settings.element.find(qn("w:zoom"))
    if zoom is not None and zoom.get(qn("w:percent")) is None:
        zoom.set(qn("w:percent"), "100")  # the library's template leaves it out; the schema requires it
    cp = doc.core_properties
    cp.title, cp.author, cp.last_modified_by = c["name"] + " - Curriculum Vitae", c["name"], c["name"]
    cp.comments, cp.subject, cp.keywords = "", "Curriculum Vitae", ""
    doc.save(out_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--content", required=True, help="content file (a copy of agent/cv_master.json with the wording changed)")
    ap.add_argument("--out", required=True, help="the .docx to write")
    ap.add_argument("--check", action="store_true", help="check the content file only, write nothing")
    ap.add_argument("--layout", default="compact", choices=["compact", "relaxed"],
                    help="relaxed = more white space; needs shorter text to stay on two pages")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    c = json.loads(io.open(a.content, encoding="utf-8").read())
    errors = check(c)
    if errors:
        sys.exit("not built, the content file breaks the locked structure:\n- " + "\n- ".join(errors))
    for w in warnings(c):
        print("! " + w)
    if a.check:
        print("content file fits the locked structure")
        return
    build(c, a.out, relaxed=a.layout == "relaxed")
    print("saved", a.out)


if __name__ == "__main__":
    main()
