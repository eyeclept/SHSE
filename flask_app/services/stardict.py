"""
Author: Richard Baldwin
Date:   2026
Email: eyeclept@pm.me

Description:
    StarDict dictionary reader for offline OED definition lookups.
    Provides query detection, OED lookup via gzip.seek(), Pango markup
    parsing into structured sections/definitions, and answer_card construction.
"""
# Imports
import gzip
import logging
import os
import re
import struct
from pathlib import Path
from typing import Optional

# Globals
logger = logging.getLogger(__name__)

_DICT_BASE = Path(os.environ.get("STARDICT_DICT_PATH", "/app/dicts"))
_OED_P1_STEM = (
    _DICT_BASE
    / "stardict-Oxford_English_Dictionary_2nd_Ed._P1-2.4.2"
    / "Oxford_English_Dictionary_2nd_Ed._P1"
)
_OED_P2_STEM = (
    _DICT_BASE
    / "stardict-Oxford_English_Dictionary_2nd_Ed._P2-2.4.2"
    / "Oxford_English_Dictionary_2nd_Ed._P2"
)

# Query detection
_RE_DEFINE = re.compile(r"^define\s+([a-z][\w\s'\-]{0,49})\s*$", re.IGNORECASE)
_RE_DEFN   = re.compile(r"^([a-z][\w\s'\-]{0,49})\s+definition\s*$", re.IGNORECASE)

# OED markup patterns
_RE_HEADWORD    = re.compile(r"<k>([^<]+)</k>")
_RE_SECTION_HDR = re.compile(
    r'<b><c c="darkmagenta">▪\s*<c>[IVX]+\.</c></c></b>\s*\t?\s*'
    r'<b>([^<,]+),\s*<abr>([^<]+)</abr>'
)
_RE_SINGLE_HDR  = re.compile(r'^<b>([^<,]+),\s*<abr>([^<]+)</abr>')
_RE_PRON        = re.compile(r'<c c="darkslategray">([^<]+)</c>')
_RE_ETYM        = re.compile(r'<c c="gray">(\[.*\])</c>', re.DOTALL)
_RE_INDIGO      = re.compile(r'<b><c c="indigo">([^<]*)</c></b>')
_RE_EX          = re.compile(r'<ex>.*?</ex>', re.DOTALL)
_RE_TAG         = re.compile(r'<[^>]+>')
_RE_WS          = re.compile(r'\s+')
_RE_CITE_DATE   = re.compile(
    r'\s+(?:[ac]\s*)?\d{4}\s+[A-Z][a-z]'  # year + capitalised author
)

_ENTITIES = {
    "&apos;": "'", "&quot;": '"', "&amp;": "&",
    "&lt;": "<",  "&gt;": ">",  "&#39;": "'", "&#34;": '"',
}

_POS_NAMES = {
    "n.": "noun",          "v.": "verb",         "a.": "adjective",
    "adj.": "adjective",   "adv.": "adverb",     "prep.": "preposition",
    "conj.": "conjunction","pron.": "pronoun",   "int.": "interjection",
    "ppl.": "participial adjective",
    "n. pl.": "plural noun",
    "a. and n.": "adjective & noun",
    "v. and n.": "verb & noun",
}

# Grammatical form-table lines — not real definitions
_RE_FORMS_LINE = re.compile(
    r'^(?:inf\.|pres\.|imp\.|subj\.|pret\.|pa\.\s|pa,\s|pt\.|pp\.\s|pple\.|'
    r'past\s|Forms?:|α\.|β\.|γ\.|'
    r'weak\s|strong\s|'            # "weak conj. ...", "strong conj. ..."
    r'\(α\)|\(β\)|\(γ\)|'          # form-group markers
    r'Also\s|'                     # variant spellings: "Also berserkar, -ir", "Also 6 algeber"
    r'\d+\s+[a-z]\w{0,5}[,.])',    # pure dated-forms like "3 ærnde, 3–4 arnde"
    re.IGNORECASE,
)

_MAX_SECTIONS = 3
_MAX_DEFS     = 5


# Functions
def detect_definition_query(q: str) -> Optional[str]:
    """
    Input: q — raw search query string
    Output: extracted word if "define <word>" or "<word> definition", else None
    """
    q = q.strip()
    m = _RE_DEFINE.match(q)
    if m:
        return m.group(1).strip()
    m = _RE_DEFN.match(q)
    if m:
        return m.group(1).strip()
    return None


def _clean(text: str) -> str:
    """Strip tags, resolve entities, collapse whitespace."""
    text = _RE_EX.sub("", text)
    text = _RE_TAG.sub("", text)
    for ent, repl in _ENTITIES.items():
        text = text.replace(ent, repl)
    return _RE_WS.sub(" ", text).strip()


def _strip_markup(raw: str) -> str:
    """Plain-text fallback used for ai_context and legacy callers."""
    return _clean(raw)


def _def_number(indigo_parts: list) -> str:
    """
    Input: list of strings from <c c="indigo"> tags on one line
    Output: compact number string like "1", "1a", "2b"
    Details:
        Skips pure roman-numeral parts (e.g. "I."); combines digit + sub-letter.
    """
    number = ""
    sub    = ""
    for part in indigo_parts:
        part = part.strip().rstrip(".")
        if re.fullmatch(r"[IVX]+", part):
            continue
        m = re.match(r"[IVX]*\.?\s*(\d+)\s*([a-z]?)", part)
        if m:
            number = m.group(1)
            sub    = m.group(2)
            continue
        m = re.match(r"([a-z])$", part)
        if m and number:
            sub = m.group(1)
    return number + sub


def _parse_def_line(line: str) -> Optional[dict]:
    """
    Input: one raw markup line from an OED entry
    Output: {"number": str, "text": str, "obsolete": bool} or None
    Details:
        Processes lines that contain <c c="indigo"> definition numbers.
        Strips the number, obsolete marker, blockquote tags, and all XML.
        Truncates at the first historical citation date pattern.
    """
    indigo_parts = _RE_INDIGO.findall(line)
    if not indigo_parts:
        return None

    number = _def_number(indigo_parts)
    if not number:
        return None

    obsolete = bool(re.search(r'<abr>†</abr>', line))

    # Strip markers, then clean
    text = _RE_INDIGO.sub("", line)
    text = re.sub(r'<abr>†</abr>\s*', "", text)
    text = _clean(text)

    # Remove trailing Obs. / arch. labels
    text = re.sub(r'\s*\b(?:Obs|arch)\.\s*$', "", text).strip()

    # Truncate at first historical citation (year + capitalised author)
    m = _RE_CITE_DATE.search(text)
    if m:
        text = text[:m.start()].rstrip(" .,;")

    if len(text) < 4:
        return None

    # Skip grammatical form-table entries (inflected forms, not definitions)
    if _RE_FORMS_LINE.match(text):
        return None

    return {"number": number, "text": text, "obsolete": obsolete}


def _extract_pos(header_line: str) -> tuple:
    """
    Input: a section header line (may or may not contain ▪)
    Output: (pos_abbr: str, pos_full: str)
    Details:
        Returns the primary POS only. Secondary POS in parentheses (e.g. "a. (n.)")
        is ignored so "human, a. (n.)" yields "adjective" not "adjective & noun".
    """
    m = re.search(r'<abr>([^<]+)</abr>', header_line)
    if not m:
        return "", ""
    abbr = m.group(1).strip()
    full = _POS_NAMES.get(abbr, abbr.rstrip(".").capitalize())
    return abbr, full


def parse_oed_entry(raw: str) -> dict:
    """
    Input: raw — full OED StarDict entry (Pango XML markup)
    Output: structured dict:
        {
          "headword": str,
          "sections": [
            {
              "pos_abbr": str,
              "pos": str,
              "pronunciation": str,
              "etymology": str,
              "definitions": [{"number": str, "text": str, "obsolete": bool}]
            }
          ]
        }
    Details:
        Splits on ▪ section markers. For single-section entries (no ▪) the
        whole entry is treated as one section. Limits to _MAX_SECTIONS sections
        and _MAX_DEFS non-obsolete definitions per section.
    """
    m = _RE_HEADWORD.search(raw)
    headword = _clean(m.group(1)) if m else ""

    lines = raw.split("\n")
    has_sections = "▪" in raw

    sections    = []
    cur_section = None

    def _flush():
        if cur_section and cur_section.get("definitions"):
            sections.append(cur_section)

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # ── Section header ─────────────────────────────────────────────
        if has_sections and "▪" in line and 'darkmagenta' in line:
            if len(sections) >= _MAX_SECTIONS:
                break
            _flush()
            pos_abbr, pos_full = _extract_pos(line)
            cur_section = {
                "pos_abbr": pos_abbr,
                "pos": pos_full,
                "pronunciation": "",
                "etymology": "",
                "definitions": [],
            }
            continue

        # Bootstrap single-section entries on the first <b> header line.
        # Entries like "algebra" have no <abr> tag; entries like "boycott"
        # or "Schadenfreude" have <abr> but no coloured section marker.
        # Exclude <b><c c=...> lines — those are coloured inline spans, not headers.
        if not has_sections and cur_section is None:
            if line.startswith("<b>") and not line.startswith("<b><c c="):
                pos_abbr, pos_full = _extract_pos(line)
                cur_section = {
                    "pos_abbr": pos_abbr,
                    "pos": pos_full,
                    "pronunciation": "",
                    "etymology": "",
                    "definitions": [],
                }
            continue

        if cur_section is None:
            continue

        # ── Pronunciation ───────────────────────────────────────────────
        if not cur_section["pronunciation"] and 'darkslategray' in line:
            m2 = _RE_PRON.search(line)
            if m2:
                cur_section["pronunciation"] = m2.group(1).strip()
            continue

        # ── Etymology ──────────────────────────────────────────────────
        if not cur_section["etymology"] and 'c c="gray"' in line:
            m2 = _RE_ETYM.search(line)
            if m2:
                cur_section["etymology"] = _clean(m2.group(1))
            continue

        # ── Skip historical citations ──────────────────────────────────
        if "<ex>" in line:
            continue

        # ── Numbered definition line ────────────────────────────────────
        if 'c c="indigo"' in line:
            defn = _parse_def_line(line)
            if defn:
                non_obs = sum(1 for d in cur_section["definitions"] if not d["obsolete"])
                if non_obs < _MAX_DEFS:
                    cur_section["definitions"].append(defn)

        # ── Unnumbered definition (boycott, schadenfreude, etc.) ────────
        # Short entries omit <c c="indigo"> numbering; their single definition
        # sits in a plain blockquote with no other colour markers.
        elif (
            "<blockquote>" in line
            and not cur_section["definitions"]        # no numbered defs yet
            and 'c c="darkslategray"' not in line     # not pronunciation
            and 'c c="gray"' not in line              # not etymology
            and 'c c="darkmagenta"' not in line       # not section header
            and "<ex>" not in line                    # not citation
        ):
            text = _clean(line)
            text = re.sub(r'\s*\b(?:Obs|arch)\.\s*$', "", text).strip()
            m2 = _RE_CITE_DATE.search(text)
            if m2:
                text = text[: m2.start()].rstrip(" .,;")
            if len(text) >= 10 and not _RE_FORMS_LINE.match(text):
                cur_section["definitions"].append({
                    "number": "1",
                    "text": text,
                    "obsolete": False,
                })

    _flush()

    # Ensure at least one section even if no ▪ was found
    if not sections and cur_section:
        if cur_section.get("definitions"):
            sections.append(cur_section)

    return {"headword": headword, "sections": sections}


class StarDictReader:
    """
    Input: stem — Path stem (no extension) for a StarDict dictionary
    Output: lookup(word) -> str | None,  lookup_raw(word) -> str | None
    Details:
        Loads .idx once on first use. Each lookup uses gzip.open().seek().
        Results are cached per instance to avoid redundant decompression.
    """

    def __init__(self, stem: Path) -> None:
        self._stem = stem
        self._idx:      Optional[dict] = None
        self._cache:    dict = {}
        self._raw_cache: dict = {}

    def _load_idx(self) -> None:
        idx_path = Path(str(self._stem) + ".idx")
        with open(idx_path, "rb") as f:
            raw = f.read()
        idx: dict = {}
        pos = 0
        while pos < len(raw):
            null = raw.index(0, pos)
            word = raw[pos:null].decode("utf-8", errors="replace")
            offset, size = struct.unpack(">II", raw[null + 1: null + 9])
            idx[word.lower()] = (offset, size)
            pos = null + 9
        self._idx = idx

    def _read(self, word: str) -> Optional[str]:
        if self._idx is None:
            try:
                self._load_idx()
            except Exception:
                logger.exception("stardict: failed to load idx %s", self._stem.name)
                return None
        entry = self._idx.get(word.lower())
        if entry is None:
            return None
        offset, size = entry
        dz_path = Path(str(self._stem) + ".dict.dz")
        try:
            with gzip.open(str(dz_path), "rb") as gz:
                gz.seek(offset)
                return gz.read(size).decode("utf-8", errors="replace")
        except Exception:
            logger.exception("stardict: read failed %s/%s", self._stem.name, word)
            return None

    def lookup_raw(self, word: str) -> Optional[str]:
        """
        Input: word
        Output: raw Pango XML markup string or None
        """
        key = word.lower()
        if key in self._raw_cache:
            return self._raw_cache[key]
        raw = self._read(word)
        self._raw_cache[key] = raw
        return raw

    def lookup(self, word: str) -> Optional[str]:
        """
        Input: word
        Output: plain-text definition string or None
        """
        key = word.lower()
        if key in self._cache:
            return self._cache[key]
        raw = self.lookup_raw(word)
        result = _strip_markup(raw) if raw else None
        self._cache[key] = result
        return result


class OedReader:
    """
    Input: None (uses module-level OED P1 + P2 path constants)
    Output: lookup/lookup_raw — tries P1 first, then P2
    """

    def __init__(self) -> None:
        self._p1 = StarDictReader(_OED_P1_STEM)
        self._p2 = StarDictReader(_OED_P2_STEM)

    def lookup_raw(self, word: str) -> Optional[str]:
        """
        Input: word
        Output: raw Pango XML or None
        """
        return self._p1.lookup_raw(word) or self._p2.lookup_raw(word)

    def lookup(self, word: str) -> Optional[str]:
        """
        Input: word
        Output: plain-text definition or None
        """
        return self._p1.lookup(word) or self._p2.lookup(word)


_oed_reader: Optional[OedReader] = None


def get_oed_reader() -> OedReader:
    """
    Input: None
    Output: module-level OedReader singleton (lazy-initialised)
    """
    global _oed_reader
    if _oed_reader is None:
        _oed_reader = OedReader()
    return _oed_reader


def build_definition_card(q: str) -> tuple:
    """
    Input: q — raw search query
    Output: (answer_card dict, ai_context str) or (None, None)
    Details:
        Detects definition queries, looks up OED, parses markup into
        structured sections, and returns a card dict for the template.
    """
    word = detect_definition_query(q)
    if not word:
        return None, None

    try:
        oed = get_oed_reader()
        raw = oed.lookup_raw(word)
    except Exception:
        logger.warning("OED lookup_raw failed for %s", word, exc_info=True)
        raw = None

    if not raw:
        return None, None

    parsed = parse_oed_entry(raw)
    if not parsed["sections"]:
        return None, None

    # Plain-text summary for ai_context (first section, first 3 defs)
    first = parsed["sections"][0]
    defs_text = " ".join(
        d["text"] for d in first["definitions"] if not d["obsolete"]
    )[:300]
    ai_context = f"Definition of {word}: {defs_text}" if defs_text else None

    answer_card = {
        "type":   "definition",
        "word":   word,
        "parsed": parsed,
        "source": "Oxford English Dictionary",
    }
    return answer_card, ai_context


if __name__ == "__main__":
    pass
