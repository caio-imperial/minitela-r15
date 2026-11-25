#!/usr/bin/env python3
"""
acf_inspect.py — le um Texture.acf com o mapa do firmware (SDK 1.10.20).

Valida o que o firmware valida de fato:
  * StartOfConfigdata % 16384 == 0
  * MagicNumber == 0x494d4841 ("AHMI") em ConfigInfo+32
  * AHMIInfo.Version em ConfigInfo+260 (esperado 0x5A010a13)
  * CheckCode de cada pagina == 0xA55A5AA5 ^ XOR(u32 do bloco)

E lista a tabela de texturas (TextureClass, 48 B por registro) de cada pagina.

O checksum do arquivo (u32 @4) NAO e validado pelo firmware; aqui so reportamos.

Uso:
    ./acf_inspect.py Texture.acf
    ./acf_inspect.py Texture.acf --textures     # detalha cada textura
    ./acf_inspect.py /usr/share/minitela/resources/ACF/*.acf   # so o resumo

Referencia: RE-acf-source.md (§3), RE-acf.md.
"""

import argparse
import glob
import struct
import sys

MAGIC = 0x494D4841            # "AHMI" em ConfigInfo+32
CFG_MAGIC = 0x41484D49        # "IMHA" em upg_cfg.bin (byte-order trocado)
AHMI_VERSION = 0x5A010A13
PAGE_XOR_SEED = 0xA55A5AA5
CONFIG_INFO_SIZE = 284
PAGE_CFG_SIZE = 56
TEXTURE_SIZE = 48

TEX_TYPE = {
    0x00: "STCRGB888", 0x10: "STCRGBA888", 0x20: "ALPHA1", 0x30: "PURECOLOR",
    0x40: "RGB565", 0x50: "RGBA8888", 0x60: "Y8", 0x70: "RGB565_RE",
    0x80: "PUREMASK", 0x90: "ALPHA2", 0xA0: "ALPHA8", 0xB0: "ALPHA4",
    0xC0: "ARGB1555", 0xD0: "ARGB4444", 0xE0: "SFBC", 0xF0: "RGBA8888_RE",
}


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def u16(b, o):
    return struct.unpack_from("<H", b, o)[0]


def s16(b, o):
    return struct.unpack_from("<h", b, o)[0]


def xor_words(data):
    x = 0
    for (w,) in struct.iter_unpack("<I", data[: len(data) // 4 * 4]):
        x ^= w
    return x


def _coerentes(data, base, ntex, nfile):
    """Quantos dos `ntex` registros candidatos batem com a formula/limites."""
    good = 0
    for t in range(ntex):
        p = base + t * TEXTURE_SIZE
        w, h = u16(data, p + 16), u16(data, p + 18)
        if not (1 <= w <= 1024 and 1 <= h <= 1024):
            continue
        slice_, addr, attr = u32(data, p), u32(data, p + 4), u32(data, p + 12)
        tipo = (attr >> 4) & 0xF
        esperado = ((w + 3) // 4) * ((h + 3) // 4) * 16
        if tipo == 0x3:                     # PURECOLOR: sem dados, addr e a cor ARGB
            good += slice_ == 0
        elif tipo == 0x8:                   # PUREMASK: mascara chapada
            good += 1
        elif tipo in (0x0, 0x1):            # STC: 16 B por bloco 4x4
            good += (slice_ == esperado and addr < nfile)
        else:                               # ALPHA2/ARGB1555/...: formula nao modelada
            good += 1
    return good


def _find_table(data, block_start, size, ntex, nfile):
    """Procura o inicio de TextureClass[] dentro do bloco (antes dos arrays finais).

    Devolve (offset, registros_coerentes). Blocos com muitos widgets/acoes e texturas
    de GIF (varias fatias) nao batem 100% com a formula, por isso escolhemos o melhor.
    """
    best = (None, -1)
    for off in range(size - ntex * TEXTURE_SIZE, -1, -4):
        n = _coerentes(data, block_start + off, ntex, nfile)
        if n > best[1]:
            best = (off, n)
            if n == ntex:
                break
    return best


def parse(path, show_textures=False):
    data = open(path, "rb").read()
    problems = []
    if len(data) < 0x4000:
        return {"path": path, "erro": "arquivo menor que 16 KB"}, ["tamanho"]

    start, file_cks, unk = u32(data, 0), u32(data, 4), u32(data, 8)
    project = data[12:0x4000].split(b"\0", 1)[0].decode("ascii", "replace")
    if start % 0x4000:
        problems.append(f"StartOfConfigdata {start:#x} nao e multiplo de 16 KB")

    cfg = data[start:]
    magic = u32(cfg, 32)
    total = u32(cfg, 36)
    version = u32(cfg, 260)
    cfgstr = u16(cfg, 72)
    npages = u16(cfg, 74)
    width, height = u16(cfg, 264), u16(cfg, 266)

    if magic != MAGIC:
        problems.append(f"magic {magic:#x} != {MAGIC:#x}")
    if total != len(data) - 8:
        problems.append(f"TotalSize {total} != tamanho-8 ({len(data) - 8})")
    if version != AHMI_VERSION:
        problems.append(f"AHMIInfo.Version {version:#010x} != {AHMI_VERSION:#010x}")

    pages = []
    base = CONFIG_INFO_SIZE + cfgstr
    for i in range(npages):
        o = base + i * PAGE_CFG_SIZE
        store, size, check = u32(cfg, o), u32(cfg, o + 4), u32(cfg, o + 8)
        ntex = u16(cfg, o + 14)
        touch = u16(cfg, o + 24)
        block = data[start + store: start + store + size]
        calc = (PAGE_XOR_SEED ^ xor_words(block)) if len(block) == size else None
        ok = calc == check
        if not ok:
            problems.append(f"pagina {i}: CheckCode {check:#010x} != {calc if calc is None else hex(calc)}")

        texs = []
        # A tabela fica no fim do bloco, antes de ate 4 arrays variaveis. Em vez de
        # modelar os arrays, procura-se o offset que faz TODOS os registros coerentes
        # (w/h plausiveis, slice == ceil(w/4)*ceil(h/4)*16, addr dentro do arquivo).
        if ntex:
            off, coerentes = _find_table(data, start + store, size, ntex, len(data))
            if off is None:
                problems.append(f"pagina {i}: tabela de {ntex} texturas nao localizada")
            else:
                if coerentes < ntex:
                    problems.append(f"pagina {i}: {coerentes}/{ntex} texturas coerentes na tabela")
                for t in range(ntex):
                    p = start + store + off + t * TEXTURE_SIZE
                    attr = u32(data, p + 12)
                    w, h = u16(data, p + 16), u16(data, p + 18)
                    texs.append({
                        "i": t,
                        "slice": u32(data, p),
                        "addr": u32(data, p + 4),
                        "attr": attr,
                        "tipo": TEX_TYPE.get(((attr >> 4) & 0xF) << 4, hex((attr >> 4) & 0xF)),
                        "w": w,
                        "h": h,
                        "esperado": ((w + 3) // 4) * ((h + 3) // 4) * 16,
                    })

        pages.append({"i": i, "store": store, "size": size, "check": check,
                      "ok": ok, "ntex": ntex, "texs": texs})

    info = {
        "path": path, "tamanho": len(data), "start": start, "unk": unk,
        "project": project, "file_cks": file_cks, "npages": npages,
        "w": width, "h": height, "version": version, "pages": pages,
        "problemas": problems,
    }
    return info, problems


def main():
    ap = argparse.ArgumentParser(description="Le e valida um Texture.acf pelo mapa do firmware")
    ap.add_argument("acf", nargs="+")
    ap.add_argument("--textures", action="store_true", help="lista cada textura")
    a = ap.parse_args()

    files = []
    for pat in a.acf:
        files.extend(sorted(glob.glob(pat)) or [pat])

    ruins = 0
    for f in files:
        try:
            info, problems = parse(f, a.textures)
        except Exception as e:
            print(f"{f}: ERRO {e}")
            ruins += 1
            continue
        if "erro" in info:
            print(f"{f}: {info['erro']}")
            ruins += 1
            continue
        ntex = sum(p["ntex"] for p in info["pages"])
        ok = "OK" if not problems else f"{len(problems)} PROBLEMA(S)"
        print(f"{f.rsplit('/', 1)[-1]}: {info['tamanho']} B, {info['w']}x{info['h']}, "
              f"{info['npages']} paginas, {ntex} texturas, cfg@{info['start']:#x} — {ok}")
        if problems:
            ruins += 1
            for p in problems[:6]:
                print(f"    ! {p}")
        if a.textures:
            for pg in info["pages"]:
                for t in pg["texs"]:
                    flag = "" if t["slice"] in (0, t["esperado"]) else "  <- slice != previsto"
                    print(f"    pg{pg['i']} #{t['i']:<2} {t['tipo']:<11} {t['w']:>4}x{t['h']:<4} "
                          f"addr={t['addr']:#010x} slice={t['slice']}{flag}")
    print(f"\n{len(files)} arquivo(s), {ruins} com problema")
    return 1 if ruins else 0


if __name__ == "__main__":
    sys.exit(main())
