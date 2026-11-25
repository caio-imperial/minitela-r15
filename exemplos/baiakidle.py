#!/usr/bin/env python3
"""
baiakidle.py — mostra o seu personagem do Baiakidle na Minitela.

Exemplo de como plugar qualquer API: busca os dados, formata em linhas curtas e escreve
nas tags de texto da tela de Clima (a que tem mais campos). Não mexe na flash.

A rota do Baiakidle é pública (não precisa de token).

Uso:
    ./baiakidle.py "haha lafon"              # uma vez
    ./baiakidle.py "haha lafon" --loop 60    # atualiza a cada 60s
"""

import argparse
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "mt", os.path.join(os.path.dirname(HERE), "minitela_tags.py"))
mt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mt)
mc = mt.mc

API = "https://baiakidle.com/api/trpc/characters.profile"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0"


def busca(nome):
    inp = json.dumps({"0": {"name": nome}}, separators=(",", ":"))
    url = f"{API}?batch=1&input={urllib.parse.quote(inp)}"
    req = urllib.request.Request(url, headers={
        "accept": "*/*", "referer": "https://baiakidle.com/", "user-agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        dados = json.load(r)

    def acha(o, prof=0):
        """o tRPC embrulha a resposta em várias camadas; procura o objeto do personagem"""
        if isinstance(o, dict):
            if "level" in o and "experience" in o and prof > 2:
                return o
            for v in o.values():
                r = acha(v, prof + 1)
                if r:
                    return r
        elif isinstance(o, list):
            for v in o:
                r = acha(v, prof + 1)
                if r:
                    return r
    p = acha(dados)
    if not p:
        raise ValueError("não achei o personagem na resposta da API")
    return p


def milhoes(n):
    """711086131 -> '711.1M' (a tela é estreita, número inteiro não cabe)"""
    n = int(n)
    for div, suf in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "k")):
        if n >= div:
            return f"{n/div:.1f}{suf}"
    return str(n)


def campos(p):
    """Mapeia os dados do personagem nas tags que existem de verdade neste projeto.

    A tela de Clima é a escolhida porque tem seis campos de texto — as outras têm uma
    (Notas) ou duas (WhatsApp). Os nomes das tags são de clima, mas o que aparece na
    tela é o texto que a gente manda.
    """
    sk = p.get("skills") or {}
    return {
        "cidade":      str(p.get("name", "?")),                    # nome, em destaque
        "temp_agora":  f"Lv {p.get('level','?')}",
        "clima2_desc": f"melee {sk.get('melee','-')}",
        "temp_prev1":  f"sh {sk.get('shielding','-')}",
        "clima3_desc": f"exp {milhoes(p.get('experience', 0))}",
        "temp_prev2":  "online" if p.get("online") else "offline",
    }


def envia(tags, dados):
    for tag, valor in dados.items():
        tags.set(tag, valor)


def main():
    ap = argparse.ArgumentParser(description="Baiakidle na Minitela")
    ap.add_argument("personagem")
    ap.add_argument("--loop", type=int, default=0, metavar="SEG",
                    help="atualiza a cada N segundos (0 = uma vez só)")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if mc.app_running() and not args.force:
        sys.exit("o app oficial 'minitela' segura a porta — pare com: pkill -x minitela")

    tags = mt.Tags()
    try:
        while True:
            try:
                p = busca(args.personagem)
                dados = campos(p)
                envia(tags, dados)
                print(f"[{time.strftime('%H:%M:%S')}] " +
                      " | ".join(f"{v}" for v in dados.values()))
            except (urllib.error.URLError, ValueError, TimeoutError) as e:
                print(f"[{time.strftime('%H:%M:%S')}] falha ao buscar: {e}")
            if not args.loop:
                break
            time.sleep(args.loop)
    except KeyboardInterrupt:
        print()
    finally:
        tags.close()


if __name__ == "__main__":
    main()
