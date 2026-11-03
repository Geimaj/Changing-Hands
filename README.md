# Changing Hands

*Changing Hands (1550 onwards): a calendar of bondage in Southern Africa
1550–1888* was published as a Folio Views infobase (`ChangingHands.nfo`,
205,042 records). This repository keeps it readable without Folio Views. It
holds the original material, the scripts that parse it, the structured
dataset they produce, and a script that turns the dataset into an offline
website.

## Contents

| Path | What it is |
|---|---|
| `source/` | The original material: a full dump of the infobase in Folio Document Format, and Folio's RTF stylesheet. Stored with [Git LFS](https://git-lfs.com) |
| `dataset/` | The structured dataset: every record as JSON Lines (text, HTML, outline position, links), plus styles and embedded media. See [`dataset/README.md`](dataset/README.md) |
| `tools/` | Scripts to extract the dataset from `source/` and build the website from `dataset/`. See [`tools/README.md`](tools/README.md) |

## Building the website

Needs only Python 3:

    python tools/build_site.py dataset dist

Then open `dist/index.html` in a browser. Nothing needs installing and no
internet connection is required. To share the site, copy or zip the whole
`dist/` folder. To serve it locally instead:

    python -m http.server 8765 --directory dist

## Getting the source files

Cloning needs Git LFS for `source/`. Install it, then run `git lfs install`
once before cloning. The dataset and website don't need `source/`. To skip
downloading it:

    GIT_LFS_SKIP_SMUDGE=1 git clone <repository url>

## Copyright

The infobase carries its own copyright notice, shown on the last page of the
website. It restricts use to personal use.
