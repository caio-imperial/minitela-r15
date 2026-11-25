#!/usr/bin/env python3
"""
acf_anim.py — monta fatias (quadros) numa textura de um Texture.acf, mudando o tamanho.

O firmware não tem "textura de GIF": ele tem *fatias*. Um registro `TextureClass` com
`SingleSliceSize = S` e N fatias guarda o quadro i em `TexAddr + i*S`; o widget GIF
(tipo 34) avança `GifSliceNum` fatias a cada `GifInterval` ticks
(ActionProcessor.cpp:2405). Com N > 1 existe um trailer logo depois da última:

    u32 flagsAddr   (gravado como u16 alto + u16 baixo)
    u32 colorsAddr  (idem)
    u16 bitmap[]    N bits, MSB-first em cada u16; 1 = fatia opaca

Fonte: RE-acf-source.md §7 (validado reconstruindo o ACF de 75 quadros do ODM, com 10
bytes divergentes, todos lixo do gerador).

Esta rotina também serve para **mudar o tamanho da textura** (por exemplo, trocar o slot
de 192x192 do tema de fábrica por 240x240): o arquivo cresce ou encolhe, tudo depois do
slot anda, e os endereços, o `StartOfConfigdata`, o `TotalTextureSize` e os `CheckCode`
das páginas são recalculados.
"""

import struct

SEED = 0xA55A5AA5


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


def _total_fatias(data, info, page_index, texto):
    """Quantas fatias o registro tem hoje (GifSliceNum do bloco, se houver trailer)."""
    if not _u32(data, texto["off"] + 8):
        return 1
    blk = info["start"] + info["pages"][page_index]["store"]
    n = _u16(data, blk + 0x17E) if blk + 0x180 <= len(data) else 0
    return n or 1


def monta(data, info, page_index, texto, quadros):
    """Devolve o .acf com `quadros` (bytes STC) no registro `texto` da página dada.

    Os quadros podem ter tamanho diferente do atual: o registro é atualizado
    (`SingleSliceSize`, `TexWidth/Height`, `SliceFlagsHeaderAddr`) e a área de textura
    é remontada.
    """
    n = len(quadros)
    if n < 1:
        raise ValueError("sem quadros")
    tamanhos = {len(q) for q in quadros}
    if len(tamanhos) != 1:
        raise ValueError("quadros com tamanhos diferentes")
    sl = tamanhos.pop()
    w = h = int(round((sl / 16) ** 0.5)) * 4      # melhor esforço para o lado quadrado
    if ((w + 3) // 4) * ((h + 3) // 4) * 16 != sl:
        # nao e quadrado: deriva das dimensoes do proprio registro quando o tamanho bate
        if texto["slice"] == sl:
            w, h = texto["w"], texto["h"]
        else:
            raise ValueError("nao consegui derivar w/h do tamanho da fatia")

    addr, start = texto["addr"], info["start"]
    old_n = _total_fatias(data, info, page_index, texto)
    seguintes = [t["addr"] for pg in info["pages"] for t in pg["texs"]
                 if t["addr"] < start and t["addr"] > addr]
    old_total = (min(seguintes) - addr) if seguintes else (start - addr)

    novo_total = n * sl + (trailer_len(n) if n > 1 else 0)
    d = novo_total - old_total

    tail = data[addr + old_total:start]
    fim = addr + novo_total + len(tail)
    new_start = ((fim + 0x3FFF) // 0x4000) * 0x4000

    out = bytearray(new_start + len(data) - start)
    out[:addr] = data[:addr]
    for i, q in enumerate(quadros):
        out[addr + i * sl:addr + (i + 1) * sl] = q

    tr = addr + n * sl
    if n > 1:
        flags = tr + 8
        colors = flags + 2 * ((n + 15) // 16)
        struct.pack_into("<HH", out, tr, flags >> 16, flags & 0xFFFF)
        struct.pack_into("<HH", out, tr + 4, colors >> 16, colors & 0xFFFF)
        for k in range(n):
            off = tr + 8 + 2 * (k // 16)
            struct.pack_into("<H", out, off, _u16(out, off) | (1 << (15 - k % 16)))
    out[addr + novo_total:addr + novo_total + len(tail)] = tail

    cfg = new_start - start
    out[new_start:new_start + len(data) - start] = data[start:]

    struct.pack_into("<I", out, 0, new_start)

    # registros de textura: reloca os que ficam depois e atualiza o do slot
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
            elif t["addr"] == addr and t["i"] == texto["i"] and pg["i"] == page_index:
                struct.pack_into("<I", out, o, sl)              # SingleSliceSize
                struct.pack_into("<I", out, o + 8, tr if n > 1 else 0)
                struct.pack_into("<H", out, o + 16, w)          # TexWidth
                struct.pack_into("<H", out, o + 18, h)          # TexHeight

    # GifSliceNum no bloco do widget (vars[+11], depois de GifNowTime/GifInterval/GifNowIdx)
    blk = new_start + info["pages"][page_index]["store"]
    struct.pack_into("<H", out, blk + 0x17E, n)

    # CheckCode de todas as páginas (o bloco do slot e os relocados mudaram)
    base = 284 + _u16(out, new_start + 72)
    for pg in info["pages"]:
        b = new_start + pg["store"]
        cc = SEED ^ _xor_words(out[b:b + pg["size"]])
        struct.pack_into("<I", out, new_start + base + pg["i"] * 56 + 8, cc)

    # ConfigInfo e header
    struct.pack_into("<I", out, new_start + 36, len(out) - 8)
    novo_tex = _u32(out, new_start + 40) + d
    struct.pack_into("<I", out, new_start + 40, novo_tex)
    struct.pack_into("<I", out, 8, novo_tex // 2)

    # checksum do arquivo, por último
    struct.pack_into("<I", out, 4, 0)
    total = 0
    n_words = len(out) // 4
    for i in range(n_words):
        if i == 1 or i == n_words - 1:
            continue
        total ^= _u32(out, i * 4)
    struct.pack_into("<I", out, 4, total)
    return bytes(out)
