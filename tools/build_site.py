"""Build a static, offline website from the structured dataset.

Usage: python build_site.py <dataset dir> <output dir>

The output opens straight from disk (file://) in any modern browser:
  index.html            contents tree + search, with pages shown alongside
  pages/pNNNNN.html     the infobase text, split into pages by the outline
  media/                pictures and PDFs from the infobase
  data/                 contents tree, search index and record lists as JS files
"""
import collections
import glob
import html
import json
import os
import re
import shutil
import sys
import unicodedata

PAGE_LIMIT = 350_000      # target HTML bytes per page
META_SHARD = 2000         # records per search-metadata file


# --------------------------------------------------------------------------
# dataset
# --------------------------------------------------------------------------
def esc(s):
    return html.escape(s, quote=False)


def load_records(dataset):
    records = []
    for path in sorted(glob.glob(os.path.join(dataset, 'records', '*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            records.extend(json.loads(line) for line in f)
    assert [r['id'] for r in records] == list(range(len(records))), 'records out of order'
    return records


def object_html(m, width):
    """Markup for an embedded object (an entry of media.json), width in twips."""
    style = ' style="width:%dpx"' % round(width / 15) if width else ''
    img = '<img src="../media/%s" alt="%s"%s loading="lazy">' % (
        m.get('show', ''), html.escape(m['name']), style) if m.get('show') else esc(m['name'])
    if m.get('open') or m.get('kind') == 'image':
        target = m.get('open') or m['show']
        label = ' <span class="objlabel">Open PDF</span>' if m.get('kind') == 'pdf' else ''
        img = '<a class="obj" href="../media/%s" target="_blank">%s%s</a>' % (target, img, label)
    return img


# --------------------------------------------------------------------------
# outline and pages
# --------------------------------------------------------------------------
def build_tree(records, level_order):
    depth = {lv: i + 1 for i, lv in enumerate(level_order)}
    root = {'rec': None, 'depth': 0, 'own': [], 'children': []}
    stack = [root]
    nodes = []
    for i, r in enumerate(records):
        k = depth.get(r['level'])
        if k is None:
            stack[-1]['own'].append(i)
            continue
        while stack[-1]['depth'] >= k:
            stack.pop()
        node = {'rec': i, 'depth': k, 'own': [i], 'children': [], 'parent': stack[-1]}
        stack[-1]['children'].append(node)
        stack.append(node)
        nodes.append(node)
    return root, nodes


def paginate(root, size):
    memo = {}

    def total(node):
        key = id(node)
        if key not in memo:
            memo[key] = sum(size[i] for i in node['own']) + sum(total(c) for c in node['children'])
        return memo[key]

    def records_of(node):
        out = list(node['own'])
        for c in node['children']:
            out.extend(records_of(c))
        return out

    pages = []
    group, gsize = [], 0

    def flush():
        nonlocal group, gsize
        if group:
            pages.append(group)
        group, gsize = [], 0

    def add(recs, s):
        nonlocal gsize
        if gsize and gsize + s > PAGE_LIMIT:
            flush()
        group.extend(recs)
        gsize += s

    def walk(node):
        if total(node) <= PAGE_LIMIT:
            add(records_of(node), total(node))
            return
        for i in node['own']:
            add([i], size[i])
        for c in node['children']:
            if total(c) <= PAGE_LIMIT:
                add(records_of(c), total(c))
            else:
                flush()
                walk(c)
        flush()

    walk(root)
    flush()
    return pages


# --------------------------------------------------------------------------
# search index
# --------------------------------------------------------------------------
WORD = re.compile(r'[0-9a-z]+')


def fold(s):
    s = unicodedata.normalize('NFKD', s.lower())
    return ''.join(ch for ch in s if not unicodedata.combining(ch))


def b36(n):
    digits = '0123456789abcdefghijklmnopqrstuvwxyz'
    s = ''
    while True:
        n, r = divmod(n, 36)
        s = digits[r] + s
        if not n:
            return s


def shard_key(word):
    return (word[:2] if len(word) > 1 else word + '_')


def js_string(s):
    return json.dumps(s, ensure_ascii=False)


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------
def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def main(dataset, outdir):
    info = json.load(open(os.path.join(dataset, 'infobase.json'), encoding='utf-8'))
    styles = json.load(open(os.path.join(dataset, 'styles.json'), encoding='utf-8'))
    media_dir = os.path.join(dataset, 'media')
    media = json.load(open(os.path.join(media_dir, 'media.json'), encoding='utf-8'))
    records = load_records(dataset)
    print(len(records), 'records')

    # embedded objects are fixed markup; jump links depend on pagination
    obj = re.compile(r'<span data-object="(\d+)" data-width="(\d+)"></span>')
    for r in records:
        r['html'] = obj.sub(lambda m: object_html(media[m.group(1)], int(m.group(2))), r['html'])
    dest_record = {a['id']: r['id'] for r in records for a in r['anchors']}

    level_order = [lv['name'] for lv in info['levels']]
    root, nodes = build_tree(records, level_order)
    print(len(nodes), 'outline entries')
    for node in nodes:
        r = records[node['rec']]
        if not r['heading']:
            r['heading'] = r['text'].strip()[:120] or '(untitled)'

    size = [len(r['html']) + 40 for r in records]
    pages = paginate(root, size)
    page_of = {}
    for p, recs in enumerate(pages):
        for i in recs:
            page_of[i] = p
    print(len(pages), 'pages')

    # breadcrumb trail for every record (nearest outline entries)
    trail = []
    rec_trail = []
    dk = {lv: i + 1 for i, lv in enumerate(level_order)}
    for i, r in enumerate(records):
        k = dk.get(r['level'])
        if k is not None:
            trail = trail[:k - 1] + [(r['heading'].strip(), i)]
        rec_trail.append(trail)

    if os.path.exists(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir)
    shutil.copytree(media_dir, os.path.join(outdir, 'media'),
                    ignore=shutil.ignore_patterns('media.json'))
    here = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(outdir, 'data'), exist_ok=True)
    for name in ('style.css', 'page.js', 'viewer.js', 'viewer.css'):
        shutil.copy(os.path.join(here, 'web', name), os.path.join(outdir, 'data', name))

    # named styles: character styles first, then paragraph styles, by name
    css = []
    for st in sorted(styles, key=lambda st: (st['kind'] != 'character', st['name'])):
        if st['css']:
            css.append('.%s{%s}' % (st['class'], ';'.join('%s:%s' % kv for kv in st['css'].items())))
    write(os.path.join(outdir, 'data', 'styles.css'), '\n'.join(css) + '\n')

    def href(m, from_page):
        ident = int(m.group(1))
        i = dest_record.get(ident)
        if i is None:
            return '#" class="broken" title="Link target is missing in the original infobase'
        p = page_of[i]
        return ('#d%d' % ident) if p == from_page else ('p%05d.html#d%d' % (p + 1, ident))

    title = info['title']
    for p, recs in enumerate(pages):
        first = recs[0]
        crumb = ' &rsaquo; '.join(
            '<a href="p%05d.html#r%d">%s</a>' % (page_of[i] + 1, i, esc(h[:80]))
            for h, i in rec_trail[first][:-1] if i in page_of)
        here_title = rec_trail[first][-1][0] if rec_trail[first] else title
        body = []
        for i in recs:
            r = records[i]
            k = dk.get(r['level'])
            cls = 'rec lv%d' % k if k else 'rec'
            h = re.sub(r'<a data-jump="(\d+)">', lambda m: '<a href="%s">' % href(m, p), r['html'])
            body.append('<div class="%s" id="r%d">%s</div>' % (cls, i, h))
        nav = '<nav class="pager">%s<span class="pnum">Page %d of %d</span>%s</nav>' % (
            '<a href="p%05d.html" rel="prev">&larr; Previous</a>' % p if p else '<span></span>',
            p + 1, len(pages),
            '<a href="p%05d.html" rel="next">Next &rarr;</a>' % (p + 2) if p + 1 < len(pages) else '<span></span>')
        doc = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
               '<meta name="viewport" content="width=device-width,initial-scale=1">'
               '<title>%s &ndash; %s</title>'
               '<link rel="stylesheet" href="../data/style.css"><link rel="stylesheet" href="../data/styles.css">'
               '</head><body data-page="%d"><header class="top"><a class="home" href="../index.html" target="_top">'
               'Changing Hands</a><div class="crumbs">%s</div></header>%s<main>%s</main>%s'
               '<script src="../data/page.js"></script></body></html>') % (
            esc(here_title[:80]), title, p + 1, crumb, nav, '\n'.join(body), nav)
        write(os.path.join(outdir, 'pages', 'p%05d.html' % (p + 1)), doc)

    # contents tree: [heading, record, page, children]
    def toc(node):
        return [node_title(node), node['rec'], page_of[node['rec']] + 1, [toc(c) for c in node['children']]]

    def node_title(node):
        return records[node['rec']]['heading'].strip() or '(untitled)'
    tree = [toc(c) for c in root['children']]
    write(os.path.join(outdir, 'data', 'toc.js'),
          'window.TOC=' + json.dumps(tree, ensure_ascii=False, separators=(',', ':')) + ';\n'
          'window.PAGECOUNT=%d;window.RECORDCOUNT=%d;\n' % (len(pages), len(records)))

    # search: word -> records, sharded by first two letters
    print('indexing...')
    postings = collections.defaultdict(list)
    for i, r in enumerate(records):
        words = set(WORD.findall(fold(r['text'])))
        for w in words:
            postings[w].append(i)
    shards = collections.defaultdict(dict)
    for w, ids in sorted(postings.items()):
        prev, parts = 0, []
        for x in ids:
            parts.append(b36(x - prev))
            prev = x
        shards[shard_key(w)][w] = ','.join(parts)
    for key, words in shards.items():
        write(os.path.join(outdir, 'data', 'search', key + '.js'),
              'SHARD(%s,%s);\n' % (js_string(key), json.dumps(words, ensure_ascii=False, separators=(',', ':'))))
    write(os.path.join(outdir, 'data', 'search', 'keys.js'),
          'window.SHARDS=%s;\n' % json.dumps(sorted(shards), separators=(',', ':')))
    for start in range(0, len(records), META_SHARD):
        meta = []
        for i in range(start, min(start + META_SHARD, len(records))):
            path = ' › '.join(h[:60] for h, _ in rec_trail[i])
            snippet = re.sub(r'\s+', ' ', records[i]['text']).strip()[:200]
            meta.append([page_of[i] + 1, path, snippet])
        write(os.path.join(outdir, 'data', 'meta', '%d.js' % (start // META_SHARD)),
              'META(%d,%s);\n' % (start // META_SHARD, json.dumps(meta, ensure_ascii=False, separators=(',', ':'))))
    print(len(postings), 'distinct words')

    shutil.copy(os.path.join(here, 'web', 'index.html'), os.path.join(outdir, 'index.html'))
    shutil.copy(os.path.join(here, 'web', 'README.txt'), os.path.join(outdir, 'README.txt'))
    print('done:', outdir)


if __name__ == '__main__':
    main(*sys.argv[1:3])
