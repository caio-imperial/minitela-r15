#!/usr/bin/env python3
"""
exp_bloco.py — descobre o encoding dos 16 bytes de um bloco 4x4 da textura.

Método: gerar imagens que diferem em UM pixel dentro do primeiro bloco 4x4, compilar
cada uma com o compilador do ODM e comparar os 16 bytes do bloco 0 com os de uma
imagem preta. Que bits mudam, e em que posição, revela o formato.

Nada é gravado na minitela — é tudo análise de arquivo.

Uso:
    ./exp_bloco.py pixels        # 1 pixel branco em cada posição do bloco 0
    ./exp_bloco.py niveis        # bloco 0 inteiro em vários tons de cinza
    ./exp_bloco.py show          # relê os resultados já compilados
"""

import argparse
import importlib.util
import os
import shutil
import struct
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("lab", os.path.join(HERE, "lab_acf.py"))
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)

WORK = lab.WORK
EXP = os.path.join(WORK, "exp")
IMGD = os.path.join(EXP, "img")
OUTD = os.path.join(EXP, "out")
IMG_OFF = 685992          # início da imagem do slot no payload (descoberto pelo diff)
BLK = 16                  # bytes por bloco 4x4
W = H = 240


def wine_env():
    env = dict(os.environ)
    env["WINEPREFIX"] = os.path.expanduser("~/.wine-mt64")
    env.pop("WINEARCH", None)
    env["WINEDEBUG"] = "-all"
    env["WINEDLLOVERRIDES"] = "mscoree,mshtml="
    return env


def compilar(nome, png_path):
    """PNG -> GIF -> projeto -> compilador -> guarda o .acf. Devolve o payload."""
    os.makedirs(OUTD, exist_ok=True)
    dst = os.path.join(OUTD, f"{nome}.acf")
    if not os.path.exists(dst):
        gif = os.path.join(IMGD, f"{nome}.gif")
        lab.to_gif(png_path, gif)
        proj = os.path.join(EXP, "file.zip")
        shutil.copy2(os.path.join(WORK, "project", "file.zip"), proj)
        tmp = proj + ".tmp"
        with zipfile.ZipFile(proj) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for it in zin.infolist():
                data = open(gif, "rb").read() if it.filename == lab.SLOT else zin.read(it.filename)
                zout.writestr(it.filename, data)
        os.replace(tmp, proj)

        ide = os.path.join(WORK, "IDE_utils")
        acf_dir = os.path.join(ide, "ACF")
        for f in os.listdir(acf_dir):
            if f.endswith(".acf"):
                os.unlink(os.path.join(acf_dir, f))
        cmd = ["wine", os.path.join(ide, "Gen", "AHMISimGenDemo_og.exe"),
               "-f", proj, "-m", "2", "-c", "0", "-e", "0", "-d", "0", "-o", acf_dir]
        r = subprocess.run(cmd, cwd=os.path.join(ide, "Gen"), input=b"13",
                           env=wine_env(), capture_output=True)
        src = os.path.join(acf_dir, "Texture.acf")
        if not os.path.exists(src):
            print((r.stdout + r.stderr).decode(errors="replace")[-1500:])
            sys.exit(f"compilação falhou para {nome}")
        shutil.copy2(src, dst)
    d = open(dst, "rb").read()
    return d[8:8 + struct.unpack("<I", d[:4])[0]]


def bloco0(payload, n=1):
    return payload[IMG_OFF:IMG_OFF + BLK * n]


def bits(b):
    return " ".join(f"{x:08b}" for x in b)


def img_preta():
    return bytearray(bytes((0, 0, 0)) * (W * H))


def cmd_pixels(args):
    os.makedirs(IMGD, exist_ok=True)
    base_png = os.path.join(IMGD, "base.png")
    lab.write_png(base_png, bytes(img_preta()))
    base = compilar("base", base_png)
    ref = bloco0(base)
    print(f"bloco 0 da imagem PRETA:\n   hex  {ref.hex(' ')}\n   bits {bits(ref)}\n")

    print("um pixel branco em cada posição do bloco 4x4 (x,y):")
    print(f"{'pos':>6} {'hex do bloco 0':<48} bytes que mudam")
    for i in range(16):
        x, y = i % 4, i // 4
        px = img_preta()
        p = (y * W + x) * 3
        px[p:p + 3] = b"\xff\xff\xff"
        nome = f"px_{x}_{y}"
        png = os.path.join(IMGD, f"{nome}.png")
        lab.write_png(png, bytes(px))
        blk = bloco0(compilar(nome, png))
        dif = [j for j in range(BLK) if blk[j] != ref[j]]
        print(f"  ({x},{y}) {blk.hex(' '):<48} {dif}")


def cmd_niveis(args):
    os.makedirs(IMGD, exist_ok=True)
    base = compilar("base", os.path.join(IMGD, "base.png"))
    ref = bloco0(base)
    print(f"referência (preto): {ref.hex(' ')}\n")
    print("bloco 0 inteiro num tom uniforme:")
    for v in (0, 8, 16, 32, 64, 128, 192, 255):
        px = img_preta()
        for y in range(4):
            for x in range(4):
                p = (y * W + x) * 3
                px[p:p + 3] = bytes((v, v, v))
        nome = f"lvl_{v}"
        png = os.path.join(IMGD, f"{nome}.png")
        lab.write_png(png, bytes(px))
        blk = bloco0(compilar(nome, png))
        print(f"  cinza {v:3d}: {blk.hex(' ')}")



def cmd_modos(args):
    """Imagens que forçam blocos com mais de 2 cores, para achar o gatilho do bit0=1."""
    os.makedirs(IMGD, exist_ok=True)
    base_png = os.path.join(IMGD, "base.png")
    lab.write_png(base_png, bytes(img_preta()))
    ref = bloco0(compilar("base", base_png))
    print(f"preto (modo esperado 0): {ref.hex(' ')}  bit0={ref[0]&1}\n")

    testes = {
        # nome: função que pinta o bloco 4x4 (recebe x,y -> cor)
        "duas_cores":   lambda x, y: (255, 0, 0) if x < 2 else (0, 0, 255),
        "quatro_cores": lambda x, y: [(255,0,0),(0,255,0),(0,0,255),(255,255,255)][(x//2)+(y//2)*2],
        "gradiente":    lambda x, y: (x*60, y*60, 128),
        "xadrez":       lambda x, y: (255,255,255) if (x+y) % 2 == 0 else (0,0,0),
        "16_tons":      lambda x, y: ((y*4+x)*17,)*3,
    }
    for nome, fn in testes.items():
        px = img_preta()
        for y in range(4):
            for x in range(4):
                o = (y*W + x)*3
                px[o:o+3] = bytes(c & 255 for c in fn(x, y))
        png = os.path.join(IMGD, f"{nome}.png")
        lab.write_png(png, bytes(px))
        blk = bloco0(compilar(nome, png))
        print(f"{nome:14} {blk.hex(' ')}  bit0={blk[0]&1}")



def cmd_modo1(args):
    """Varia UMA cor por vez num bloco de 4 cores (que cai em modo 1) para localizar
    os campos de endpoint, e testa padrões de partição."""
    os.makedirs(IMGD, exist_ok=True)

    def pinta(nome, fn):
        px = img_preta()
        for y in range(4):
            for x in range(4):
                o = (y*W + x)*3
                px[o:o+3] = bytes(c & 255 for c in fn(x, y))
        png = os.path.join(IMGD, f"{nome}.png")
        lab.write_png(png, bytes(px))
        return bloco0(compilar(nome, png))

    def quatro(c0):
        return lambda x, y: [c0, (0,255,0), (0,0,255), (255,255,255)][(x//2)+(y//2)*2]

    print("=== variando SÓ a cor do quadrante superior-esquerdo ===")
    ref = None
    for tag, c in [("ff0000",(255,0,0)), ("800000",(128,0,0)), ("400000",(64,0,0)),
                   ("000000",(0,0,0)), ("00ffff",(0,255,255))]:
        blk = pinta(f"q0_{tag}", quatro(c))
        dif = "" if ref is None else " muda em " + str([i for i in range(16) if blk[i] != ref[i]])
        print(f"  q0={tag}: {blk.hex(' ')}  bit0={blk[0]&1}{dif}")
        if ref is None:
            ref = blk

    print("\n=== padrões de partição (3 cores não colineares) ===")
    padroes = {
        "vert3":  lambda x, y: [(255,0,0),(0,255,0),(0,0,255),(0,0,255)][x],
        "horiz3": lambda x, y: [(255,0,0),(0,255,0),(0,0,255),(0,0,255)][y],
        "diag3":  lambda x, y: [(255,0,0),(0,255,0),(0,0,255)][min((x+y)//2, 2)],
        "canto":  lambda x, y: (255,0,0) if (x==0 and y==0) else ((0,255,0) if x==3 and y==3 else (0,0,255)),
    }
    for nome, fn in padroes.items():
        blk = pinta(f"p_{nome}", fn)
        print(f"  {nome:8} {blk.hex(' ')}  bit0={blk[0]&1}")



def cmd_transbordo(args):
    """O peso do pixel 15 ocupa bits 125-128; o bit 128 cai no byte 16, que é o byte 0 do
    bloco seguinte. Este teste força pesos altos no pixel 15 e olha o byte 16."""
    os.makedirs(IMGD, exist_ok=True)

    def roda(nome, v15):
        px = img_preta()
        # bloco 0: preto e branco definem os endpoints; o pixel (3,3) recebe v15
        for (x, y), c in {(0, 0): (0, 0, 0), (1, 0): (255, 255, 255)}.items():
            o = (y*W + x)*3; px[o:o+3] = bytes(c)
        o = (3*W + 3)*3; px[o:o+3] = bytes((v15, v15, v15))
        png = os.path.join(IMGD, f"{nome}.png")
        lab.write_png(png, bytes(px))
        pl = compilar(nome, png)
        b = pl[IMG_OFF:IMG_OFF+17]         # 16 do bloco + o byte 0 do bloco seguinte
        peso = 0
        for k in range(4):
            bit = 125 + k
            peso |= ((b[bit >> 3] >> (bit & 7)) & 1) << k
        print(f"  pixel15={v15:3d}: bloco={b[:16].hex(' ')} | byte16={b[16]:02x} "
              f"bit128={(b[16]&1)} -> peso15={peso}")

    print("peso do pixel (3,3) e o bit que transborda para o bloco seguinte:")
    for v in (0, 68, 136, 204, 255):
        roda(f"tb_{v}", v)



def cmd_animado(args):
    """Descobre como frames de GIF animado são guardados: monta um GIF de 4 frames de
    cores lisas (fáceis de achar no arquivo) e localiza cada um no .acf."""
    import subprocess, struct, shutil, zipfile
    os.makedirs(IMGD, exist_ok=True)
    cores = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    for i, c in enumerate(cores):
        lab.write_png(os.path.join(IMGD, f"fr{i}.png"), bytes(bytearray(bytes(c) * (W * H))))
    gif = os.path.join(IMGD, "anim.gif")
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                        "-framerate", "4", "-i", os.path.join(IMGD, "fr%d.png"),
                        "-vf", "split[a][b];[a]palettegen=max_colors=256[p];[b][p]paletteuse=dither=none",
                        "-loop", "0", gif], capture_output=True)
    if r.returncode:
        sys.exit("ffmpeg falhou: " + r.stderr.decode(errors="replace")[:500])
    print(f"GIF de {len(cores)} frames: {os.path.getsize(gif)} bytes")

    # compila com esse GIF no slot
    nome = "anim"
    dst = os.path.join(OUTD, f"{nome}.acf")
    os.makedirs(OUTD, exist_ok=True)
    if not os.path.exists(dst):
        proj = os.path.join(EXP, "file.zip")
        shutil.copy2(os.path.join(WORK, "project", "file.zip"), proj)
        tmp = proj + ".tmp"
        with zipfile.ZipFile(proj) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for it in zin.infolist():
                data = open(gif, "rb").read() if it.filename == lab.SLOT else zin.read(it.filename)
                zout.writestr(it.filename, data)
        os.replace(tmp, proj)
        ide = os.path.join(WORK, "IDE_utils"); acf_dir = os.path.join(ide, "ACF")
        for f in os.listdir(acf_dir):
            if f.endswith(".acf"):
                os.unlink(os.path.join(acf_dir, f))
        cmd = ["wine", os.path.join(ide, "Gen", "AHMISimGenDemo_og.exe"),
               "-f", proj, "-m", "2", "-c", "0", "-e", "0", "-d", "0", "-o", acf_dir]
        rr = subprocess.run(cmd, cwd=os.path.join(ide, "Gen"), input=b"13",
                            env=wine_env(), capture_output=True)
        src = os.path.join(acf_dir, "Texture.acf")
        if not os.path.exists(src):
            print((rr.stdout + rr.stderr).decode(errors="replace")[-1200:])
            sys.exit("compilação falhou")
        shutil.copy2(src, dst)
    d = open(dst, "rb").read()
    pl = d[8:8 + struct.unpack("<I", d[:4])[0]]
    print(f"acf: {len(d)} bytes, payload {len(pl)}")

    # cada cor lisa vira um bloco previsível; procura a maior sequência repetida de cada
    for i, c in enumerate(cores):
        blk = bytearray(16)
        for ch, v in enumerate((c[0], c[0], c[1], c[1], c[2], c[2], 255, 255)):
            for k in range(8):
                b = 1 + ch * 8 + k
                if (v >> k) & 1:
                    blk[b >> 3] |= 1 << (b & 7)
        pat = bytes(blk)
        pos, melhor = -1, 0
        j = pl.find(pat)
        while j != -1:
            n = 0
            while pl[j + n * 16: j + (n + 1) * 16] == pat:
                n += 1
            if n > melhor:
                melhor, pos = n, j
            j = pl.find(pat, j + 16 * max(n, 1))
        print(f"  frame {i} {c}: {melhor} blocos iguais seguidos @ offset {pos}"
              f"{'  (3600 = frame inteiro)' if melhor >= 3000 else ''}")


def cmd_show(args):
    if not os.path.isdir(OUTD):
        sys.exit("nada compilado ainda")
    for f in sorted(os.listdir(OUTD)):
        d = open(os.path.join(OUTD, f), "rb").read()
        p = d[8:8 + struct.unpack("<I", d[:4])[0]]
        print(f"{f:<16} {bloco0(p).hex(' ')}")


def main():
    ap = argparse.ArgumentParser(description="Decifra o encoding do bloco da textura")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pixels").set_defaults(fn=cmd_pixels)
    sub.add_parser("niveis").set_defaults(fn=cmd_niveis)
    sub.add_parser("modos").set_defaults(fn=cmd_modos)
    sub.add_parser("modo1").set_defaults(fn=cmd_modo1)
    sub.add_parser("transbordo").set_defaults(fn=cmd_transbordo)
    sub.add_parser("animado").set_defaults(fn=cmd_animado)
    sub.add_parser("show").set_defaults(fn=cmd_show)
    a = ap.parse_args(); a.fn(a)


if __name__ == "__main__":
    main()
