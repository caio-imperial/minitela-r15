#!/usr/bin/env python3
"""
lab_acf.py — bancada para descobrir o layout do container Texture.acf.

Ideia: em vez de adivinhar o layout varrendo bytes, alimentamos o compilador oficial
com imagens *sintéticas* cujo resultado em DXT é previsível byte a byte, e procuramos
essa assinatura no .acf gerado. Cada imagem responde uma pergunta:

    solid   240x240 de uma cor só   -> ONDE a imagem foi colocada no arquivo
    quad    4 quadrantes de cores   -> orientação e ordem dos blocos
    stripes 60 faixas verticais     -> largura do atlas / stride entre linhas de blocos
    marker  preto + 2 blocos brancos-> primeiro e último bloco, confirma raster vs swizzle

Depois de descoberto o layout, o wine é descartado: o gerador final é nativo.

Uso:
    ./lab_acf.py images                 # cria as imagens sintéticas (não precisa de wine)
    ./lab_acf.py predict solid          # mostra a assinatura DXT esperada
    ./lab_acf.py run solid              # compila via wine e guarda lab/out/solid.acf
    ./lab_acf.py find solid             # procura a assinatura dentro do .acf gerado
    ./lab_acf.py diff solid quad        # onde dois .acf diferem
"""

import argparse
import os
import shutil
import struct
import subprocess
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.expanduser("~/.local/share/minitela-custom")
LAB = os.path.join(WORK, "lab")
IMG = os.path.join(LAB, "img")
OUT = os.path.join(LAB, "out")
SLOT = "1i1h1e37393671471.gif"        # slot 1 (tema 21)
W = H = 240

# ------------------------------------------------------------------ PNG puro

def write_png(path, pixels, w=W, h=H):
    """pixels: bytes RGB (w*h*3). PNG sem perdas, sem dependências."""
    raw = b"".join(b"\x00" + pixels[y * w * 3:(y + 1) * w * 3] for y in range(h))
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    open(path, "wb").write(png)


def make_images():
    os.makedirs(IMG, exist_ok=True)

    def blank(color=(0, 0, 0)):
        return bytearray(bytes(color) * (W * H))

    # 1) solid: uma cor só
    write_png(f"{IMG}/solid.png", bytes(blank((255, 0, 0))))

    # 2) quad: 4 quadrantes
    px = blank()
    cores = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)]
    for y in range(H):
        for x in range(W):
            c = cores[(1 if x >= W // 2 else 0) + (2 if y >= H // 2 else 0)]
            px[(y * W + x) * 3:(y * W + x) * 3 + 3] = bytes(c)
    write_png(f"{IMG}/quad.png", bytes(px))

    # 3) stripes: 60 faixas verticais de 4px (uma por coluna de blocos DXT)
    px = blank()
    for y in range(H):
        for x in range(W):
            v = (x // 4) * 4 + 3          # 0,4,8,... distingue cada coluna de blocos
            px[(y * W + x) * 3:(y * W + x) * 3 + 3] = bytes((v & 255, 0, 255 - (v & 255)))
    write_png(f"{IMG}/stripes.png", bytes(px))

    # 4) marker: preto, com bloco 4x4 branco no canto superior esquerdo e inferior direito
    px = blank()
    for (bx, by) in ((0, 0), (W - 4, H - 4)):
        for y in range(by, by + 4):
            for x in range(bx, bx + 4):
                px[(y * W + x) * 3:(y * W + x) * 3 + 3] = b"\xff\xff\xff"
    write_png(f"{IMG}/marker.png", bytes(px))

    print(f"imagens sintéticas em {IMG}:")
    for n in ("solid", "quad", "stripes", "marker"):
        p = f"{IMG}/{n}.png"
        print(f"   {n:8} {os.path.getsize(p):7} bytes")
    print("\nagora converta para GIF e compile:  ./lab_acf.py run solid")


# --------------------------------------------------------------- previsão DXT

def rgb_to_565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def predict_solid(color=(255, 0, 0)):
    """Uma cor lisa vira blocos DXT idênticos e previsíveis."""
    c = rgb_to_565(*color)
    # DXT1 de bloco liso: c0 == c1 == cor, índices todos 0 (usa a rampa de 3 cores)
    dxt1 = struct.pack("<HHI", c, c, 0)
    # DXT5: 8 bytes de alpha (opaco: a0=255, a1=255, índices 0) + o bloco DXT1
    dxt5 = struct.pack("<BB", 255, 255) + b"\x00" * 6 + dxt1
    return dxt1, dxt5


def cmd_predict(args):
    dxt1, dxt5 = predict_solid()
    print(f"cor        : (255,0,0) -> RGB565 0x{rgb_to_565(255,0,0):04X}")
    print(f"bloco DXT1 : {dxt1.hex(' ')}   ({len(dxt1)} B) -> 3600 blocos = {3600*8} B")
    print(f"bloco DXT5 : {dxt5.hex(' ')}   ({len(dxt5)} B) -> 3600 blocos = {3600*16} B")
    print("\nprocure essa sequência repetida dentro do .acf: ./lab_acf.py find solid")


# ------------------------------------------------------------------ compilação

def to_gif(src, dst):
    """PNG -> GIF preservando as cores exatas (sem dither)."""
    vf = "split[a][b];[a]palettegen=max_colors=256:stats_mode=full[p];[b][p]paletteuse=dither=none"
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                        "-i", src, "-vf", vf, "-loop", "0", dst], capture_output=True)
    if r.returncode:
        sys.exit("ffmpeg falhou: " + r.stderr.decode(errors="replace")[:800])


def cmd_run(args):
    if not shutil.which("wine"):
        sys.exit("wine não instalado — veja o README (é usado só como bancada de análise)")
    sys.path.insert(0, HERE)
    import zipfile
    ide = os.path.join(WORK, "IDE_utils")
    if not os.path.isdir(ide):
        sys.exit("workspace não montado: rode ./minitela_build.py setup")
    os.makedirs(OUT, exist_ok=True)

    png = f"{IMG}/{args.name}.png"
    if not os.path.exists(png):
        sys.exit(f"não achei {png} — rode ./lab_acf.py images")
    gif = f"{IMG}/{args.name}.gif"
    to_gif(png, gif)

    # projeto isolado por experimento, mantendo o nome 'file.zip' que o gerador espera
    expdir = os.path.join(LAB, f"exp_{args.name}")
    os.makedirs(expdir, exist_ok=True)
    proj = os.path.join(expdir, "file.zip")
    shutil.copy2(os.path.join(WORK, "project", "file.zip"), proj)
    tmp = proj + ".tmp"
    with zipfile.ZipFile(proj) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for it in zin.infolist():
            data = open(gif, "rb").read() if it.filename == SLOT else zin.read(it.filename)
            zout.writestr(it.filename, data)
    os.replace(tmp, proj)

    gen_dir = os.path.join(ide, "Gen")
    acf_dir = os.path.join(ide, "ACF")
    os.makedirs(acf_dir, exist_ok=True)
    for f in os.listdir(acf_dir):
        if f.endswith(".acf"):
            os.unlink(os.path.join(acf_dir, f))

    cmd = ["wine", os.path.join(gen_dir, "AHMISimGenDemo_og.exe"),
           "-f", proj, "-m", "2", "-c", "0", "-e", "0", "-d", "0", "-o", acf_dir]
    print("$", " ".join(cmd))
    r = subprocess.run(cmd, cwd=gen_dir, input=b"13", capture_output=True)
    print((r.stdout + r.stderr).decode(errors="replace")[-2500:])

    for f in sorted(os.listdir(acf_dir)):
        if f.endswith(".acf"):
            dst = os.path.join(OUT, f"{args.name}__{f}")
            shutil.copy2(os.path.join(acf_dir, f), dst)
            print(f"guardado: {dst} ({os.path.getsize(dst)} bytes)")


# -------------------------------------------------------------------- análise

def payload(path):
    d = open(path, "rb").read()
    n = struct.unpack("<I", d[:4])[0]
    return d, d[8:8 + n]


def cmd_find(args):
    cands = [f for f in os.listdir(OUT) if f.startswith(args.name + "__")] if os.path.isdir(OUT) else []
    if not cands:
        sys.exit(f"nenhum .acf de '{args.name}' em {OUT} — rode ./lab_acf.py run {args.name}")
    dxt1, dxt5 = predict_solid()
    for c in cands:
        p = os.path.join(OUT, c)
        _, pl = payload(p)
        print(f"\n=== {c} (payload {len(pl)})")
        for tag, blk in (("DXT1", dxt1), ("DXT5", dxt5)):
            # procura a maior repetição contígua do bloco previsto
            best = (0, -1)
            i = pl.find(blk)
            while i != -1:
                n = 0
                while pl[i + n * len(blk): i + (n + 1) * len(blk)] == blk:
                    n += 1
                if n > best[0]:
                    best = (n, i)
                i = pl.find(blk, i + len(blk) * max(n, 1))
            if best[0]:
                print(f"   {tag}: {best[0]} blocos idênticos seguidos @offset {best[1]}"
                      f"  (esperado 3600 para 240x240)")
            else:
                print(f"   {tag}: assinatura não encontrada")
        # também: bytes mais repetidos, para pegar variações
        print(f"   dica: se não achou, a cor pode ter sido alterada pela paletização do GIF")


def cmd_diff(args):
    pa = os.path.join(OUT, args.a) if os.path.exists(os.path.join(OUT, args.a)) else args.a
    pb = os.path.join(OUT, args.b) if os.path.exists(os.path.join(OUT, args.b)) else args.b
    _, x = payload(pa)
    _, y = payload(pb)
    n = min(len(x), len(y))
    difs = [i for i in range(n) if x[i] != y[i]]
    print(f"{os.path.basename(pa)} ({len(x)}) vs {os.path.basename(pb)} ({len(y)})")
    print(f"bytes diferentes: {len(difs)} de {n} ({100*len(difs)/max(n,1):.2f}%)")
    if difs:
        print(f"primeira diferença: offset {difs[0]}   última: {difs[-1]}")
        # agrupa em regiões contíguas (tolerando buracos de até 64 bytes)
        regs = []
        ini = prev = difs[0]
        for i in difs[1:]:
            if i - prev > 64:
                regs.append((ini, prev)); ini = i
            prev = i
        regs.append((ini, prev))
        print(f"regiões alteradas: {len(regs)}")
        for a, b in regs[:12]:
            print(f"   [{a:8} .. {b:8}]  {b-a+1:8} bytes")


def main():
    p = argparse.ArgumentParser(description="Bancada de RE do container .acf")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("images", help="gera as imagens sintéticas").set_defaults(fn=lambda a: make_images())
    s = sub.add_parser("predict", help="assinatura DXT esperada"); s.add_argument("name", nargs="?", default="solid"); s.set_defaults(fn=cmd_predict)
    s = sub.add_parser("run", help="compila via wine"); s.add_argument("name"); s.set_defaults(fn=cmd_run)
    s = sub.add_parser("find", help="procura a assinatura no .acf"); s.add_argument("name"); s.set_defaults(fn=cmd_find)
    s = sub.add_parser("diff", help="compara dois .acf"); s.add_argument("a"); s.add_argument("b"); s.set_defaults(fn=cmd_diff)
    a = p.parse_args(); a.fn(a)


if __name__ == "__main__":
    main()
