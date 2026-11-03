"""Extract a structured dataset from a Folio Document Format dump.

Usage: python extract_dataset.py <ChangingHands.fdf> <rtf stylesheet> <dataset dir>

Writes (see dataset/README.md for the full schema):
  infobase.json         title, record count and the outline levels in order
  styles.json           named paragraph/character styles and their formatting
  records/NNNNNN.jsonl  one JSON object per record, RECORD_SHARD records per file,
                        named by the id of the first record

Embedded pictures and documents are extracted separately into <dataset>/media
by extract_media.py.
"""
import html
import json
import os
import re
import shutil
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
import folio_fdf as F  # noqa: E402

RECORD_SHARD = 5000       # records per JSONL file
ALIGN = {0: 'left', 1: 'center', 2: 'right', 3: 'justify'}


# --------------------------------------------------------------------------
# styles: the RTF export's stylesheet carries each named style's formatting
# --------------------------------------------------------------------------
def css_class(prefix, name):
    return prefix + re.sub(r'[^A-Za-z0-9_-]', '_', name)


def rtf_stylesheet(path):
    """Return [(kind, name, {css property: value})], kind 's' (paragraph) or 'cs'."""
    rtf = open(path, 'rb').read().decode('cp1252')
    colours = []
    ct = re.search(r'\{\\colortbl(.*?)\}', rtf, re.S).group(1)
    for entry in ct.split(';')[:-1]:
        r = re.search(r'\\red(\d+)', entry)
        g = re.search(r'\\green(\d+)', entry)
        b = re.search(r'\\blue(\d+)', entry)
        colours.append('#%02x%02x%02x' % tuple(int(x.group(1)) if x else 0 for x in (r, g, b)))
    css = {}
    for m in re.finditer(r'\{(?:\\\*)?\\(s|cs)\d+([^{}]*)\}', rtf):
        kind, body = m.groups()
        body = body.replace('\r', '').replace('\n', '')
        name = re.sub(r'\\[a-z]+-?\d* ?', '', body).strip().rstrip(';').strip()
        rules = {}
        shading = None
        for word, num in re.findall(r'\\([a-z]+)(-?\d+)?', body):
            n = int(num) if num else None
            if word == 'b':
                rules['font-weight'] = 'normal' if n == 0 else 'bold'
            elif word == 'i':
                rules['font-style'] = 'normal' if n == 0 else 'italic'
            elif word == 'ul':
                if n != 0:
                    rules['text-decoration'] = 'underline'
            elif word == 'strike' and n != 0:
                rules['text-decoration'] = 'line-through'
            elif word == 'v' and n != 0:
                rules['display'] = 'none'
            elif word == 'fs' and n:
                rules['font-size'] = '%gpt' % (n / 2)
            elif word == 'cf' and n is not None and n < len(colours) and n:
                rules['color'] = colours[n]
            elif word in ('cb', 'cfpat') and n is not None and n < len(colours):
                shading = colours[n]
            elif word in ('up', 'super'):
                rules['vertical-align'] = 'super'
            elif word in ('dn', 'sub'):
                rules['vertical-align'] = 'sub'
            elif kind == 's' and word in ('ql', 'qc', 'qr', 'qj'):
                rules['text-align'] = {'ql': 'left', 'qc': 'center', 'qr': 'right', 'qj': 'justify'}[word]
            elif kind == 's' and word == 'li' and n:
                rules['margin-left'] = '%gpt' % (n / 20)
            elif kind == 's' and word == 'ri' and n:
                rules['margin-right'] = '%gpt' % (n / 20)
            elif kind == 's' and word == 'fi' and n:
                rules['text-indent'] = '%gpt' % (n / 20)
            elif kind == 's' and word == 'sb' and n:
                rules['margin-top'] = '%gpt' % (n / 20)
        if shading and shading != '#ffffff':
            rules['background-color'] = shading
        css[(kind, name)] = rules
    return [(kind, name, rules) for (kind, name), rules in css.items()]


# --------------------------------------------------------------------------
# rendering: records as HTML fragments
#
# Two placeholders stand for things whose final form depends on the site:
#   <a data-jump="N">...</a>                         jump link to destination N
#   <span data-object="N" data-width="W"></span>     embedded object N, W twips wide
# --------------------------------------------------------------------------
def esc(s):
    return html.escape(s, quote=False)


def twips(v):
    return '%gpt' % (v / 20)


class Paragraphs:
    """Collects inline HTML; a paragraph's format arrives after its content."""

    def __init__(self):
        self.inline = []
        self.pending = None   # (inline html, style attr) waiting for an optional 0x16

    def flush(self, out, style_class=None):
        if self.pending is None:
            return
        body, attr = self.pending
        self.pending = None
        cls = ' class="%s"' % style_class if style_class else ''
        out.append('<p%s%s>%s</p>' % (cls, attr, body or '&nbsp;'))


def popup_text(nested):
    """Popup documents use a compact encoding: a short header, cp1252 text,
    0x05 between paragraphs."""
    body = nested[5:] if nested[4:5] == b'\x09' else nested[4:]
    body = re.sub(rb'[\x00-\x1f]+$', b'', body.rstrip(b'\x00\x01\x02\x09\x10'))
    text = body.decode('cp1252', 'replace')
    text = re.sub(r'[\x00-\x04\x06-\x08\x0b-\x1f]', '', text)
    paras = [p.strip() for p in re.split(r'\x05+', text)]
    return ''.join('<span class="pp">%s</span>' % esc(p) for p in paras if p)


def render(ib, style_names):
    """Walk the token body; return records as dicts."""
    d = ib.d
    dest_names = ib.names[0x1e]
    records = []
    out = []                       # html of the current container
    stack = []                     # enclosing containers while inside tables
    para = Paragraphs()

    def new_record():
        return {'level': 0, 'heading': None, 'text': [], 'anchors': [], 'objects': []}
    rec = new_record()
    char_open = False
    char_style = ''
    link_open = None
    heading_on = False
    hidden = False
    table = None
    prev = None

    def close_char():
        nonlocal char_open
        if char_open:
            para.inline.append('</span>')
            char_open = False

    def close_link():
        nonlocal link_open
        close_char()
        if link_open:
            para.inline.append(link_open)
            link_open = None

    def end_paragraph(attr):
        nonlocal heading_on
        close_link()
        para.flush(out)
        para.pending = (''.join(para.inline), attr)
        para.inline = []
        heading_on = False

    def finish_pending(style_class=None):
        para.flush(out, style_class)

    for o, c, n in F.tokens(d, ib.body_start, ib.body_end - 2):
        if prev == 0x17 and c != 0x16:
            finish_pending()
        prev = c
        if c == 0x06:
            s = d[o + 4:o + n].decode('cp1252', 'replace')
            if heading_on:              # contents headings may use hidden text
                rec['heading'] = (rec['heading'] or '') + s
            if not hidden:
                rec['text'].append(s)
                if not char_open and char_style:
                    para.inline.append('<span%s>' % char_style)
                    char_open = True
                para.inline.append(esc(s))
            else:
                rec['text'].append(' ' + s + ' ')   # searchable, not shown
        elif c == 0x15:
            close_link()
            heading_on = False
            f, _ = F.flag_fields(d, o, 0x15)
            classes, styles = [], []
            hidden = bool(f.get(4, b'\0')[0])
            if f.get(0, b'\0')[0]:
                styles.append('font-weight:bold')
            elif 0 in f:
                styles.append('font-weight:normal')
            if f.get(1, b'\0')[0]:
                styles.append('font-style:italic')
            elif 1 in f:
                styles.append('font-style:normal')
            if f.get(2, b'\0')[0]:
                styles.append('text-decoration:underline')
            if f.get(3, b'\0')[0]:
                styles.append('text-decoration:line-through')
            if 9 in f:
                styles.append('font-size:%gpt' % (struct.unpack('<H', f[9])[0] / 20))
            if 10 in f and f[10][3] == 0:
                styles.append('color:#%02x%02x%02x' % tuple(f[10][:3]))
            if 11 in f and f[11][3] == 0:
                styles.append('background-color:#%02x%02x%02x' % tuple(f[11][:3]))
            if 12 in f:
                off = struct.unpack('<h', f[12])[0]
                if off:
                    classes.append('sup' if off < 0 else 'sub')
            char_style = ''
            if classes:
                char_style += ' class="%s"' % ' '.join(classes)
            if styles:
                char_style += ' style="%s"' % ';'.join(styles)
        elif c in (0x14, 0x12):
            name = style_names[c].get(struct.unpack_from('<H', d, o + 3)[0])
            if name:
                close_char()
                if name in ('cHidden',):
                    hidden = True
                cls = css_class('c-', name)
                if 'class="' in char_style:
                    char_style = char_style.replace('class="', 'class="%s ' % cls)
                else:
                    char_style = ' class="%s"' % cls + char_style
        elif c == 0x17:
            f, _ = F.flag_fields(d, o, 0x17)
            st = []
            if 0 in f and f[0][0] in ALIGN and f[0][0]:
                st.append('text-align:' + ALIGN[f[0][0]])
            if 6 in f:
                st.append('margin-left:' + twips(struct.unpack('<h', f[6])[0]))
            if 7 in f:
                st.append('margin-right:' + twips(struct.unpack('<h', f[7])[0]))
            if 8 in f:
                st.append('text-indent:' + twips(struct.unpack('<h', f[8])[0]))
            end_paragraph(' style="%s"' % ';'.join(st) if st else '')
            rec['text'].append(' ')
        elif c == 0x16:
            name = style_names[0x16].get(struct.unpack_from('<H', d, o + 3)[0])
            finish_pending(css_class('p-', name) if name else None)
        elif c == 0x10:
            heading_on = True           # this run belongs to the contents heading
        elif c == 0x1e:
            ident = struct.unpack_from('<I', d, o + 2)[0]
            rec['anchors'].append({'id': ident, 'name': dest_names.get(ident)})
            para.inline.append('<a id="d%d"></a>' % ident)
        elif c == 0x1c:
            close_link()
            kind, payload, nested, _ = F.link_parts(d, o)
            if kind == 'Jump' and payload[:1] == b'\x02':
                para.inline.append('<a data-jump="%d">' % F.decode_target(payload[1:]))
                link_open = '</a>'
            elif kind == 'Web':
                url = payload.decode('cp1252', 'replace').strip('\0')
                para.inline.append('<a href="%s" target="_blank" rel="noopener">' % html.escape(url))
                link_open = '</a>'
            elif kind == 'Popup':
                body = popup_text(nested)
                para.inline.append('<span class="popup" tabindex="0"><span class="popbody">%s</span>' % body)
                rec['text'].append(' %s ' % html.unescape(re.sub(r'<[^>]+>', ' ', body)))
                link_open = '</span>'
            elif kind == 'Data':
                para.inline.append('<span class="datalink">')
                link_open = '</span>'
        elif c == 0x08:
            para.inline.append('<br>')
            rec['text'].append(' ')
        elif c == 0x20:
            ident = struct.unpack_from('<I', d, o + 2)[0]
            w, h = struct.unpack_from('<HH', d, o + 18)
            if ident in ib.objects:
                rec['objects'].append(ident)
                close_char()
                para.inline.append('<span data-object="%d" data-width="%d"></span>' % (ident, w))
        elif c == 0x09:
            para.inline.append('<span class="tab"></span>')
            rec['text'].append(' ')
        elif 0x80 <= c <= 0xff:
            para.inline.append(esc(bytes([c]).decode('cp1252', 'replace')))
        elif c == 0x18:
            close_link()
            finish_pending()
            stack.append((out, table))
            out = []
            table = {'rows': [[]], 'widths': None}
        elif c == 0x1a:
            close_link()
            finish_pending()
            if para.inline:
                end_paragraph('')
                finish_pending()
            table['rows'][-1].append(''.join(out))
            out = []
        elif c == 0x0b:
            table['rows'].append([])
            rec['text'].append(' \u00b7 ')
        elif c == 0x19:
            f, _ = F.flag_fields(d, o, 0x19)
            if 0 in f:
                raw = f[0][1:]
                table['widths'] = [struct.unpack_from('<H', raw, 2 * i)[0] for i in range(len(raw) // 2)]
        elif c == 0x0c:
            rows = ''.join('<tr>%s</tr>' % ''.join('<td>%s</td>' % cell for cell in row)
                           for row in table['rows'] if row)
            cols = ''
            if table['widths'] and all(w < 0x8000 for w in table['widths']):
                cols = '<colgroup>%s</colgroup>' % ''.join(
                    '<col style="width:%gpt">' % (w / 20) for w in table['widths'])
            out, table = stack.pop()
            out.append('<table>%s%s</table>' % (cols, rows))
        elif c == 0x0f:
            close_link()
            finish_pending()
            if para.inline:
                end_paragraph('')
                finish_pending()
            while stack:            # unterminated table: close it
                body = ''.join(out)
                out, table = stack.pop()
                out.append(body)
            rec['level'] = struct.unpack_from('<H', d, o + 2)[0]
            rec['html'] = ''.join(out)
            records.append(rec)
            out = []
            rec = new_record()
            char_style, hidden, heading_on = '', False, False
    close_link()
    finish_pending()
    if para.inline:
        end_paragraph('')
        finish_pending()
    rec['html'] = ''.join(out)
    records.append(rec)
    return records


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------
def write_json(path, value):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=1)
        f.write('\n')


def main(src, stylesheet, outdir):
    ib = F.Infobase(src)
    style_names = {c: ib.names[c] for c in (0x12, 0x14, 0x16)}
    print('rendering records...')
    records = render(ib, style_names)
    print(len(records), 'records')

    # outline levels in the infobase's own order; records at other levels
    # (including the normal level) are body text of the entry above them
    used_levels = {r['level'] for r in records if r['level']}
    level_order = [lv for lv in ib.names[0x0f] if lv in used_levels]
    depth = {lv: i + 1 for i, lv in enumerate(level_order)}
    stack = []                     # (depth, record) of the enclosing outline entries
    for i, r in enumerate(records):
        k = depth.get(r['level'])
        if k:
            while stack and stack[-1][0] >= k:
                stack.pop()
        r['parent'] = stack[-1][1] if stack else None
        r['depth'] = k
        if k:
            stack.append((k, i))

    records_dir = os.path.join(outdir, 'records')
    if os.path.exists(records_dir):
        shutil.rmtree(records_dir)
    os.makedirs(records_dir)
    for start in range(0, len(records), RECORD_SHARD):
        path = os.path.join(records_dir, '%06d.jsonl' % start)
        with open(path, 'w', encoding='utf-8') as f:
            for i in range(start, min(start + RECORD_SHARD, len(records))):
                r = records[i]
                f.write(json.dumps({
                    'id': i,
                    'level': ib.names[0x0f].get(r['level']) if r['level'] else None,
                    'depth': r['depth'],
                    'parent': r['parent'],
                    'heading': r['heading'],
                    'text': ''.join(r['text']),
                    'html': r['html'],
                    'anchors': r['anchors'],
                    'objects': r['objects'],
                }, ensure_ascii=False, separators=(',', ':')) + '\n')

    write_json(os.path.join(outdir, 'infobase.json'), {
        'title': 'Changing Hands',
        'source': 'ChangingHands.nfo (Folio Views 4 infobase)',
        'record_count': len(records),
        'record_shard_size': RECORD_SHARD,
        'levels': [{'name': ib.names[0x0f][lv], 'depth': depth[lv]} for lv in level_order],
    })
    write_json(os.path.join(outdir, 'styles.json'), [
        {'kind': 'paragraph' if kind == 's' else 'character', 'name': name,
         'class': css_class('p-' if kind == 's' else 'c-', name), 'css': rules}
        for kind, name, rules in rtf_stylesheet(stylesheet)])
    print('done:', outdir)


if __name__ == '__main__':
    main(*sys.argv[1:4])
