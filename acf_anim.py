#!/usr/bin/env python3
"""
acf_anim.py — monta uma textura animada (N quadros) dentro de um Texture.acf.

O firmware não tem "textura de GIF": ele tem *fatias*. Um registro `TextureClass`
com `SingleSliceSize = S` e `SliceFlagsHeaderAddr != 0` contém N fatias de S bytes
em `TexAddr + i*S`, e o widget GIF (tipo 34) avança `GifSliceNum` fatias a cada
`GifInterval` ticks (ActionProcessor.cpp:2405). O trailer de fatias, logo depois da
última, é:

    u32 flagsAddr   (gravado como u16 alto + u16 baixo)
    u32 colorsAddr  (idem)
    u16 bitmap[]    N bits, MSB-first em cada u16; 1 = fatia opaca

Fonte: RE-acf-source.md §7 (validado reconstruindo o ACF de 75 quadros do ODM,
com 10 bytes divergentes, todos lixo do gerador).

A operação muda o tamanho do arquivo: tudo depois do slot anda `d` bytes, então
os `TexAddr` seguintes, o `StartOfConfigdata`, o `TotalSize`, o `TotalTextureSize`
e os `CheckCode` das páginas tocadas são recalculados.
"""

import struct

SEED = 0xA55A5AA5
TEX_STRUCT = 48


def trailer_len(n):
    """Tamanho do trailer de fatias, alinhado em 16: 8 + 2*ceil(n/16) arredondado."""
    return ((8 + 2 * ((n + 15) // 16) + 15) // 16) * 16


def _xor_words(buf):
    x = 0
    for (w,) in struct.iter_unpack("<I", buf[: len(buf) // 4 * 4]):
        x ^= w
    return x


def _u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def _u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def monta(data, info, page_index, texto, quadros):
    """Devolve o .acf com `quadros` (bytes STC) no registro `texto` da página `page_index`."""
    n = len(quadros)
    if n < 1:
        raise ValueError("sem quadros")
    addr, sl, start = texto["addr"], texto["slice"], info["start"]
    if any(len(q) != sl for q in quadros):
        raise ValueError("quadro com tamanho diferente da fatia")

    # fim do trailer antigo = próxima textura depois do slot (ou 16 B por padrão)
    seguintes = [t["addr"] for pg in info["pages"] for t in pg["texs"]
                 if t["addr"] < start and t["addr"] > addr]
    tr_old = (min(seguintes) - addr - sl) if seguintes else 16
    tr_new = trailer_len(n)
    d = n * sl + tr_new - (sl + tr_old)

    tail = data[addr + sl + tr_old:start]
    fim = addr + n * sl + tr_new + len(tail)
    new_start = ((fim + 0x3FFF) // 0x4000) * 0x4000

    out = bytearray(new_start + len(data) - start)
    out[:addr] = data[:addr]
    for i, q in enumerate(quadros):
        out[addr + i * sl:addr + (i + 1) * sl] = q

    # trailer de fatias
    tr = addr + n * sl
    flags = tr + 8
    colors = flags + 2 * ((n + 15) // 16)
    struct.pack_into("<HH", out, tr, flags >> 16, flags & 0xFFFF)
    struct.pack_into("<HH", out, tr + 4, colors >> 16, colors & 0xFFFF)
    for k in range(n):
        off = tr + 8 + 2 * (k // 16)
        struct.pack_into("<H", out, off, _u16(out, off) | (1 << (15 - k % 16)))
    out[addr + n * sl + tr_new:addr + n * sl + tr_new + len(tail)] = tail

    cfg = new_start - start          # deslocamento da config
    out[new_start:new_start + len(data) - start] = data[start:]

    # header
    struct.pack_into("<I", out, 0, new_start)

    # registros de textura: move os que ficam depois do slot e aponta o trailer do slot
    for pg in info["pages"]:
        for t in pg["texs"]:
            off = t.get("off")
            if off is None or t["addr"] >= start:
                continue
            o = off + cfg
            if t["addr"] > addr:
                struct.pack_into("<I", out, o + 4, t["addr"] + d)
                fl = _u32(out, o + 8)
                if fl:
                    struct.pack_into("<I", out, o + 8, fl + d)
            elif t["addr"] == addr:
                struct.pack_into("<I", out, o + 8, tr)

    # GifSliceNum no bloco do widget (vars[+11] vem depois de GifNowTime/GifInterval/GifNowIdx)
    blk = new_start + info["pages"][page_index]["store"]
    struct.pack_into("<H", out, blk + 0x17E, n)

    # CheckCode de toda página cujo bloco mudou (recalculado por segurança em todas)
    base = 284 + _u16(out, new_start + 72)
    for pg in info["pages"]:
        b = new_start + pg["store"]
        cc = SEED ^ _xor_words(out[b:b + pg["size"]])
        struct.pack_into("<I", out, new_start + base + pg["i"] * 56 + 8, cc)

    # ConfigInfo: TotalSize, TotalTextureSize e o campo @8
    struct.pack_into("<I", out, new_start + 36, len(out) - 8)
    novo_tex = _u32(out, new_start + 40) + d
    struct.pack_into("<I", out, new_start + 40, novo_tex)
    struct.pack_into("<I", out, 8, novo_tex // 2)

    # checksum do arquivo: XOR de todas as words, exceto a própria (word 1) e a última
    struct.pack_into("<I", out, 4, 0)
    total = 0
    n_words = len(out) // 4
    for i in range(n_words):
        if i == 1 or i == n_words - 1:
            continue
        total ^= _u32(out, i * 4)
    struct.pack_into("<I", out, 4, total)
    return bytes(out)
