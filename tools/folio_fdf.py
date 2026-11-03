"""Reader for Folio Views 4 "Folio Document Format" (FDF) data.

FDF is the binary format Folio Views puts on the Windows clipboard when text is
copied. A copy of an entire infobase therefore contains every record, its
formatting, links, popups and embedded objects. The layout was worked out by
inspection; nothing here comes from official documentation.

File layout
  0..15   8 zero bytes + 8-byte infobase id
  16..19  u32 length of the token body that starts at offset 20
  body    stream of tokens (see TOKEN LAYOUT below)
  trailer definitions: levels, styles, jump destinations and object data

Token layout: every token starts with a u16 code.
  0x06 text run           u16 length + cp1252 bytes
  0x15 character format   u32 flag word, then one field per set bit (CHAR)
  0x17 paragraph format   u32 flag word, then one field per set bit (PARA);
                          ends the paragraph it follows
  0x16 paragraph style    01 + style id      (applies to the paragraph just ended)
  0x14 character style    01 + style id      (until the next 0x15)
  0x12 field style        01 + style id      (until the next 0x15)
  0x10 level heading      marks where the contents-tree heading text starts
  0x0f record end         u16 level id (0 = normal record)
  0x1e jump destination   u32 destination id
  0x1c link               type name + payload + nested popup document
  0x08 link end
  0x20 object reference   u32 object id, display size in twips at 18/20
  0x18 table start, 0x1a/0x1b cell end + cell format, 0x0a next cell,
  0x0b next row, 0x19 table format, 0x0c table end
  0x09 tab; 0x80-0xff single character
"""
import re
import struct

CHAR = {0: 1, 1: 1, 2: 1, 3: 1, 4: 1, 9: 2, 10: 4, 11: 4, 12: 2}
PARA = {0: 1, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2, 7: 2, 8: 2}
CELL = {1: 2, 3: 1, 10: 10, 11: 10, 12: 10, 13: 10, 14: 10, 15: 10}
TABLE = {4: 2, 5: 2, 7: 2, 8: 2, 10: 10, 11: 10, 12: 10, 13: 10, 14: 10, 15: 10}
FIXED = {0x00: 2, 0x07: 2, 0x08: 2, 0x09: 2, 0x0a: 2, 0x0b: 2, 0x0c: 2, 0x0d: 4,
         0x0f: 18, 0x10: 3, 0x12: 19, 0x14: 19, 0x16: 19, 0x18: 2, 0x1a: 6,
         0x1e: 18, 0x1f: 18, 0x20: 72}


def _font(d, p):
    return p + 1 + d[p] + 2


def _tabs(d, p):
    return p + 1 + 3 * d[p]


def _cols(d, p):
    return p + 1 + 2 * d[p]


SPECIAL = {0x15: (CHAR, {8: _font}), 0x17: (PARA, {9: _tabs}),
           0x1b: (CELL, {}), 0x19: (TABLE, {0: _cols})}


def flag_fields(d, o, code):
    """Return ({bit: raw bytes}, token length) for a flag-word token."""
    table, special = SPECIAL[code]
    flags = struct.unpack_from('<I', d, o + 2)[0]
    p = o + 6
    out = {}
    for b in range(32):
        if flags >> b & 1:
            q = special[b](d, p) if b in special else p + table[b]
            out[b] = d[p:q]
            p = q
    return out, p - o


def link_parts(d, o):
    """Return (type, payload, nested, token length) for a 0x1c link token."""
    p = o + 3
    kind = d[p + 1:p + 1 + d[p]].decode('cp1252')
    p += 1 + d[p]
    n = struct.unpack_from('<H', d, p)[0]
    payload = d[p + 2:p + 2 + n]
    p += 2 + n
    n = struct.unpack_from('<I', d, p)[0]
    nested = d[p + 4:p + 4 + n]
    p += 4 + n + 17
    return kind, payload, nested, p - o


def token_length(d, o):
    c = struct.unpack_from('<H', d, o)[0]
    if c == 0x06:
        return c, 4 + struct.unpack_from('<H', d, o + 2)[0]
    if c in SPECIAL:
        return c, flag_fields(d, o, c)[1]
    if c == 0x1c:
        return c, link_parts(d, o)[3]
    if c in FIXED:
        return c, FIXED[c]
    if 0x80 <= c <= 0xff:
        return c, 2
    raise ValueError('unknown token %#x at offset %d' % (c, o))


def tokens(d, start, end):
    o = start
    while o < end:
        c, n = token_length(d, o)
        yield o, c, n
        o += n


def decode_target(b):
    """Decode a jump target: biased 7-bit big-endian varint."""
    if b[0] < 0x80:
        return b[0]
    if b[1] < 0x80:
        return (((b[0] & 0x7f) << 7) | b[1]) + 0x80
    return (((b[0] & 0x7f) << 14) | ((b[1] & 0x7f) << 7) | b[2]) + 0x4080


class Infobase:
    def __init__(self, path):
        self.d = open(path, 'rb').read()
        self.body_start = 20
        self.body_end = 20 + struct.unpack_from('<I', self.d, 16)[0]
        self._read_definitions()

    def _read_definitions(self):
        """Definitions in the trailer start with a reference token, then a
        u16-prefixed name, then type-specific data."""
        d, t0 = self.d, self.body_end
        t = d[t0:]
        ref_len = {0x0f: 18, 0x12: 18, 0x14: 18, 0x16: 18, 0x1e: 18, 0x1f: 18, 0x20: 18}
        self.names = {c: {} for c in ref_len}
        self.objects = {}
        for code, n in ref_len.items():
            pat = struct.pack('<H', code) + b'(....)' + b'\0' * (n - 6) + b'(..)'
            for m in re.finditer(pat, t, re.S):
                k = struct.unpack('<H', m.group(2))[0]
                name = t[m.end():m.end() + k]
                if not 0 < k < 200 or not all(32 <= ch for ch in name):
                    continue
                ident = struct.unpack('<I', m.group(1))[0]
                self.names[code][ident] = name.decode('cp1252')
                if code == 0x20:
                    p = m.end() + k
                    k2 = struct.unpack_from('<H', t, p)[0]
                    cls = t[p + 2:p + 2 + k2].decode('cp1252')
                    p += 2 + k2
                    size = struct.unpack_from('<I', t, p)[0]
                    self.objects[ident] = (name.decode('cp1252'), cls, t[p + 4:p + 4 + size])
