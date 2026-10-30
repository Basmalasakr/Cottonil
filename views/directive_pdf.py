# -*- coding: utf-8 -*-
"""
directive_pdf.py
================
Professional Arabic / English PDF generation for the Cotonil logistics directive.

Design choices (one clear solution, no mixing of PDF libraries):
  * fpdf2                 -> PDF writing (plain API only: cell / line / ellipse / add_font)
  * arabic-reshaper       -> joins Arabic letters into their correct contextual forms
  * python-bidi           -> visual re-ordering (RTL base direction, English/numbers stay LTR)

IMPORTANT - no double processing:
  fpdf2's own text shaping (`set_text_shaping`) is NEVER enabled here. Every line is
  wrapped in *logical* order first, and only then reshaped + bidi-reordered ONCE per
  visual line. Reversing a whole paragraph (or reshaping twice) would break numbers,
  English words and line order, so it is deliberately avoided.

Public API
----------
generate_directive_pdf(text, lang="ar", title=None, issue_date=None, font_dir=None)
    -> (pdf_bytes | None, error_message | None)
diagnose(lang="ar") -> str          (versions, font search paths - for support)
find_fonts(lang="ar", font_dir=None) -> FontSet
parse_markdown(text) -> list[Block]
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

__all__ = [
    "generate_directive_pdf",
    "diagnose",
    "find_fonts",
    "parse_markdown",
    "clean_text",
    "DirectivePdfError",
    "FontNotFoundError",
    "DependencyError",
    "Block",
    "FontSet",
]


# ----------------------------------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------------------------------
class DirectivePdfError(Exception):
    """Base class: the message is already user-readable."""


class FontNotFoundError(DirectivePdfError):
    pass


class DependencyError(DirectivePdfError):
    pass


def _t(lang: str, ar: str, en: str) -> str:
    return ar if lang == "ar" else en


def _norm_lang(lang: Optional[str]) -> str:
    return "ar" if str(lang or "ar").lower().startswith("ar") else "en"


# ----------------------------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------------------------
STRINGS: Dict[str, Dict[str, str]] = {
    "ar": {
        "title": "أمر تكليف لوجستي \u2013 شركة قطونيل",
        "brand": "قطونيل",
        "doc_type": "أمر تكليف لوجستي",
        "issue": "تاريخ الإصدار",
        "page": "صفحة",
        "of": "من",
    },
    "en": {
        "title": "Logistics Directive \u2013 Cotonil",
        "brand": "Cotonil",
        "doc_type": "Logistics Directive",
        "issue": "Issue date",
        "page": "Page",
        "of": "of",
    },
}

# colours (R, G, B)
C_TEXT = (15, 23, 42)
C_HEAD = (30, 58, 138)
C_MUTED = (100, 116, 139)
C_RULE = (203, 213, 225)

PT_TO_MM = 25.4 / 72.0

# page geometry (mm, A4 portrait)
MARGIN_X = 20.0
HEADER_BOTTOM = 18.0
CONTENT_TOP = 27.0
FOOTER_Y = 285.0
CONTENT_BOTTOM = 280.0
INDENT_STEP = 6.0
BULLET_W = 6.0
NUMBER_W = 9.0
LEAD_GAP = 1.8

# Font families: (label, regular file, bold file). First usable family wins.
FONT_FAMILIES: Sequence[Tuple[str, str, str]] = (
    ("Amiri", "Amiri-Regular.ttf", "Amiri-Bold.ttf"),
    ("Noto Naskh Arabic", "NotoNaskhArabic-Regular.ttf", "NotoNaskhArabic-Bold.ttf"),
    ("Noto Sans Arabic", "NotoSansArabic-Regular.ttf", "NotoSansArabic-Bold.ttf"),
    ("DejaVu Sans", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    ("Arial", "arial.ttf", "arialbd.ttf"),
    ("Tahoma", "tahoma.ttf", "tahomabd.ttf"),
)

# Code points a font MUST have to be accepted (basic letter + the presentation forms that
# arabic-reshaper produces: isolated alef, lam-alef ligature, initial/medial lam).
REQUIRED_CODEPOINTS = (0x0020, 0x0030, 0x0041, 0x0627, 0xFE8D, 0xFEFB, 0xFEDF, 0xFEE0)

_SYSTEM_FONT_DIRS = (
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "~/.fonts",
    "~/.local/share/fonts",
    "/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
    "~/Library/Fonts",
    "C:\\Windows\\Fonts",
)

# typographic characters replaced when the chosen font lacks them
_FALLBACK_MAP = {
    "\u2013": "-", "\u2014": "-", "\u2011": "-", "\u2022": "-", "\u2026": "...",
    "\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'", "\u00a0": " ",
}


# ----------------------------------------------------------------------------------------------
# Library loading (version tolerant)
# ----------------------------------------------------------------------------------------------
def _load_libs(lang: str):
    try:
        from fpdf import FPDF  # fpdf2
    except ImportError as e:  # pragma: no cover - depends on environment
        raise DependencyError(_t(
            lang,
            "مكتبة fpdf2 غير مثبتة. نفّذ: pip install fpdf2",
            "The fpdf2 package is not installed. Run: pip install fpdf2",
        )) from e
    try:
        import arabic_reshaper
    except ImportError as e:  # pragma: no cover
        raise DependencyError(_t(
            lang,
            "مكتبة arabic-reshaper غير مثبتة. نفّذ: pip install arabic-reshaper",
            "The arabic-reshaper package is not installed. Run: pip install arabic-reshaper",
        )) from e
    try:  # python-bidi >= 0.5 exposes get_display at package level
        from bidi import get_display
    except ImportError:
        try:  # python-bidi <= 0.4.x
            from bidi.algorithm import get_display
        except ImportError as e:  # pragma: no cover
            raise DependencyError(_t(
                lang,
                "مكتبة python-bidi غير مثبتة. نفّذ: pip install python-bidi",
                "The python-bidi package is not installed. Run: pip install python-bidi",
            )) from e
    return FPDF, arabic_reshaper, get_display


# ----------------------------------------------------------------------------------------------
# Font discovery (never downloads anything)
# ----------------------------------------------------------------------------------------------
@dataclass
class FontSet:
    label: str
    regular: str
    bold: Optional[str]
    cmap: Set[int]


def _project_dirs(font_dir: Optional[str]) -> List[Path]:
    here = Path(__file__).resolve().parent
    dirs: List[Path] = []
    if font_dir:
        dirs.append(Path(font_dir).expanduser())
    env_dir = os.environ.get("COTONIL_FONT_DIR")
    if env_dir:
        dirs.append(Path(env_dir).expanduser())
    dirs += [here / "fonts", here, here.parent / "fonts", Path.cwd() / "fonts", Path.cwd()]
    seen, out = set(), []
    for d in dirs:
        key = str(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def _system_index() -> Dict[str, str]:
    """lower-case file name -> path, for the usual system font folders (depth-limited)."""
    index: Dict[str, str] = {}
    budget = 60000
    for raw in _SYSTEM_FONT_DIRS:
        base = os.path.expanduser(raw)
        if not os.path.isdir(base):
            continue
        base_depth = base.rstrip(os.sep).count(os.sep)
        for root, dirs, files in os.walk(base):
            if root.count(os.sep) - base_depth >= 5:
                dirs[:] = []
            for f in files:
                budget -= 1
                if f.lower().endswith(".ttf"):
                    index.setdefault(f.lower(), os.path.join(root, f))
            if budget <= 0:
                return index
    return index


def _read_cmap(path: str) -> Set[int]:
    from fontTools.ttLib import TTFont  # installed together with fpdf2

    font = TTFont(path, lazy=True)
    try:
        cmap = font.getBestCmap() or {}
        return set(cmap.keys())
    finally:
        font.close()


def _supports_arabic(cmap: Set[int]) -> bool:
    return all(cp in cmap for cp in REQUIRED_CODEPOINTS)


def _search_dirs_text(font_dir: Optional[str]) -> str:
    return "\n".join(f"  - {d}" for d in _project_dirs(font_dir)) + "\n  - (system font folders)"


_FONT_CACHE: Dict[Tuple[str, str], FontSet] = {}


def find_fonts(lang: str = "ar", font_dir: Optional[str] = None) -> FontSet:
    """Return the first usable font family. Raises FontNotFoundError with install steps."""
    lang = _norm_lang(lang)
    key = (lang, str(font_dir or ""))
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]

    proj_dirs = _project_dirs(font_dir)
    sys_index: Optional[Dict[str, str]] = None
    rejected: List[str] = []

    for label, reg_name, bold_name in FONT_FAMILIES:
        reg_path = None
        for d in proj_dirs:
            cand = d / reg_name
            if cand.is_file():
                reg_path = str(cand)
                break
        if reg_path is None:
            if sys_index is None:
                sys_index = _system_index()
            reg_path = sys_index.get(reg_name.lower())
        if reg_path is None:
            continue
        try:
            cmap = _read_cmap(reg_path)
        except Exception as e:  # unreadable / corrupted font file
            rejected.append(f"{reg_path} ({type(e).__name__}: {e})")
            continue
        if not _supports_arabic(cmap):
            rejected.append(f"{reg_path} ({_t(lang, 'لا يدعم الحروف العربية المطلوبة', 'lacks required Arabic glyphs')})")
            continue
        bold_path = None
        reg_dir = Path(reg_path).parent
        bcand = reg_dir / bold_name
        if bcand.is_file():
            bold_path = str(bcand)
        else:
            for d in proj_dirs:
                if (d / bold_name).is_file():
                    bold_path = str(d / bold_name)
                    break
            if bold_path is None and sys_index is not None:
                bold_path = sys_index.get(bold_name.lower())
        fs = FontSet(label=label, regular=reg_path, bold=bold_path, cmap=cmap)
        _FONT_CACHE[key] = fs
        return fs

    default_dir = Path(__file__).resolve().parent / "fonts"
    msg = _t(
        lang,
        "لم يتم العثور على خط عربي صالح لإنشاء ملف PDF.\n"
        f"الحل: ضع الملف Amiri-Regular.ttf (ويفضّل Amiri-Bold.ttf معه) داخل المجلد:\n  {default_dir}\n"
        "ثم أعد المحاولة. الخط مجاني (ترخيص OFL) ويُنزَّل مرة واحدة يدوياً من "
        "https://github.com/aliftype/amiri/releases أو https://fonts.google.com/specimen/Amiri "
        "(على Debian/Ubuntu يمكن تثبيت الحزمة fonts-hosny-amiri بدلاً من ذلك).\n"
        "المجلدات التي تم البحث فيها:\n",
        "No usable Arabic font was found for PDF generation.\n"
        f"Fix: put Amiri-Regular.ttf (ideally with Amiri-Bold.ttf) in:\n  {default_dir}\n"
        "then try again. The font is free (OFL licence); download it once manually from "
        "https://github.com/aliftype/amiri/releases or https://fonts.google.com/specimen/Amiri "
        "(on Debian/Ubuntu you can install the package fonts-hosny-amiri instead).\n"
        "Folders searched:\n",
    ) + _search_dirs_text(font_dir)
    if rejected:
        msg += _t(lang, "\nخطوط وُجدت لكن تم رفضها:\n", "\nFonts found but rejected:\n") + "\n".join(f"  - {r}" for r in rejected)
    raise FontNotFoundError(msg)


# ----------------------------------------------------------------------------------------------
# Text cleaning + lightweight Markdown parsing
# ----------------------------------------------------------------------------------------------
_CONTROL_RE = re.compile("[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff\u00ad]")
_HTML_TAG_RE = re.compile(r"</?(?:br|b|i|u|strong|em|p|div|span|ul|ol|li|h[1-6])\b[^>]*>", re.I)


def clean_text(text: str, cmap: Optional[Set[int]] = None) -> str:
    """Normalise newlines, strip HTML-ish tags / invisible controls, drop glyphs the font lacks."""
    s = str(text or "")
    s = s.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = _HTML_TAG_RE.sub("", s)
    s = _CONTROL_RE.sub("", s)
    if cmap is None:
        return s
    out: List[str] = []
    for ch in s:
        if ch == "\n" or ord(ch) in cmap:
            out.append(ch)
        elif ch in _FALLBACK_MAP:
            out.append(_FALLBACK_MAP[ch])
        elif ch.isspace():
            out.append(" ")
        # anything else (emoji, symbols the font cannot draw) is dropped on purpose
    return "".join(out)


@dataclass
class Block:
    kind: str                # heading | subheading | para | bullet | number | rule | space
    text: str = ""
    lead: str = ""           # bold label at the start ("**Label:** rest")
    marker: str = ""         # list number
    level: int = 0           # indent level for nested bullets
    bold: bool = False       # whole text is bold


_RE_RULE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
_RE_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_RE_BULLET = re.compile(r"^(\s*)[-*+\u2022\u00b7\u25aa\u25cf\u25e6\u2013\u2014]\s+(.*)$")
_RE_NUMBER = re.compile(r"^(\s*)([0-9\u0660-\u0669]{1,3})[.)\-]\s+(.*)$")
_RE_QUOTE = re.compile(r"^\s*>+\s?(.*)$")
_RE_TABLE_SEP = re.compile(r"^\s*\|?[\s:|\-]+\|?\s*$")
_RE_BOLD_FULL = re.compile(r"^\s*(\*\*|__)(.+?)\1\s*[:\uff1a]?\s*$")
_RE_BOLD_LEAD = re.compile(r"^\s*(\*\*|__)(.+?)\1\s*(.*)$")


def _inline_clean(s: str) -> str:
    """Remove inline Markdown markers (partial bold/italic/code cannot be styled mid-line)."""
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", s)
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"\1", s)
    s = s.replace("`", "").replace("**", "")
    return re.sub(r"[ ]{2,}", " ", s).strip()


def _split_lead(text: str) -> Tuple[str, str, bool]:
    """'**Label:** rest' -> (label, rest, False); '**whole**' -> ('', whole, True)."""
    full = _RE_BOLD_FULL.match(text)
    if full:
        return "", _inline_clean(full.group(2)), True   # no lead; the whole text is bold
    m = _RE_BOLD_LEAD.match(text)
    if m:
        label = _inline_clean(m.group(2))
        rest = m.group(3)
        if rest[:1] in (":", "\uff1a"):
            label = label.rstrip(":\uff1a") + ":"
            rest = rest[1:]
        rest = _inline_clean(rest)
        if label and rest:
            return label, rest, False
    return "", _inline_clean(text), False


def parse_markdown(text: str) -> List[Block]:
    blocks: List[Block] = []
    for raw in str(text or "").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            if blocks and blocks[-1].kind != "space":
                blocks.append(Block("space"))
            continue
        if _RE_RULE.match(line):
            blocks.append(Block("rule"))
            continue
        h = _RE_HEADING.match(line)
        if h:
            level = len(h.group(1))
            blocks.append(Block("heading" if level == 1 else "subheading", text=_inline_clean(h.group(2)), bold=True))
            continue
        if line.strip().startswith("|") and line.strip().endswith("|"):
            if _RE_TABLE_SEP.match(line):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|") if c.strip()]
            blocks.append(Block("para", text=_inline_clean(" - ".join(cells))))
            continue
        q = _RE_QUOTE.match(line)
        if q:
            line = q.group(1)
            if not line.strip():
                continue
        b = _RE_BULLET.match(line)
        if b:
            lead, body, bold = _split_lead(b.group(2))
            blocks.append(Block("bullet", text=body, lead=lead, bold=bold, level=min(len(b.group(1).expandtabs(4)) // 2, 2)))
            continue
        n = _RE_NUMBER.match(line)
        if n:
            lead, body, bold = _split_lead(n.group(3))
            blocks.append(Block("number", text=body, lead=lead, bold=bold, marker=n.group(2) + ".",
                                level=min(len(n.group(1).expandtabs(4)) // 2, 2)))
            continue
        lead, body, bold = _split_lead(line)
        if bold and not lead:
            blocks.append(Block("subheading", text=body, bold=True))
        else:
            blocks.append(Block("para", text=body, lead=lead))
    while blocks and blocks[-1].kind == "space":
        blocks.pop()
    while blocks and blocks[0].kind == "space":
        blocks.pop(0)
    return blocks


# ----------------------------------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------------------------------
class _Renderer:
    FAMILY = "DirFont"

    def __init__(self, lang: str, libs, fonts: FontSet, title: str, issue_date: _dt.date, total_pages: Optional[int]):
        self.lang = lang
        self.rtl = lang == "ar"
        self.FPDF, self.reshaper, self.get_display = libs
        self.fonts = fonts
        self.title = title
        self.issue_date = issue_date
        self.total_pages = total_pages
        self.strings = STRINGS[lang]
        self.body_size = 13.0 if self.rtl else 11.0
        self.lh_factor = 1.75 if self.rtl else 1.55
        self.pdf = None

    # ---- shaping -------------------------------------------------------------------------
    def reshape(self, s: str) -> str:
        return self.reshaper.reshape(s)

    def shape(self, s: str) -> str:
        """Logical -> visual string. Applied exactly once per visual line."""
        reshaped = self.reshape(s)
        direction = "R" if self.rtl else "L"
        try:
            return self.get_display(reshaped, base_dir=direction)
        except TypeError:  # very old python-bidi without base_dir
            return self.get_display(reshaped)

    def width(self, s: str) -> float:
        return self.pdf.get_string_width(self.reshape(s))

    # ---- low level drawing ---------------------------------------------------------------
    def _font(self, bold: bool, size: float, color=C_TEXT) -> None:
        style = "B" if (bold and self.fonts.bold) else ""
        self.pdf.set_font(self.FAMILY, style, size)
        self.pdf.set_text_color(*color)

    def _cell(self, x0: float, y: float, w: float, h: float, visual: str, align: str) -> None:
        self.pdf.set_xy(x0, y)
        try:
            self.pdf.cell(w, h, text=visual, align=align)
        except TypeError:  # fpdf2 < 2.7.6 uses `txt`
            self.pdf.cell(w, h, txt=visual, align=align)

    def _lh(self, size: float) -> float:
        return size * PT_TO_MM * self.lh_factor

    def _ensure(self, needed: float) -> None:
        if self.pdf.get_y() + needed > CONTENT_BOTTOM:
            self.pdf.add_page()
            self.pdf.set_y(CONTENT_TOP)

    # ---- header / footer (called by fpdf2 on every page) -----------------------------------
    def draw_header(self) -> None:
        pdf = self.pdf
        left, right = MARGIN_X, pdf.w - MARGIN_X
        half = (right - left) / 2.0
        brand = self.shape(self.strings["brand"])
        doc = self.shape(self.strings["doc_type"])
        self._font(True, 11, C_HEAD)
        if self.rtl:
            self._cell(left + half, 8.0, half, 6.0, brand, "R")
            self._font(False, 9, C_MUTED)
            self._cell(left, 8.5, half, 6.0, doc, "L")
        else:
            self._cell(left, 8.0, half, 6.0, brand, "L")
            self._font(False, 9, C_MUTED)
            self._cell(left + half, 8.5, half, 6.0, doc, "R")
        pdf.set_draw_color(*C_RULE)
        pdf.set_line_width(0.3)
        pdf.line(left, HEADER_BOTTOM, right, HEADER_BOTTOM)

    def draw_footer(self) -> None:
        pdf = self.pdf
        left, right = MARGIN_X, pdf.w - MARGIN_X
        pdf.set_draw_color(*C_RULE)
        pdf.set_line_width(0.3)
        pdf.line(left, FOOTER_Y, right, FOOTER_Y)
        n = pdf.page_no()
        if self.total_pages:
            logical = f"{self.strings['page']} {n} {self.strings['of']} {self.total_pages}"
        else:
            logical = f"{self.strings['page']} {n}"
        self._font(False, 9, C_MUTED)
        self._cell(left, FOOTER_Y + 2.0, right - left, 6.0, self.shape(logical), "C")

    # ---- wrapping --------------------------------------------------------------------------
    def _fit_prefix(self, word: str, limit: float) -> int:
        k = 1
        while k < len(word) and self.width(word[: k + 1]) <= limit:
            k += 1
        return k

    def wrap(self, text: str, first_w: float, w: float) -> List[str]:
        """Greedy wrap in LOGICAL order (measured on the reshaped string, bidi not needed for width)."""
        words = text.split()
        lines: List[str] = []
        cur = ""
        limit = max(first_w, 1.0)
        for word in words:
            cand = word if not cur else cur + " " + word
            if self.width(cand) <= limit:
                cur = cand
                continue
            if cur:
                lines.append(cur)
                cur = ""
                limit = w
            while self.width(word) > limit:  # a single very long token: hard split
                k = self._fit_prefix(word, limit)
                lines.append(word[:k])
                word = word[k:]
                limit = w
            cur = word
        if cur or not lines:
            lines.append(cur)
        return lines

    # ---- blocks ----------------------------------------------------------------------------
    def _text_block(self, b: Block, size: float, color=C_TEXT, gap_after: float = 1.4) -> None:
        pdf = self.pdf
        lh = self._lh(size)
        shift = b.level * INDENT_STEP
        marker_w = BULLET_W if b.kind == "bullet" else (NUMBER_W if b.kind == "number" else 0.0)
        if self.rtl:
            zone_edge = pdf.w - MARGIN_X - shift          # where the marker sits (right side)
            text_right = zone_edge - marker_w
            text_left = MARGIN_X
        else:
            zone_edge = MARGIN_X + shift                  # marker on the left
            text_left = zone_edge + marker_w
            text_right = pdf.w - MARGIN_X
        avail = text_right - text_left
        align = "R" if self.rtl else "L"

        lead = b.lead
        lead_w = 0.0
        if lead:
            self._font(True, size, color)
            lead_w = self.width(lead)
            if lead_w > 0.5 * avail:      # a very long label: render everything as normal text
                b = Block(b.kind, text=f"{lead} {b.text}".strip(), marker=b.marker, level=b.level)
                lead, lead_w = "", 0.0

        self._font(b.bold, size, color)
        first_w = avail - (lead_w + LEAD_GAP if lead else 0.0)
        lines = self.wrap(b.text, first_w, avail)

        for i, line in enumerate(lines):
            self._ensure(lh)
            y = pdf.get_y()
            if i == 0 and b.kind == "bullet":
                d = 1.6
                cx = (zone_edge - 1.4) if self.rtl else (zone_edge + 1.4)
                pdf.set_fill_color(*C_HEAD)
                pdf.ellipse(cx - d / 2.0, y + lh / 2.0 - d / 2.0, d, d, style="F")
            elif i == 0 and b.kind == "number":
                self._font(True, size, C_HEAD)
                if self.rtl:
                    self._cell(zone_edge - NUMBER_W, y, NUMBER_W - 1.0, lh, self.shape(b.marker), "R")
                else:
                    self._cell(zone_edge, y, NUMBER_W - 1.0, lh, self.shape(b.marker), "L")
            if i == 0 and lead:
                self._font(True, size, color)
                lead_visual = self.shape(lead)
                self._font(False, size, color)  # body font for the first line
                body_visual = self.shape(line)
                self._font(True, size, color)
                if self.rtl:
                    self._cell(text_right - lead_w, y, lead_w, lh, lead_visual, "R")
                    self._font(b.bold, size, color)
                    self._cell(text_left, y, avail - lead_w - LEAD_GAP, lh, body_visual, "R")
                else:
                    self._cell(text_left, y, lead_w, lh, lead_visual, "L")
                    self._font(b.bold, size, color)
                    self._cell(text_left + lead_w + LEAD_GAP, y, avail - lead_w - LEAD_GAP, lh, body_visual, "L")
            else:
                self._font(b.bold, size, color)
                self._cell(text_left, y, avail, lh, self.shape(line), align)
            pdf.set_y(y + lh)
        pdf.set_y(pdf.get_y() + gap_after)

    def _heading(self, b: Block) -> None:
        size = self.body_size + (3.0 if b.kind == "heading" else 1.5)
        lh = self._lh(size)
        self._ensure(lh + 2 * self._lh(self.body_size) + 3.5)
        self.pdf.set_y(self.pdf.get_y() + 3.0)
        self._text_block(Block("para", text=b.text, bold=True), size, color=C_HEAD, gap_after=1.0)

    def _rule(self) -> None:
        self._ensure(4.0)
        y = self.pdf.get_y() + 1.5
        self.pdf.set_draw_color(*C_RULE)
        self.pdf.set_line_width(0.3)
        self.pdf.line(MARGIN_X, y, self.pdf.w - MARGIN_X, y)
        self.pdf.set_y(y + 2.5)

    def _title_block(self) -> None:
        pdf = self.pdf
        width = pdf.w - 2 * MARGIN_X
        size = 20.0
        self._font(True, size, C_HEAD)
        lines = self.wrap(self.title, width, width)
        lh = self._lh(size)
        for line in lines:
            y = pdf.get_y()
            self._font(True, size, C_HEAD)
            self._cell(MARGIN_X, y, width, lh, self.shape(line), "C")
            pdf.set_y(y + lh)
        pdf.set_y(pdf.get_y() + 1.0)
        pdf.set_draw_color(*C_HEAD)
        pdf.set_line_width(0.7)
        pdf.line(MARGIN_X + 30, pdf.get_y(), pdf.w - MARGIN_X - 30, pdf.get_y())
        pdf.set_y(pdf.get_y() + 2.5)
        meta = f"{self.strings['issue']}: {self.issue_date.isoformat()}"
        self._font(False, 10, C_MUTED)
        y = pdf.get_y()
        self._cell(MARGIN_X, y, width, self._lh(10), self.shape(meta), "C")
        pdf.set_y(y + self._lh(10) + 5.0)

    # ---- entry point -----------------------------------------------------------------------
    def render(self, blocks: List[Block]) -> Tuple[bytes, int]:
        renderer = self

        class _Pdf(self.FPDF):  # header()/footer() are invoked by fpdf2 on each page
            def header(inner):  # noqa: N805
                renderer.draw_header()

            def footer(inner):  # noqa: N805
                renderer.draw_footer()

        pdf = _Pdf(orientation="P", unit="mm", format="A4")
        self.pdf = pdf
        pdf.set_auto_page_break(False)
        pdf.set_margins(MARGIN_X, CONTENT_TOP, MARGIN_X)
        try:
            pdf.c_margin = 0  # exact alignment of right/left aligned cells
        except Exception:  # pragma: no cover
            pass
        pdf.add_font(self.FAMILY, "", self.fonts.regular)
        if self.fonts.bold:
            pdf.add_font(self.FAMILY, "B", self.fonts.bold)
        try:
            pdf.set_title(self.title)
            pdf.set_author("Cotonil Command Center")
            pdf.set_subject(self.strings["doc_type"])
        except Exception:  # pragma: no cover - metadata is optional
            pass

        pdf.add_page()
        pdf.set_y(CONTENT_TOP)
        self._title_block()

        for b in blocks:
            if b.kind == "space":
                pdf.set_y(pdf.get_y() + 2.0)
            elif b.kind == "rule":
                self._rule()
            elif b.kind in ("heading", "subheading"):
                self._heading(b)
            else:
                self._text_block(b, self.body_size, gap_after=0.8 if b.kind in ("bullet", "number") else 1.8)

        pages = pdf.page_no()
        data = pdf.output()
        if isinstance(data, str):  # extremely old fpdf2 returned latin-1 str
            data = data.encode("latin-1")
        return bytes(data), pages


# ----------------------------------------------------------------------------------------------
# Public functions
# ----------------------------------------------------------------------------------------------
def _is_valid_pdf(data: bytes) -> bool:
    return bool(data) and data.startswith(b"%PDF") and b"%%EOF" in data[-1024:]


def generate_directive_pdf(
    text: str,
    lang: str = "ar",
    title: Optional[str] = None,
    issue_date: Optional[_dt.date] = None,
    font_dir: Optional[str] = None,
) -> Tuple[Optional[bytes], Optional[str]]:
    """Build the directive PDF. Returns (bytes, None) on success or (None, readable_error)."""
    lang = _norm_lang(lang)
    try:
        libs = _load_libs(lang)
        fonts = find_fonts(lang, font_dir)
        blocks = parse_markdown(clean_text(text, fonts.cmap))
        if not any(b.kind not in ("space", "rule") and b.text.strip() for b in blocks):
            raise DirectivePdfError(_t(lang, "لا يوجد نص لإنشاء ملف PDF.", "There is no text to build the PDF from."))

        doc_title = title or STRINGS[lang]["title"]
        doc_date = issue_date or _dt.date.today()

        # pass 1: count pages; pass 2: final document with "Page X of N" footer
        _, pages = _Renderer(lang, libs, fonts, doc_title, doc_date, None).render(blocks)
        data, pages2 = _Renderer(lang, libs, fonts, doc_title, doc_date, pages).render(blocks)
        if pages2 != pages:  # footer text never changes layout, but never trust silently
            data, _ = _Renderer(lang, libs, fonts, doc_title, doc_date, pages2).render(blocks)

        if not _is_valid_pdf(data):
            raise DirectivePdfError(_t(lang, "الملف الناتج ليس PDF صالحاً.", "The generated file is not a valid PDF."))
        return data, None
    except DirectivePdfError as e:
        return None, str(e)
    except Exception as e:  # unexpected: keep type + location so it can be fixed, never a vague message
        tb = traceback.extract_tb(e.__traceback__)
        where = f" [{os.path.basename(tb[-1].filename)}:{tb[-1].lineno}]" if tb else ""
        return None, _t(lang, "خطأ غير متوقع أثناء بناء PDF: ", "Unexpected error while building the PDF: ") + f"{type(e).__name__}: {e}{where}"


def diagnose(lang: str = "ar") -> str:
    """Human-readable environment report (versions, chosen font, searched folders)."""
    lang = _norm_lang(lang)
    from importlib import metadata

    lines = [f"Python {sys.version.split()[0]}"]
    for pkg in ("fpdf2", "arabic-reshaper", "python-bidi", "fonttools"):
        try:
            lines.append(f"{pkg}: {metadata.version(pkg)}")
        except metadata.PackageNotFoundError:
            lines.append(f"{pkg}: NOT INSTALLED")
    try:
        fs = find_fonts(lang)
        lines.append(f"font: {fs.label} -> {fs.regular}")
        lines.append(f"bold: {fs.bold or '(none - headings use size/colour only)'}")
    except DirectivePdfError as e:
        lines.append("font: NOT FOUND")
        lines.append(str(e))
    return "\n".join(lines)
