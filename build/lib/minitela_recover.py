#!/usr/bin/env python3
"""
minitela_recover.py — devolve a minitela a um tema de fábrica.

Para quando uma textura gravada deixa o firmware travado: ele continua enumerando no USB
mas para de responder aos comandos. A flash de textura pode ser reescrita — o bootloader
não foi tocado —, só é preciso pegar o dispositivo numa janela em que ele responda,
normalmente logo depois de o notebook religar (power cycle de verdade).

Uso:
    ./minitela_recover.py                 # fica tentando até conseguir
    ./minitela_recover.py --acf X.acf     # grava outro .acf em vez do tema 21

Deixe rodando e reinicie o notebook: assim que a minitela responder, ele grava.
"""

import argparse
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import importlib.util
spec = importlib.util.spec_from_file_location("mc", os.path.join(HERE, "minitela_ctl.py"))
mc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mc)

PADRAO = "/usr/share/minitela/resources/ACF/Texture21.acf"


def tenta(port, acf, verbose):
    """Uma tentativa de handshake + gravação. True se gravou."""
    try:
        mt = mc.Minitela(port, verbose=verbose)
    except OSError:
        return False
    try:
        pkt = mt.handshake()                     # levanta TimeoutError se estiver mudo
        print(f"\n[{time.strftime('%H:%M:%S')}] respondeu em {port} (maxPacket={pkt}) — gravando…")
        data = open(acf, "rb").read()
        last = [-1]

        def prog(p):
            if p != last[0]:
                last[0] = p
                print(f"\r  [{'#'*(p//4)}{'.'*(25-p//4)}] {p:3d}%", end="", flush=True)

        r = mt.upload(data, "texture", progress=prog)
        print(f"\n  {'já estava gravado' if r == 'ja-gravado' else 'gravado'}: {os.path.basename(acf)}")
        return True
    except (TimeoutError, OSError, RuntimeError):
        return False
    finally:
        mt.close()


def main():
    ap = argparse.ArgumentParser(description="Recupera a minitela gravando um tema de fábrica")
    ap.add_argument("--acf", default=PADRAO)
    ap.add_argument("--timeout", type=int, default=0, help="segundos de tentativa (0 = infinito)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.acf):
        sys.exit(f"não achei {args.acf}")

    # o app oficial disputa a porta; melhor mantê-lo fora enquanto recuperamos
    if subprocess.run(["pgrep", "-x", "minitela"], capture_output=True).stdout.strip():
        subprocess.run(["pkill", "-x", "minitela"])
        print("app 'minitela' pausado durante a recuperação")

    print(f"tentando gravar {os.path.basename(args.acf)}; reinicie o notebook se demorar.")
    print("ctrl-c para parar.\n")
    t0 = time.time()
    n = 0
    while not args.timeout or time.time() - t0 < args.timeout:
        portas = sorted(glob.glob("/dev/ttyACM*"), key=lambda p: os.stat(p).st_mtime, reverse=True)
        for port in portas:
            if tenta(port, args.acf, args.verbose):
                print("\npronto. reabra o app pela lupa/menu (ou):")
                print('  rm -f /tmp/minitela_socket && cd /tmp && D=/usr/share/mini"tela" &&'
                      ' setsid env DISPLAY=:0 GDK_BACKEND=x11 "$D/minitela" &')
                return
        n += 1
        print(f"\r  sem resposta ({n} tentativas, {int(time.time()-t0)}s) — portas: "
              f"{', '.join(os.path.basename(p) for p in portas) or 'nenhuma'}   ", end="", flush=True)
        time.sleep(3)
    print("\ntempo esgotado.")


if __name__ == "__main__":
    main()
