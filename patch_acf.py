#!/usr/bin/env python3
"""
patch_acf.py — troca a imagem dentro de um .acf de produção, sem recompilar nada.

Este é o caminho seguro descoberto depois do episódio de travamento: em vez de
recompilar o projeto inteiro (o projeto-base do pacote não é o de produção e trava o
firmware), parte-se de um .acf que o firmware já aceita e sobrescreve-se apenas os
57600 bytes da imagem, deixando todo o resto byte a byte idêntico.

Pendência conhecida: o checksum do header (bytes 4-8) não foi decifrado, então ele fica
com o valor original. Se o firmware validar o checksum, vai recusar — é exatamente o que
este teste serve para descobrir.

Uso:
    ./patch_acf.py --acf /usr/share/minitela/resources/ACF/Texture21.acf \\
                   --offset 685992 --image foto.jpg --out saida.acf
    ./patch_acf.py ... --preview           # só gera o PNG do que ficaria na tela
"""

import argparse
import importlib.util
import os
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("codec", os.path.join(HERE, "acf_codec.py"))
codec = importlib.util.module_from_spec(spec)
spec.loader.exec_module(codec)

W = H = 240
TEX_BYTES = (W // 4) * (H // 4) * 16          # 57600


def carregar_rgb(caminho):
    """Qualquer imagem -> RGB24 240x240 com crop central, via ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as f:
        raw = f.name
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}")
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                        "-i", caminho, "-frames:v", "1", "-vf", vf,
                        "-f", "rawvideo", "-pix_fmt", "rgb24", raw], capture_output=True)
    if r.returncode:
        sys.exit("ffmpeg falhou: " + r.stderr.decode(errors="replace")[:500])
    d = open(raw, "rb").read()
    os.unlink(raw)
    return d


def main():
    ap = argparse.ArgumentParser(description="Troca a imagem dentro de um .acf")
    ap.add_argument("--acf", required=True, help=".acf de produção que já funciona")
    ap.add_argument("--offset", type=int, required=True, help="offset da imagem no payload")
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", help="arquivo de saída (.acf)")
    ap.add_argument("--preview", action="store_true", help="só gera PNG do resultado")
    args = ap.parse_args()

    base = open(args.acf, "rb").read()
    n = struct.unpack("<I", base[:4])[0]
    print(f"base   : {args.acf} ({len(base)} bytes, payload {n})")

    rgb = carregar_rgb(args.image)
    textura = codec.encode_image(rgb, W, H)
    volta = codec.decode_image(textura, W, H)
    erro = sum(abs(a - b) for a, b in zip(rgb, volta)) / len(rgb)
    print(f"imagem : {args.image} -> {len(textura)} bytes de textura (erro médio {erro:.2f}/canal)")

    if args.preview:
        out = (args.out or "preview") + ".png"
        with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as f:
            f.write(volta); raw = f.name
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", f"{W}x{H}",
                        "-i", raw, "-frames:v", "1", out], check=True)
        os.unlink(raw)
        print(f"preview: {out}")
        return

    ini = 8 + args.offset
    if ini + TEX_BYTES > 8 + n:
        sys.exit("a imagem não cabe nesse offset")
    novo = bytearray(base)
    antes = bytes(novo[ini:ini + TEX_BYTES])
    novo[ini:ini + TEX_BYTES] = textura
    mudou = sum(1 for a, b in zip(antes, textura) if a != b)
    print(f"patch  : offset {args.offset}, {mudou} de {TEX_BYTES} bytes alterados")
    antigo = struct.unpack("<I", base[4:8])[0]
    codec.set_checksum(novo)
    print(f"header : checksum {antigo:#010x} -> {struct.unpack('<I', novo[4:8])[0]:#010x} "
          f"(consistente: {codec.verify_checksum(novo)})")

    dst = args.out or (os.path.splitext(args.acf)[0] + "_patched.acf")
    open(dst, "wb").write(bytes(novo))
    print(f"saída  : {dst} ({os.path.getsize(dst)} bytes)")


if __name__ == "__main__":
    main()
