#!/usr/bin/env python3
"""
acf_codec.py — codec nativo do formato de textura da minitela (GC9002 / AHMI).

Formato do bloco (16 bytes = 128 bits, bitstream LSB-first começando no bit 1):

    bit  0        flag de modo (0 = uma partição; 1 = duas partições)
    bits 1-8      R0      bits  9-16   R1
    bits 17-24    G0      bits 25-32   G1
    bits 33-40    B0      bits 41-48   B1
    bits 49-56    A0      bits 57-64   A1
    bits 65-128   16 pesos de 4 bits (pixel i em 65+4i, ordem raster no bloco 4x4)

A interpolação é a do firmware (`interpolate()` em CS/AHMI/Simulator/stc.cpp):

    true_w = w + w/8            (divisão inteira)
    cor    = clamp(a0 + (a1 - a0) * true_w / 16)

i.e. o peso 15 vira 16/16 = 1.0 e o 8 vira 9/16, e não w/15.

Modo 0 é o que este codec escreve. O compilador do ODM usa modo 1 (duas partições)
em blocos com cores não colineares; para *gerar* não faz falta — modo 0 representa
qualquer bloco, com menos fidelidade nesses casos.

Sem dependências além da stdlib.
"""

BLOCK_BYTES = 16
BLOCK_PX = 16          # 4x4


# ------------------------------------------------------------------ bit utils

def _rd(buf, base, n):
    return sum(((buf[(base + k) >> 3] >> ((base + k) & 7)) & 1) << k for k in range(n))


def _wr(buf, base, n, value):
    for k in range(n):
        b = base + k
        if (value >> k) & 1:
            buf[b >> 3] |= 1 << (b & 7)
        else:
            buf[b >> 3] &= ~(1 << (b & 7)) & 0xFF


# -------------------------------------------------------------------- decode

BLOCK_BITS = 128
BASE_BIT = 1          # o stream da textura começa no bit 1 do primeiro byte


def block_base(index):
    return BASE_BIT + index * BLOCK_BITS


def _interp(a0, a1, w):
    """Interpolação do firmware (stc.cpp: interpolate), com truncamento C."""
    true_w = w + (w >> 3)                  # w + w/8, divisão inteira
    num = (a1 - a0) * true_w
    v = a0 + (num >> 4 if num >= 0 else -((-num) >> 4))
    return 0 if v < 0 else 255 if v > 255 else v


def block_mode(textura, index):
    """0 = uma partição (o que geramos), 1 = duas partições (o compilador do ODM)."""
    b = block_base(index)
    return (textura[b >> 3] >> (b & 7)) & 1


def decode_block_at(buf, base):
    """Lê um bloco a partir de `base` (em bits) dentro do buffer da textura."""
    e0, e1 = [], []
    for c in range(4):                     # R, G, B, A — pares (c0,c1) intercalados
        e0.append(_rd(buf, base + c * 16, 8))
        e1.append(_rd(buf, base + c * 16 + 8, 8))
    px = []
    for p in range(BLOCK_PX):
        w = _rd(buf, base + 64 + 4 * p, 4)
        px.append(tuple(_interp(e0[c], e1[c], w) for c in range(4)))
    return px


def decode_image(textura, width, height):
    """Textura -> bytes RGB (width*height*3)."""
    out = bytearray(width * height * 3)
    bw = width // 4
    # uma folga de 1 byte evita estourar no último bloco (o bit 128 dele cai fora)
    buf = bytes(textura) + b"\x00"
    for bi in range((width // 4) * (height // 4)):
        px = decode_block_at(buf, block_base(bi))
        bx, by = bi % bw, bi // bw
        for p in range(BLOCK_PX):
            x, y = bx * 4 + p % 4, by * 4 + p // 4
            o = (y * width + x) * 3
            out[o:o + 3] = bytes(px[p][:3])
    return bytes(out)


# -------------------------------------------------------------------- encode

def encode_block_at(buf, base, pixels):
    """Escreve um bloco em `base` (bits) dentro de `buf` (bytearray)."""
    px = [tuple(p) + ((255,) if len(p) == 3 else ()) for p in pixels]
    amp = [max(q[c] for q in px) - min(q[c] for q in px) for c in range(4)]
    eixo = amp.index(max(amp))
    if amp[eixo] == 0:
        c0 = c1 = px[0]
        pesos = [0] * BLOCK_PX
    else:
        c0 = min(px, key=lambda q: q[eixo])
        c1 = max(px, key=lambda q: q[eixo])
        # escolhe o peso que minimiza o erro sob a interpolação REAL do firmware
        def melhor(q):
            best = (1 << 30, 0)
            for w in range(16):
                e = sum((_interp(c0[c], c1[c], w) - q[c]) ** 2 for c in range(4))
                if e < best[0]:
                    best = (e, w)
            return best[1]
        pesos = [melhor(q) for q in px]

    # O peso do pixel 15 ocuparia os bits 125-128, e o bit 128 já é o byte do bloco
    # seguinte: o firmware lê apenas 3 bits ali (0-7). Quando o peso natural passa de
    # 7, invertemos os endpoints (peso vira 15-w) — é o que o compilador do ODM faz.
    def erro(cc0, cc1, ws):
        return sum((_interp(cc0[c], cc1[c], ws[p]) - px[p][c]) ** 2
                   for p in range(BLOCK_PX) for c in range(4))

    cand_a = (c0, c1, pesos) if pesos[BLOCK_PX - 1] <= 7 else None
    invertidos = [15 - w for w in pesos]
    cand_b = (c1, c0, invertidos) if invertidos[BLOCK_PX - 1] <= 7 else None
    if cand_a and cand_b:
        c0, c1, pesos = cand_a if erro(*cand_a) <= erro(*cand_b) else cand_b
    elif cand_b:
        c0, c1, pesos = cand_b
    for c in range(4):
        _wr(buf, base + c * 16, 8, c0[c])
        _wr(buf, base + c * 16 + 8, 8, c1[c])
    for p in range(BLOCK_PX):
        nbits = 4 if p < BLOCK_PX - 1 else 3
        _wr(buf, base + 64 + 4 * p, nbits, pesos[p] & ((1 << nbits) - 1))


def encode_image(rgb, width, height):
    """bytes RGB -> textura (width*height/16 blocos de 16 B)."""
    nblocos = (width // 4) * (height // 4)
    buf = bytearray(nblocos * BLOCK_BYTES + 1)     # +1 de folga para o último bit
    bw = width // 4
    for bi in range(nblocos):
        bx, by = bi % bw, bi // bw
        bloco = []
        for p in range(BLOCK_PX):
            x, y = bx * 4 + p % 4, by * 4 + p // 4
            o = (y * width + x) * 3
            bloco.append((rgb[o], rgb[o + 1], rgb[o + 2], 255))
        encode_block_at(buf, block_base(bi), bloco)
    return bytes(buf[:nblocos * BLOCK_BYTES])



# ------------------------------------------------------------------ checksum

FOOTER_MAGIC = 0xA55A5AA5


def compute_checksum(data):
    """XOR de todas as words de 32 bits LE, pulando o próprio campo (offset 4) e a
    última word (o FooterMagic). Com o valor correto em [4:8], o XOR de TODAS as words
    do arquivo dá exatamente FOOTER_MAGIC.

    Algoritmo identificado pelo projeto SideCar (github.com/FreyreCorona/SideCar);
    validado aqui contra os .acf de fábrica e contra os gerados pelo compilador do ODM.
    """
    import struct as _s
    n = len(data)
    x = 0
    for i in range(0, n - 3, 4):
        if i == 4 or i == n - 4:
            continue
        x ^= _s.unpack_from("<I", data, i)[0]
    return x


def set_checksum(data):
    """Recalcula e grava o checksum em [4:8]. `data` deve ser bytearray."""
    import struct as _s
    _s.pack_into("<I", data, 4, 0)
    _s.pack_into("<I", data, 4, compute_checksum(data))
    return data


def verify_checksum(data):
    """True se o arquivo está consistente (XOR de todas as words == FOOTER_MAGIC)."""
    import struct as _s
    x = 0
    for i in range(0, len(data) - 3, 4):
        x ^= _s.unpack_from("<I", data, i)[0]
    return x == FOOTER_MAGIC


# --------------------------------------------------------------------- patch

def patch_acf(acf_bytes, offset, textura):
    """Devolve o .acf com a região da imagem trocada, corrigindo o header.

    header: [0:4] tamanho do payload (u32 LE), [4:8] checksum.
    O tamanho não muda (a textura tem tamanho fixo), então só o conteúdo é reescrito.
    """
    import struct
    d = bytearray(acf_bytes)
    n = struct.unpack("<I", d[:4])[0]
    ini = 8 + offset
    if ini + len(textura) > 8 + n:
        raise ValueError("a textura não cabe no payload")
    d[ini:ini + len(textura)] = textura
    return bytes(d)


if __name__ == "__main__":
    # autoteste: gradiente linear deve sobreviver ao ida-e-volta
    W = H = 8
    rgb = bytearray()
    for y in range(H):
        for x in range(W):
            v = (y * W + x) * 255 // (W * H - 1)
            rgb += bytes((v, v, v))
    tex = encode_image(bytes(rgb), W, H)
    volta = decode_image(tex, W, H)
    erro = max(abs(a - b) for a, b in zip(rgb, volta))
    print(f"gradiente {W}x{H}: {len(tex)} bytes, erro máximo por canal = {erro}")
    tex2 = encode_image(volta, W, H)
    print(f"reencode estável: {tex == tex2}")
