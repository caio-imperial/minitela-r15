#!/usr/bin/env python3
"""
gerar_fixtures.py — gera as expectativas douradas para o porte para Rust.

O que é commitado são só as *expectativas* (`fixtures/casos.json`): tamanho, páginas,
`CheckCode`s, tabela de texturas e md5. Os `.acf` em si não vão para o repositório —
saem do tema de fábrica do pacote `minitela` e do nosso próprio código.

Assim o porte em Rust pode ser validado byte a byte por quem tiver o pacote instalado,
sem redistribuir material do fabricante (ver docs/legal.md).

Uso:
    python3 apps/desktop/tests/gerar_fixtures.py
"""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SAIDA = os.path.join(HERE, "fixtures")
TMP = "/tmp/minitela-fixtures"

FABRICA = "/usr/share/minitela/resources/ACF/Texture.acf"


def carrega(nome):
    spec = importlib.util.spec_from_file_location(nome, os.path.join(RAIZ, f"{nome}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


insp = carrega("acf_inspect")


def ppm(caminho, w, h, f):
    """PPM cru (P6) determinístico — o ffmpeg lê sem depender de codec."""
    with open(caminho, "wb") as fh:
        fh.write(b"P6\n%d %d\n255\n" % (w, h))
        for y in range(h):
            for x in range(w):
                fh.write(bytes(f(x, y)))


def md5(caminho):
    return hashlib.md5(open(caminho, "rb").read()).hexdigest()


def resumo(caminho):
    """O que o porte em Rust tem de reproduzir."""
    info, problemas = insp.parse(caminho)
    return {
        "tamanho": info["tamanho"],
        "md5": md5(caminho),
        "start": info["start"],
        "paginas": info["npages"],
        "texturas": sum(p["ntex"] for p in info["pages"]),
        "checks": [p["check"] for p in info["pages"]],
        "problemas": problemas,
        "tela": [info["w"], info["h"]],
    }


def main():
    if not os.path.exists(FABRICA):
        sys.exit(f"preciso do tema de fábrica em {FABRICA} (pacote minitela instalado)")
    os.makedirs(SAIDA, exist_ok=True)
    os.makedirs(TMP, exist_ok=True)

    xadrez = os.path.join(TMP, "xadrez.ppm")
    ppm(xadrez, 240, 240, lambda x, y: (255, 0, 0) if (x // 30 + y // 30) % 2 else (0, 0, 0))
    gradiente = os.path.join(TMP, "gradiente.ppm")
    ppm(gradiente, 240, 240, lambda x, y: (x % 256, y % 256, (x + y) % 256))

    gif = os.path.join(TMP, "anim.gif")
    quadros = []
    for i in range(8):
        p = os.path.join(TMP, f"f{i}.ppm")
        ppm(p, 240, 240, lambda x, y, i=i: (i * 32, 255 - i * 32, 128) if (x + y + i * 8) % 16 < 8 else (0, 0, 0))
        quadros.append(p)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-framerate", "8", "-start_number", "0", "-i", os.path.join(TMP, "f%d.ppm"),
                    "-vf", "split[a][b];[a]palettegen=max_colors=256[p];[b][p]paletteuse=dither=none",
                    "-loop", "0", gif], check=True)

    patch = os.path.join(RAIZ, "minitela_patch.py")
    casos = {}

    def roda_patch(nome, imagem, *extra):
        saida = os.path.join(TMP, f"{nome}.acf")
        r = subprocess.run([sys.executable, patch, "--template", FABRICA,
                            "--out", saida, imagem, *extra],
                           capture_output=True, text=True)
        if r.returncode:
            sys.exit(f"{nome}: patch falhou\n{r.stdout}\n{r.stderr}")
        casos[nome] = {"imagem_md5": md5(imagem), **resumo(saida)}
        return saida

    # 192 (tamanho do slot), 240 (--tela-cheia) e GIF de 8 quadros
    roda_patch("estatico_192", xadrez)
    roda_patch("estatico_240", gradiente, "--tela-cheia")
    roda_patch("gif_8", gif)

    # --fix num arquivo com o CheckCode de uma página quebrado de propósito
    base = os.path.join(TMP, "estatico_192.acf")
    dano = bytearray(open(base, "rb").read())
    info, _ = insp.parse(base)
    pg = info["pages"][3]
    dano[info["start"] + pg["store"] + 100] ^= 0xFF
    alvo = os.path.join(TMP, "danificado.acf")
    open(alvo, "wb").write(dano)
    antes, _ = insp.parse_bytes(bytes(dano))
    consertado, mudancas = insp.conserta(bytes(dano))
    depois = os.path.join(TMP, "consertado.acf")
    open(depois, "wb").write(consertado)
    casos["fix"] = {
        "danificado_md5": md5(alvo),
        "consertado_md5": md5(depois),
        "mudancas": mudancas,
        "checks_antes": [p["check"] for p in antes["pages"]],
        "checks_depois": [p["check"] for p in insp.parse(depois)[0]["pages"]],
    }

    # diagnóstico do tema de fábrica (o que o Rust tem de dizer: nenhum problema)
    casos["fabrica"] = {
        "arquivo": FABRICA,
        "md5": md5(FABRICA),
        **{k: v for k, v in resumo(FABRICA).items() if k != "md5"},
    }

    doc = {
        "gerado_por": "apps/desktop/tests/gerar_fixtures.py",
        "ffmpeg": subprocess.run(["ffmpeg", "-version"], capture_output=True,
                                 text=True).stdout.splitlines()[0],
        "observacao": ("os .acf nao sao versionados; regenere com o pacote minitela "
                       "instalado. md5 do gif pode mudar entre versoes de ffmpeg — "
                       "use tamanho/paginas/checks como contrato."),
        "casos": casos,
    }
    destino = os.path.join(SAIDA, "casos.json")
    with open(destino, "w") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"escrito {destino}")
    for nome, c in casos.items():
        print(f"  {nome}: {c.get('tamanho', '-')} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
