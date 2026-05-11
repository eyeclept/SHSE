# Dictionary — Inline OED Answer Cards

## Query syntax

Two patterns trigger the OED answer card:

| Pattern | Example |
|---|---|
| `define <word>` | `define photosynthesis` |
| `<word> definition` | `photosynthesis definition` |

A plain word (`photosynthesis`) does **not** trigger a card.
The word may contain letters, digits, hyphens, apostrophes, and spaces (max 50 chars).
Matching is case-insensitive.

## Dictionary file paths and format

Files reside at:

```
/home/eyeclept/Documents/Docs/Media/Ebooks/Dicts/
  stardict-Oxford_English_Dictionary_2nd_Ed._P1-2.4.2/
    Oxford_English_Dictionary_2nd_Ed._P1.ifo    # metadata
    Oxford_English_Dictionary_2nd_Ed._P1.idx    # word → (offset, size) index
    Oxford_English_Dictionary_2nd_Ed._P1.dict.dz  # gzip-compressed definitions
  stardict-Oxford_English_Dictionary_2nd_Ed._P2-2.4.2/
    Oxford_English_Dictionary_2nd_Ed._P2.{ifo,idx,dict.dz}
```

Format: **StarDict 2.4.2**, `sametypesequence=x` (Pango/XML markup).

- P1: 140 086 entries, P2: 140 496 entries; together they cover the full OED 2nd Ed.
- `.idx`: packed binary — `<word>\x00<uint32BE offset><uint32BE size>` per entry.
- `.dict.dz`: dictzip (gzip-compatible). Python's `gzip.open().seek()` provides random access
  in ~0.3 s per lookup; the `.idx` is loaded once into memory (~5 MB).

## Adding a new StarDict dictionary

1. Place the `.ifo`, `.idx`, `.dict.dz` files under `_DICT_BASE`.
2. Add a `StarDictReader` instance pointing to the new stem in `flask_app/services/stardict.py`.
3. Optionally wrap multiple `StarDictReader`s in a new reader class modelled on `OedReader`.
4. Call `lookup()` from `build_definition_card()` or a new card-builder function in the route.

## Markup stripping

OED definitions use Pango-XML tags: `<k>` (headword), `<b>` (bold), `<c>` (coloured text),
`<blockquote>` (indented), `<abr>` (abbreviation), `<kref>` (cross-reference), `<i>` (italic).

`_strip_markup()` removes all `<tag>` / `</tag>` nodes with a single regex, then decodes
`&apos;`, `&quot;`, `&amp;`, `&lt;`, `&gt;`, and collapses whitespace to single spaces.

## ai_context injection

When the OED card fires, `build_definition_card()` also returns:

```python
ai_context = f"Definition of {word}: {definition[:300]}"
```

This string is passed to `results.html` as the `ai_context` template variable.
The HTMX semantic summary endpoint at `/api/semantic_summary` can be extended to accept
`?ctx=<ai_context>` so the LLM receives the definition as grounding context before
generating its summary.  The `data-ai-context` attribute on the card `<div>` exposes
the same text for JavaScript-driven enhancements.
