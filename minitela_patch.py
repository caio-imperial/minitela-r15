#!/usr/bin/env python3
"""
minitela_patch.py — troca as 3 imagens de um Texture.acf sem o compilador do ODM.

Em vez de recompilar o projeto com wine, parte de um `.acf` que o firmware já aceita
(o "template") e substitui apenas os bytes das texturas, que ficam ANTES de
`StartOfConfigdata` e não são cobertas pelo `CheckCode` das páginas. Todo o resto do
arquivo continua byte a byte idêntico.

O template precisa ter as texturas das imagens 1/2/3 na tela "Imagens": são as páginas
4/5/6 (0-based), cada uma com uma textura STC RGBA. O tamanho dela define o do arquivo
gerado (240x240 num template compilado por nós, 192x192 nos de fábrica).

Uso:
    ./minitela_patch.py --template base.acf --out novo.acf foto1.jpg
    ./minitela_patch.py --template base.acf --out novo.acf a.jpg b.png c.gif --send

O resultado passa pelo `acf_inspect.py` antes de qualquer gravação; com --send, grava
usando o `minitela_ctl.py` (que exige o app oficial parado).
"""

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PADRAO = os.path.expanduser("~/.local/share/minitela-custom/out/minitela.acf")
PAGINAS_IMAGENS = (4, 5, 6)          # 0-based: GIF 1/2/3 = tela "Imagens"


def _carrega(nome):
    spec = importlib.util.spec_from_file_location(nome, os.path.join(HERE, f"{nome}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


codec = _carrega("acf_codec")
insp = _carrega("acf_inspect")


def rgb_do_arquivo(src, w, h):
    """Qualquer imagem -> bytes RGB w*h*3, com o mesmo enquadramento do build."""
    vf = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
          "format=rgb24")
    with tempfile.NamedTemporaryFile(suffix=".rgb", delete=False) as tmp:
        out = tmp.name
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src,
             "-frames:v", "1", "-vf", vf, "-f", "rawvideo", out],
            capture_output=True)
        if r.returncode:
            sys.exit(f"ffmpeg falhou em {src}:\n{r.stderr.decode(errors='replace')[:800]}")
        data = open(out, "rb").read()
    finally:
        os.unlink(out)
    if len(data) != w * h * 3:
        sys.exit(f"ffmpeg devolveu {len(data)} bytes, esperado {w * h * 3}")
    return data


def texturas_das_imagens(info):
    """Devolve as 3 texturas STC das páginas 4/5/6, na ordem."""
    achadas = []
    for pg in info["pages"]:
        if pg["i"] not in PAGINAS_IMAGENS:
            continue
        for t in pg["texs"]:
            if t["tipo"].startswith("STC") and not t["addr"] >= info["tamanho"]:
                achadas.append(t)
    return achadas


def main():
    ap = argparse.ArgumentParser(description="Troca as imagens de um .acf sem recompilar")
    ap.add_argument("imagens", nargs="+", help="1 a 3 imagens (JPG, PNG, GIF…)")
    ap.add_argument("--template", default=TEMPLATE_PADRAO,
                    help=f".acf que o firmware já aceita (padrão: {TEMPLATE_PADRAO})")
    ap.add_argument("--out", default=None, help="arquivo de saída")
    ap.add_argument("--send", action="store_true", help="grava na minitela ao terminar")
    ap.add_argument("--page", type=int, default=None, help="página a exibir depois")
    ap.add_argument("-y", "--yes", action="store_true", help="não pergunta antes de gravar")
    a = ap.parse_args()

    if len(a.imagens) > 3:
        sys.exit("máximo de 3 imagens (as demais ficam como no template)")
    if not os.path.exists(a.template):
        sys.exit(f"template não encontrado: {a.template}\n"
                 "  gere um uma vez com: ./minitela_build.py build foto.jpg")

    info, problemas = insp.parse(a.template)
    if problemas:
        sys.exit("o template não passa na validação do firmware:\n  " + "\n  ".join(problemas))
    alvos = texturas_das_imagens(info)
    if len(alvos) != 3:
        sys.exit(f"esperava 3 texturas de imagem nas páginas {PAGINAS_IMAGENS}, "
                 f"achei {len(alvos)}")

    data = bytearray(open(a.template, "rb").read())
    print(f"template: {a.template} ({len(data)} B, {info['w']}x{info['h']})")
    for img, alvo in zip(a.imagens, alvos):
        w, h = alvo["w"], alvo["h"]
        rgb = rgb_do_arquivo(img, w, h)
        tex = codec.encode_image(rgb, w, h)
        if len(tex) != alvo["slice"]:
            sys.exit(f"{os.path.basename(img)}: textura {len(tex)} B != fatia "
                     f"{alvo['slice']} B ({w}x{h})")
        ini = alvo["addr"]
        data[ini:ini + len(tex)] = tex
        print(f"  {os.path.basename(img):<28} -> {w}x{h} @ {ini:#08x} "
              f"({len(tex)} B, {alvo['tipo']})")

    codec.set_checksum(data)
    out = a.out or os.path.splitext(a.template)[0] + "-patch.acf"
    with open(out, "wb") as f:
        f.write(data)

    info2, problemas2 = insp.parse(out)
    if problemas2:
        sys.exit(f"o arquivo gerado NÃO passou na validação:\n  " + "\n  ".join(problemas2))
    print(f"pronto: {out} ({len(data)} B) — validação OK "
          f"(magic, versão e CheckCode de {info2['npages']} páginas)")

    if a.send:
        ctl = os.path.join(HERE, "minitela_ctl.py")
        cmd = [sys.executable, ctl, "send", out, "--type", "texture"]
        if a.page is not None:
            cmd += ["--page", str(a.page)]
        if a.yes:
            cmd.append("-y")
        print("\ngravando…")
        sys.exit(subprocess.run(cmd).returncode)
    print(f"para gravar:\n   pkill -x minitela && ./minitela_ctl.py send '{out}' -y")


if __name__ == "__main__":
    main()
