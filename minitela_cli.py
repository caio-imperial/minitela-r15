#!/usr/bin/env python3
"""
minitela_cli.py — ponto de entrada único das ferramentas da minitela.

Cada subcomando roda o script correspondente, sem mudar nada neles:

    minitela patch  ...   ->  minitela_patch.py
    minitela gif    ...   ->  minitela_patch.py (mesmo comando; aceita GIF)
    minitela tags   ...   ->  minitela_tags.py
    minitela ctl    ...   ->  minitela_ctl.py
    minitela gui          ->  minitela_gui.py
    minitela inspect ...  ->  acf_inspect.py
    minitela build  ...   ->  minitela_build.py
    minitela recover ...  ->  minitela_recover.py
    minitela doctor       ->  checagem do ambiente
    minitela version      ->  versão

Uso:
    minitela doctor
    minitela patch --template base.acf --out novo.acf foto.jpg --send
    minitela inspect --diagnostico arquivo.acf
"""

import glob
import os
import runpy
import shutil
import sys

VERSAO = "0.1.0"
HERE = os.path.dirname(os.path.abspath(__file__))

SCRIPTS = {
    "patch": "minitela_patch.py",
    "gif": "minitela_patch.py",
    "tags": "minitela_tags.py",
    "ctl": "minitela_ctl.py",
    "gui": "minitela_gui.py",
    "inspect": "acf_inspect.py",
    "build": "minitela_build.py",
    "recover": "minitela_recover.py",
}

AJUDA = """minitela — ferramentas da tela secundária (GC9002, Positivo Vision R15M)

comandos:
  patch     troca imagens/GIF num .acf que já funciona (sem wine); --tela-cheia = 240x240
  gif       o mesmo que patch (aceita GIF animado)
  tags      relógio, bateria, CPU, wifi e notificações (sem tocar na flash)
  ctl       protocolo: send, page, brightness, info, monitor, reboot
  gui       painel gráfico (tkinter)
  inspect   valida e inspeciona um .acf (--diagnostico, --fix, --textures)
  build     compila um .acf do zero com o compilador do ODM (precisa de wine)
  recover   regrava o tema de fábrica quando a tela trava
  doctor    checa o ambiente
  version   mostra a versão

exemplos:
  minitela doctor
  minitela patch --template ~/.local/share/minitela-custom/out/minitela.acf \\
                 --out novo.acf foto.jpg --send
  minitela inspect --diagnostico arquivo.acf
"""


def _roda(script, argv):
    caminho = os.path.join(HERE, script)
    if not os.path.exists(caminho):
        sys.exit(f"nao encontrei {script} ao lado do minitela_cli.py")
    sys.argv = [script] + argv
    runpy.run_path(caminho, run_name="__main__")


def doctor():
    ok = True

    def linha(estado, texto):
        nonlocal ok
        marca = {"ok": "ok  ", "aviso": "!   ", "erro": "X   "}[estado]
        if estado == "erro":
            ok = False
        print(f"  [{marca}] {texto}")

    print("ambiente:")
    v = sys.version_info
    linha("ok" if v >= (3, 10) else "erro", f"python {v.major}.{v.minor}.{v.micro}")

    ff = shutil.which("ffmpeg")
    linha("ok" if ff else "erro", f"ffmpeg: {ff or 'nao encontrado (apt install ffmpeg)'}")
    wine = shutil.which("wine")
    linha("ok" if wine else "aviso", f"wine: {wine or 'ausente (so necessario para build/layout)'}")

    try:
        sys.path.insert(0, HERE)
        import importlib.util
        spec = importlib.util.spec_from_file_location("mc", os.path.join(HERE, "minitela_ctl.py"))
        mc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mc)
        portas = sorted(glob.glob("/dev/ttyACM*"))
        linha("ok" if portas else "aviso",
              "tela: " + (", ".join(portas) if portas else "nenhum /dev/ttyACM* (conectada?)"))
        rodando = mc.app_running()
        linha("aviso" if rodando else "ok",
              "app oficial: " + ("rodando (segura a porta; use pkill -x minitela)"
                                 if rodando else "parado"))
    except Exception as e:                     # noqa: BLE001
        linha("erro", f"nao consegui falar com a tela: {e}")

    pacote = "/usr/share/minitela/resources/ACF"
    linha("ok" if os.path.isdir(pacote) else "aviso",
          f"temas de fabrica: {pacote}" + ("" if os.path.isdir(pacote) else " (pacote minitela instalado?)"))

    template = os.path.expanduser("~/.local/share/minitela-custom/out/minitela.acf")
    linha("ok" if os.path.exists(template) else "aviso",
          "template 240x240: " + (template if os.path.exists(template)
                                  else "ausente (o de fabrica serve; build gera um)"))

    print("\ntudo pronto." if ok else "\nha itens para resolver acima.")
    return 0 if ok else 1


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(AJUDA)
        return 0
    cmd, resto = sys.argv[1], sys.argv[2:]

    if cmd in ("version", "--version", "-V"):
        print(f"minitela {VERSAO}")
        return 0
    if cmd == "doctor":
        return doctor()
    if cmd not in SCRIPTS:
        print(f"comando desconhecido: {cmd}\n")
        print(AJUDA)
        return 2

    _roda(SCRIPTS[cmd], resto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
