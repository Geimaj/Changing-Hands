# Changing Hands conversion

Converts the Folio Views 4 infobase `ChangingHands.nfo` into a structured
dataset (`../dataset/`), and the dataset into a static website (`../dist/`)
that opens from disk in any browser.

## How the data was extracted

The `.nfo` file stores its text compressed in an undocumented format, so it is
not read directly. Instead, the Folio Views 4.6 program from the backup was run
under Wine (Debian amd64 container), the whole infobase was selected and copied,
and the clipboard's native "Folio Document Format" was saved with a small
Windows helper. That dump is `source/ChangingHands.fdf`: every record, level,
style, link, popup and embedded object, uncompressed. `folio_fdf.py` documents
its layout.

`source/rtf_stylesheet.rtf` is the stylesheet from Folio's own RTF export and
supplies the formatting of named styles.

## Scripts

| Script | Reads | Writes |
|---|---|---|
| `extract_dataset.py` | `source/` | `dataset/` records, levels and styles |
| `extract_media.py` | `source/ChangingHands.fdf` | `dataset/media/` |
| `build_site.py` | `dataset/` | the website, using the templates in `web/` |

## Rebuilding the dataset

Needs Python 3 with `pillow` and `olefile`, plus macOS `sips` (PDF previews).
WMF drawings need `wmf2svg` (libwmf); on macOS convert them elsewhere and re-run
`extract_media.py`, which picks up existing `.svg` files.

    python tools/extract_dataset.py source/ChangingHands.fdf source/rtf_stylesheet.rtf dataset
    python tools/extract_media.py source/ChangingHands.fdf dataset/media

## Building the website

Needs only Python 3.

    python tools/build_site.py dataset dist
