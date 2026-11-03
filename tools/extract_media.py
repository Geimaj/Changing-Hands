"""Extract the infobase's embedded objects into browser-friendly files.

Usage: python extract_media.py <ChangingHands.fdf> <output media dir>

Writes <id>.<ext> files plus media.json mapping object id ->
{"name", "show" (file to display inline), "open" (file to open on click)}.
WMF drawings are converted with wmf2svg when it is on PATH; OLE objects are
Acrobat documents, so the embedded PDF is extracted and its first page
rendered to PNG with macOS sips. On macOS without wmf2svg, convert the .wmf
files elsewhere and re-run: an existing .svg next to a .wmf is picked up.
"""
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys

import olefile
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
import folio_fdf  # noqa: E402


def safe(name):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', name).strip('_')


def dib_to_bmp(dib):
    size, = struct.unpack_from('<I', dib, 0)
    bits, = struct.unpack_from('<H', dib, 14)
    used, = struct.unpack_from('<I', dib, 32)
    colours = used or (1 << bits if bits <= 8 else 0)
    offset = 14 + size + 4 * colours
    return b'BM' + struct.pack('<IHHI', 14 + len(dib), 0, 0, offset) + dib


def main(src, out):
    os.makedirs(out, exist_ok=True)
    ib = folio_fdf.Infobase(src)
    index = {}
    for ident, (name, cls, data) in sorted(ib.objects.items()):
        base = '%d_%s' % (ident, safe(os.path.splitext(name)[0]) or 'object')
        entry = {'name': name}
        if data[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
            ole = olefile.OleFileIO(data)
            pdf = ole.openstream('CONTENTS').read()
            open(os.path.join(out, base + '.pdf'), 'wb').write(pdf)
            subprocess.run(['sips', '-s', 'format', 'png', '-Z', '900',
                            os.path.join(out, base + '.pdf'), '--out',
                            os.path.join(out, base + '.png')],
                           check=True, capture_output=True)
            entry.update(show=base + '.png', open=base + '.pdf', kind='pdf')
        elif data[:2] == b'\x01\x00' and data[2:6] == b'\x28\x00\x00\x00':
            Image.open(io.BytesIO(dib_to_bmp(data[2:]))).save(os.path.join(out, base + '.png'))
            entry.update(show=base + '.png', kind='image')
        elif data[:2] == b'BM' or data[:4] in (b'II*\x00', b'MM\x00*'):
            img = Image.open(io.BytesIO(data))
            if img.mode not in ('RGB', 'RGBA', 'L', 'P', '1'):
                img = img.convert('RGB')
            img.save(os.path.join(out, base + '.png'))
            entry.update(show=base + '.png', kind='image')
        elif data[:3] == b'\xff\xd8\xff' or data[:4] == b'GIF8':
            ext = '.jpg' if data[:1] == b'\xff' else '.gif'
            open(os.path.join(out, base + ext), 'wb').write(data)
            entry.update(show=base + ext, kind='image')
        elif data[:4] in (b'\xd7\xcd\xc6\x9a', b'\x01\x00\x09\x00'):
            wmf = os.path.join(out, base + '.wmf')
            open(wmf, 'wb').write(data)
            svg = os.path.join(out, base + '.svg')
            if shutil.which('wmf2svg'):
                subprocess.run(['wmf2svg', '-o', svg, wmf], check=True)
            bitmap = os.path.join(out, base + '-1.png')
            if os.path.exists(svg) and os.path.getsize(svg) < 2000 and os.path.exists(bitmap):
                # a WMF that only wraps a bitmap: browsers won't load an SVG's
                # external images from <img>, so show the bitmap itself
                entry.update(show=base + '-1.png', open=base + '.wmf', kind='image')
            elif os.path.exists(svg):
                entry.update(show=base + '.svg', open=base + '.wmf', kind='image')
            else:
                entry.update(open=base + '.wmf', kind='file')
        else:
            open(os.path.join(out, base + '.bin'), 'wb').write(data)
            entry.update(open=base + '.bin', kind='file')
        index[ident] = entry
        print(ident, name, '->', entry.get('show') or entry.get('open'))
    json.dump(index, open(os.path.join(out, 'media.json'), 'w'), indent=1)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
