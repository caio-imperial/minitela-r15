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
import os
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
    return parse_bytes(open(path, "rb").read(), path, show_textures)


def parse_bytes(data, nome="<mem>", show_textures=False):
    problems = []
    if len(data) < 0x4000:
        return {"path": nome, "erro": "arquivo menor que 16 KB"}, ["tamanho"]

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
        gif = u16(cfg, o + 26)
        touch = u16(cfg, o + 24)
        block = data[start + store: start + store + size]
        calc = (PAGE_XOR_SEED ^ xor_words(block)) if len(block) == size else None
        ok = calc == check
        if not ok:
            problems.append(f"pagina {i}: CheckCode {check:#010x} != {calc if calc is None else hex(calc)}")

        texs = []
        coerentes = 0
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
                        "off": p,
                        "slice": u32(data, p),
                        "addr": u32(data, p + 4),
                        "attr": attr,
                        "tipo": TEX_TYPE.get(((attr >> 4) & 0xF) << 4, hex((attr >> 4) & 0xF)),
                        "w": w,
                        "h": h,
                        "esperado": ((w + 3) // 4) * ((h + 3) // 4) * 16,
                    })

        pages.append({"i": i, "store": store, "size": size, "check": check,
                      "ok": ok, "ntex": ntex, "texs": texs, "gif": gif,
                      "coerentes": coerentes})

    info = {
        "path": nome, "tamanho": len(data), "start": start, "unk": unk,
        "project": project, "file_cks": file_cks, "npages": npages,
        "w": width, "h": height, "version": version, "pages": pages,
        "problemas": problems,
    }
    return info, problems


def diagnostico(data, nome="<mem>"):
    """Explica POR QUE um .acf seria rejeitado pelo firmware, com a invariante quebrada.

    Devolve lista de (nivel, mensagem, dica). Nivel 0 = ok, 1 = aviso, 2 = erro fatal
    (o firmware trava ou recusa).
    """
    achados = []
    try:
        info, problems = parse_bytes(data, nome)
    except struct.error:
        return [(2, "arquivo truncado: a leitura passou do fim", 
                 "o arquivo foi cortado ou uma gravacao ficou incompleta")]
    except Exception as e:
        return [(2, f"nao consegui interpretar: {e}", "nao parece um .acf?")]
    if "erro" in info:
        return [(2, info["erro"], "arquivo truncado ou nao e um .acf?")]

    def erro(msg, dica):
        achados.append((2, msg, dica))

    def aviso(msg, dica):
        achados.append((1, msg, dica))

    # ---- estrutura geral
    if info["start"] % 0x4000:
        erro(f"StartOfConfigdata = {info['start']:#x} nao e multiplo de 16 KB",
             "header corrompido ou deslocado; o firmware recusa")
    if (len(data) - 8) % 0x4000:
        erro(f"tamanho {len(data)} nao segue 8 + k*16384",
             "arquivo truncado ou padding nao refeito apos edicao")

    # So confiamos na tabela das paginas onde TODOS os registros sao coerentes; nas
    # outras o localizador e best-effort e os enderecos podem ser lixo.
    confiaveis = [pg for pg in info["pages"] if pg["coerentes"] == pg["ntex"]]
    for pg in info["pages"]:
        if pg["coerentes"] < pg["ntex"]:
            aviso(f"pg{pg['i']}: tabela de texturas parcial ({pg['coerentes']}/{pg['ntex']} coerentes)",
                  "checagens de textura desta pagina foram ignoradas")
            # nao inferimos registros individuais aqui: sem a tabela coerente, um
            # deslocamento de 4 bytes ja muda o que se le

    # ---- texturas: tamanho, limites e sobreposicao
    ocupados = []
    for pg in confiaveis:
        for t in pg["texs"]:
            if t["tipo"] == "PURECOLOR":
                continue
            if t["tipo"] in ("STCRGB888", "STCRGBA888") and t["slice"] != t["esperado"]:
                erro(f"pg{pg['i']} #{t['i']}: slice {t['slice']} != {t['esperado']} "
                     f"para {t['w']}x{t['h']}",
                     "TexWidth/TexHeight foram alterados sem atualizar SingleSliceSize")
            if t["addr"] + t["slice"] > info["start"]:
                erro(f"pg{pg['i']} #{t['i']}: textura passa da area ({t['addr']:#x}"
                     f"+{t['slice']} > {info['start']:#x})",
                     "endereco nao foi relocado depois de mudar o tamanho do arquivo")
            ocupados.append((t["addr"], t["addr"] + t["slice"], pg["i"], t["i"]))
    # a mesma textura pode ser referenciada por mais de uma pagina: deduplica antes
    vistos = {}
    for a, b, pi, ti in ocupados:
        vistos.setdefault((a, b), (pi, ti))
    ocupados = sorted((a, b, pi, ti) for (a, b), (pi, ti) in vistos.items())
    for a, b in zip(ocupados, ocupados[1:]):
        if a[1] > b[0]:
            erro(f"pg{a[2]} #{a[3]} e pg{b[2]} #{b[3]} se sobrepoem "
                 f"({a[1]:#x} > {b[0]:#x})",
                 "relocacao deixou duas texturas no mesmo lugar")

    # ---- GIF: GifSliceNum x trailer x espaco ocupado
    for pg in confiaveis:
        if not pg.get("gif"):
            continue
        blk = info["start"] + pg["store"]
        if blk + 0x180 > len(data):
            continue
        n = u16(data, blk + 0x17E)
        if not n:
            continue
        gif_tex = [t for t in pg["texs"] if t["tipo"].startswith("STC")]
        if not gif_tex:
            continue
        t = gif_tex[0]
        flags = u32(data, t["off"] + 8)
        fim = t["addr"] + n * t["slice"]
        if flags == 0:
            if n > 1:
                erro(f"pg{pg['i']}: GifSliceNum={n} mas a textura nao tem trailer",
                     "faltou gravar SliceFlagsHeaderAddr / o trailer de fatias")
        else:
            if flags + 8 > len(data):
                erro("trailer de fatias fora do arquivo", "SliceFlagsHeaderAddr invalido")
            else:
                bitmap = [u16(data, flags + 8 + 2 * k) for k in range((n + 15) // 16)]
                bits = sum(bin(w).count("1") for w in bitmap)
                if bits != n:
                    aviso(f"pg{pg['i']}: GifSliceNum={n} mas o bitmap tem {bits} fatias",
                          "trailer e contagem de quadros nao batem")
            if fim + 16 > info["start"]:
                erro(f"pg{pg['i']}: {n} quadros passam da area de textura",
                     "numero de quadros grande demais para o arquivo")

    # ---- paginas: CheckCode (o que faz o firmware entrar em laco infinito)
    for pg in info["pages"]:
        if not pg["ok"]:
            erro(f"pg{pg['i']}: CheckCode do bloco nao bate",
                 "o firmware entra no laco de AHMIInterface e nao termina: "
                 "recalcule o CheckCode depois de qualquer edicao no bloco")

    if not achados:
        achados.append((0, "todas as invariantes que o firmware checa estao OK", ""))
    return achados


def conserta(data):
    """Recalcula o que o firmware valida: CheckCode das páginas, TotalSize, @8 e checksum.

    NÃO conserta estrutura (tamanho, magic, versão, texturas fora da área): só as
    invariantes derivadas. Devolve (bytes, lista de mudanças).
    """
    out = bytearray(data)
    info, problems = parse_bytes(bytes(out))
    if "erro" in info:
        raise ValueError(info["erro"])
    mudancas = []
    base = CONFIG_INFO_SIZE + u16(out, info["start"] + 72)
    for pg in info["pages"]:
        b = info["start"] + pg["store"]
        calc = PAGE_XOR_SEED ^ xor_words(out[b:b + pg["size"]])
        if calc != pg["check"]:
            struct.pack_into("<I", out, info["start"] + base + pg["i"] * 56 + 8, calc)
            mudancas.append(f"pg{pg['i']}: CheckCode {pg['check']:#010x} -> {calc:#010x}")

    total_size = len(out) - 8
    if u32(out, info["start"] + 36) != total_size:
        mudancas.append(f"TotalSize {u32(out, info['start'] + 36)} -> {total_size}")
        struct.pack_into("<I", out, info["start"] + 36, total_size)

    texto = u32(out, info["start"] + 40)
    if u32(out, 8) != texto // 2:
        mudancas.append(f"@8 {u32(out, 8)} -> {texto // 2}")
        struct.pack_into("<I", out, 8, texto // 2)

    cks_antigo = u32(out, 4)
    total = 0
    n_words = len(out) // 4
    for i in range(n_words):
        if i == 1 or i == n_words - 1:
            continue
        total ^= u32(out, i * 4)
    if cks_antigo != total:
        mudancas.append(f"checksum {cks_antigo:#010x} -> {total:#010x}")
        struct.pack_into("<I", out, 4, total)
    return bytes(out), mudancas


def main():
    ap = argparse.ArgumentParser(description="Le e valida um Texture.acf pelo mapa do firmware")
    ap.add_argument("acf", nargs="+")
    ap.add_argument("--textures", action="store_true", help="lista cada textura")
    ap.add_argument("--diagnostico", action="store_true",
                    help="explica por que um arquivo seria rejeitado (campo a campo)")
    ap.add_argument("--fix", action="store_true",
                    help="recalcula CheckCode das paginas, TotalSize e checksums")
    ap.add_argument("--out", default=None, help="saida do --fix (padrao: <nome>-fix.acf)")
    a = ap.parse_args()

    files = []
    for pat in a.acf:
        files.extend(sorted(glob.glob(pat)) or [pat])

    ruins = 0
    for f in files:
        if a.fix:
            dados = open(f, "rb").read()
            try:
                novo, mudancas = conserta(dados)
            except Exception as e:
                print(f"{f}: nao consegui consertar: {e}")
                ruins += 1
                continue
            saida = a.out or (os.path.splitext(os.path.basename(f))[0] + "-fix.acf")
            try:
                open(saida, "wb").write(novo)
            except OSError as e:
                print(f"{f}: nao consegui escrever {saida}: {e} (use --out)")
                ruins += 1
                continue
            print(f"{f} -> {saida}")
            for m in mudancas:
                print(f"  ~ {m}")
            if not mudancas:
                print("  (nada a corrigir)")
            else:
                _, restam = parse(saida)
                print("  diagnostico depois:", "OK" if not restam else "; ".join(restam[:3]))
                ruins += 1 if restam else 0
            continue
        if a.diagnostico:
            print(f)
            ruins += sum(1 for nivel, _, _ in diagnostico(open(f, "rb").read(), f) if nivel == 2)
            for nivel, msg, dica in diagnostico(open(f, "rb").read(), f):
                marca = {0: "OK  ", 1: "AVISO", 2: "ERRO "}[nivel]
                print(f"  [{marca}] {msg}")
                if dica:
                    print(f"          -> {dica}")
            continue
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
