#!/usr/bin/env python3
"""
criar_tela.py — cria uma tela nova no projeto da Minitela, clonando uma existente.

O projeto tem três páginas vazias ("New-page", páginas 8, 9 e 10). Este script copia a
estrutura de uma página que já funciona para uma delas, mantendo layout, fontes e
recursos — o que evita ter que montar canvas e atlas de glifos do zero.

As tags dos widgets são preservadas, então a tela nova mostra o mesmo conteúdo que a
original; o que muda é que você ganha uma página própria, que pode editar depois
(remover ícones, reposicionar canvas) sem mexer na tela original.

Uso:
    ./criar_tela.py --de 4 --para 8 --nome Baiakidle          # gera o projeto
    ./criar_tela.py --de 4 --para 8 --nome Baiakidle --sem-icones
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile

PROJETO = "/usr/share/minitela/resources/ACF/file.zip"
WORK = os.path.expanduser("~/.local/share/minitela-custom")
HERE = os.path.dirname(os.path.abspath(__file__))


def widgets(pagina):
    for c in (pagina.get("canvasList") or []):
        for sc in (c.get("subCanvasList") or []):
            for w in (sc.get("widgetList") or []):
                yield c, sc, w


def main():
    ap = argparse.ArgumentParser(description="Cria uma tela nova clonando outra")
    ap.add_argument("--de", type=int, required=True, help="página de origem (1-based)")
    ap.add_argument("--para", type=int, required=True, help="página de destino (1-based, vazia)")
    ap.add_argument("--nome", required=True)
    ap.add_argument("--sem-icones", action="store_true",
                    help="remove os widgets de imagem (MySlide), deixando só os textos")
    ap.add_argument("--saida", default=os.path.join(WORK, "build", "file.zip"))
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.saida), exist_ok=True)
    shutil.copy2(PROJETO, args.saida)

    with zipfile.ZipFile(args.saida) as z:
        data = json.loads(z.read("data.json"))
        outros = {n: z.read(n) for n in z.namelist() if n != "data.json"}
    # `outros` é mutável de propósito: a clonagem acrescenta os recursos da página nova

    pl = data["pageList"]
    if not (1 <= args.de <= len(pl)) or not (1 <= args.para <= len(pl)):
        sys.exit(f"páginas válidas: 1..{len(pl)}")

    origem = pl[args.de - 1]
    destino = pl[args.para - 1]
    if list(widgets(destino)):
        print(f"aviso: a página {args.para} '{destino.get('name')}' não está vazia — vai ser sobrescrita")

    # clona tudo menos a identidade da página
    novo = json.loads(json.dumps(origem))
    novo["id"] = destino.get("id")
    novo["name"] = args.nome

    # Os ids de canvas/subcanvas/widget são hierárquicos e começam pelo índice da página
    # ("3.0", "3.0.0", "3.0.0.0" na página 4). Clonar sem renumerar deixa o projeto com
    # ids duplicados e a tela sai em branco — o compilador não resolve os recursos.
    pref_de, pref_para = str(args.de - 1), str(args.para - 1)

    def renumera(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "id" and isinstance(v, str) and v.split(".")[0] == pref_de:
                    o[k] = pref_para + v[len(pref_de):]
                else:
                    renumera(v)
        elif isinstance(o, list):
            for v in o:
                renumera(v)

    renumera(novo["canvasList"])

    # Os PNGs de cada página são nomeados por índice: "r-3-0.png", "r-3-1-0-1-0.png"…
    # A página nova precisa dos seus próprios arquivos, senão o compilador não acha nada
    # para desenhar e a tela sai em branco. Copiamos os recursos da origem com o nome da
    # nova página e reapontamos as referências dentro dela.
    copiados = {}
    for nome_arq in list(outros):
        if nome_arq.startswith(f"r-{pref_de}-") or nome_arq == f"r-{pref_de}-0.png":
            novo_nome = f"r-{pref_para}-" + nome_arq[len(f"r-{pref_de}-"):]
            copiados[nome_arq] = novo_nome
            outros[novo_nome] = outros[nome_arq]

    bruto = json.dumps(novo)
    for antigo, atual in copiados.items():
        bruto = bruto.replace(antigo, atual)
    novo = json.loads(bruto)
    print(f"  recursos copiados: {len(copiados)} (r-{pref_de}-* -> r-{pref_para}-*)")

    # Cada canvas tem um refID único no projeto, registrado na lista `refIDs`. Clonar sem
    # trocar deixa dois canvas com o mesmo refID, e a tela nova sai em branco.
    usados = set(str(x) for x in (data.get("refIDs") or []))
    for pag in pl:
        for c in (pag.get("canvasList") or []):
            if c.get("refID") not in (None, ""):
                usados.add(str(c["refID"]))
    proximo, novos_refs = 0, []
    for c in (novo.get("canvasList") or []):
        while str(proximo) in usados:
            proximo += 1
        c["refID"] = str(proximo)
        usados.add(str(proximo))
        novos_refs.append(str(proximo))
    data["refIDs"] = list(data.get("refIDs") or []) + novos_refs
    print(f"  refIDs novos dos canvas: {novos_refs}")

    if args.sem_icones:
        for c in (novo.get("canvasList") or []):
            for sc in (c.get("subCanvasList") or []):
                sc["widgetList"] = [w for w in (sc.get("widgetList") or [])
                                    if w.get("subType") == "MyTextInput"]

    pl[args.para - 1] = novo

    n_widgets = len(list(widgets(novo)))
    tags = sorted({w.get("tag") for _, _, w in widgets(novo) if w.get("tag")})
    print(f"página {args.para} agora é '{args.nome}': {len(novo.get('canvasList') or [])} canvas, "
          f"{n_widgets} widgets")
    print(f"  tags exibidas: {', '.join(tags)}")

    with zipfile.ZipFile(args.saida, "w", zipfile.ZIP_DEFLATED) as z:
        # o compilador é sensível ao formato: indent=4 + ensure_ascii=False reproduz
        # o data.json original byte a byte. Compacto ou com escapes, ele recusa o projeto.
        z.writestr("data.json", json.dumps(data, indent=4, ensure_ascii=False))
        for n, b in outros.items():
            z.writestr(n, b)
    print(f"\nprojeto salvo: {args.saida}")
    print("agora compile e grave:")
    print(f"   ./minitela_build.py build --projeto '{args.saida}' --send")


if __name__ == "__main__":
    main()
