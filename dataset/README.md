# Changing Hands dataset

The full text of the Folio Views infobase *Changing Hands (1550 onwards): a
calendar of bondage in Southern Africa 1550–1888*, extracted from
`source/ChangingHands.fdf` by `tools/extract_dataset.py` and
`tools/extract_media.py`. All text is UTF-8.

## Files

| Path | Contents |
|---|---|
| `infobase.json` | Title, record count, records per shard, and the outline levels in order |
| `styles.json` | The infobase's named paragraph and character styles, as CSS |
| `records/NNNNNN.jsonl` | The records, one JSON object per line, 5,000 per file; each file is named by the id of its first record |
| `media/` | Embedded pictures and documents, with `media.json` describing them |

## Records

The infobase is a sequence of 205,042 records in reading order. A record is
usually a paragraph or a few paragraphs. Some records are *outline entries*:
they sit at a named level and make up the contents tree. Every other record is
body text belonging to the outline entry above it.

```json
{"id": 4, "level": "04lv", "depth": 1, "parent": null,
 "heading": "1550 to 1870 — Slave Shipwrecks on the South African Coast",
 "text": "1550 to 1870 — Slave Shipwrecks on the South African Coast ",
 "html": "<p class=\"p-pBold-DGreen-bgLGreenA0_0\">1550 to 1870 — …</p>",
 "anchors": [], "objects": []}
```

| Field | Meaning |
|---|---|
| `id` | Position in the infobase, from 0 |
| `level` | Outline level name (see `infobase.json`), or `null` for body text |
| `depth` | Depth in the contents tree, from 1, or `null` for body text |
| `parent` | `id` of the enclosing outline entry, or `null` at the top |
| `heading` | Contents-tree heading as marked in the infobase, or `null`. Some outline entries have none; the website then uses the start of `text` |
| `text` | Plain text for searching and analysis. It also holds hidden text and the text of pop-up notes, which `html` does not show inline |
| `html` | The record as an HTML fragment (see below) |
| `anchors` | Jump destinations in this record: `{"id", "name"}`. `name` is the destination's name in the infobase, if known |
| `objects` | Ids of embedded objects in this record (keys of `media/media.json`) |

### HTML fragments

Paragraphs are `<p>` elements. Named styles appear as classes: `p-<name>` for
paragraph styles and `c-<name>` for character styles. The `class` field in
`styles.json` gives each style's class name. Direct formatting is written as
inline `style` attributes. Other markup:

| Markup | Meaning |
|---|---|
| `<a id="dN"></a>` | Jump destination `N` (listed in `anchors`) |
| `<a data-jump="N">…</a>` | Link to jump destination `N`. A few destinations are missing from the original infobase |
| `<span data-object="N" data-width="W"></span>` | Embedded object `N` (see `media/media.json`), shown `W` twips wide (1/1440 inch; 0 means natural size) |
| `<span class="popup"><span class="popbody">…</span>…</span>` | A pop-up note: `popbody` holds the note, made of `<span class="pp">` paragraphs, followed by the text it is attached to |
| `<a href="…" target="_blank">` | Link to a web page |
| `<span class="datalink">` | A Folio data link (no target is kept) |
| `<span class="tab"></span>` | A tab |
| `<table>` | A table, with column widths in `<colgroup>` when the infobase gives them |
| `class="sup"`, `class="sub"` | Superscript and subscript |

## Media

`media/media.json` maps each object id to:

| Field | Meaning |
|---|---|
| `name` | The object's original file name in the infobase |
| `kind` | `image`, `pdf` or `file` |
| `show` | File to show inline (a PNG/JPEG/GIF/SVG; for PDFs, a preview of the first page) |
| `open` | File to open on click (the PDF, or the original WMF drawing) |
