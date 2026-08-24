#!/usr/bin/env python3
"""
minitela_build.py — coloca imagens suas na Minitela do Positivo Vision R15M.

Fluxo (validado no hardware):

    sua imagem
      -> ffmpeg: GIF 240x240 de 1 frame (crop central, paleta sem dither)
      -> substitui o slot dentro de uma cópia do projeto do IDE (file.zip)
      -> AHMISimGenDemo_og.exe (compilador do ODM, sob wine)
      -> Texture.acf
      -> minitela_ctl.py send

Os três slots são as três imagens da tela "Personalizar Imagens" do app oficial.

Uso:
    ./minitela_build.py setup                          # 1x: monta o workspace
    ./minitela_build.py build foto.jpg                 # troca só a imagem 1
    ./minitela_build.py build a.jpg b.png c.gif        # troca as três
    ./minitela_build.py build foto.jpg --send          # compila e já grava
"""

import argparse
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
WORK = os.path.join(HOME, ".local", "share", "minitela-custom")
WINEPREFIX = os.path.join(HOME, ".wine-mt64")

APPIMAGE = "/usr/share/minitela/resources/MiniPanel-0.1.6.AppImage"
# projeto do IDE: o file.zip PRINCIPAL (o BkpFileZip é um backup com outro conteúdo)
PROJETO = "/usr/share/minitela/resources/ACF/file.zip"
# imagens de fábrica, usadas nos slots que você não trocar
PADRAO = {i: f"/usr/share/minitela/resources/gifs_imagens/img{i}.jpg" for i in (1, 2, 3)}

SLOTS = {
    1: "1i1h1e37393671471.gif",
    2: "1h1k1e37393671464.gif",
    3: "1h1m1e37393671466.gif",
}
SIZE = 240


def run(cmd, **kw):
    print("   $", " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, **kw)


def wine_env():
    env = dict(os.environ)
    env["WINEPREFIX"] = WINEPREFIX
    env.pop("WINEARCH", None)
    env["WINEDEBUG"] = "-all"
    env["WINEDLLOVERRIDES"] = "mscoree,mshtml="
    return env


def ensure_wine():
    if not shutil.which("wine"):
        sys.exit(
            "wine não está instalado (o compilador do ODM é um .exe PE32):\n"
            "  sudo dpkg --add-architecture i386 && sudo apt update\n"
            "  sudo apt install wine wine32:i386 wine64"
        )
    if not os.path.isdir(os.path.join(WINEPREFIX, "drive_c")):
        print(f"   criando prefixo wine em {WINEPREFIX} (só na primeira vez)")
        env = wine_env(); env["WINEARCH"] = "win64"      # win32 procura zip32\\7z.exe, que não existe
        subprocess.run(["wineboot", "-u"], env=env, capture_output=True, timeout=600)


def cmd_setup(args):
    if not os.path.exists(APPIMAGE):
        sys.exit(f"não encontrei {APPIMAGE} — o pacote 'minitela' está instalado?")
    os.makedirs(WORK, exist_ok=True)
    extract = os.path.join(WORK, "appimage")
    if not os.path.isdir(os.path.join(extract, "squashfs-root")):
        os.makedirs(extract, exist_ok=True)
        local = os.path.join(extract, "MiniPanel.AppImage")
        shutil.copy2(APPIMAGE, local)
        os.chmod(local, 0o755)
        r = run([local, "--appimage-extract"], cwd=extract, capture_output=True)
        if r.returncode:
            sys.exit("falha ao extrair o AppImage:\n" + r.stderr.decode(errors="replace")[:1500])

    ide_dst = os.path.join(WORK, "IDE_utils")
    if not os.path.isdir(ide_dst):
        shutil.copytree(os.path.join(extract, "squashfs-root", "resources", "IDE_utils"), ide_dst)
        for root, dirs, files in os.walk(ide_dst):
            for d in dirs:
                os.chmod(os.path.join(root, d), 0o755)
            for f in files:
                os.chmod(os.path.join(root, f), 0o644)
        for exe in ("AHMISimGenDemo_og.exe", "AHMISimGenDemo_gif.exe"):
            p = os.path.join(ide_dst, "Gen", exe)
            if os.path.exists(p):
                os.chmod(p, 0o755)
    os.makedirs(os.path.join(WORK, "out"), exist_ok=True)
    os.makedirs(os.path.join(WORK, "build"), exist_ok=True)

    with zipfile.ZipFile(PROJETO) as z:
        nomes = set(z.namelist())
    print(f"\nworkspace pronto em {WORK}")
    for n, nome in SLOTS.items():
        print(f"   slot {n}: {nome}  {'OK' if nome in nomes else 'AUSENTE'}")
    ensure_wine()
    print("\npronto. agora:  ./minitela_build.py build sua_foto.jpg --send")


def to_gif(src, dst):
    """Qualquer imagem -> GIF 240x240 de 1 frame, cores exatas (sem dither)."""
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg não encontrado")
    vf = (f"scale={SIZE}:{SIZE}:force_original_aspect_ratio=increase,crop={SIZE}:{SIZE},"
          "split[a][b];[a]palettegen=max_colors=256[p];[b][p]paletteuse=dither=none")
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                        "-i", src, "-vf", vf, "-loop", "0", dst], capture_output=True)
    if r.returncode or not os.path.getsize(dst):
        sys.exit("ffmpeg falhou:\n" + r.stderr.decode(errors="replace")[:1000])
    return dst


def cmd_build(args):
    if not os.path.isdir(os.path.join(WORK, "IDE_utils")):
        sys.exit("workspace não montado — rode primeiro: ./minitela_build.py setup")
    ensure_wine()

    build_dir = os.path.join(WORK, "build")
    out_dir = os.path.join(WORK, "out")
    os.makedirs(build_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    # monta os três slots: o que você passou, e as imagens de fábrica no resto
    fontes = {}
    for i in (1, 2, 3):
        fontes[i] = args.imagens[i - 1] if i - 1 < len(args.imagens) else PADRAO[i]
    print("slots:")
    gifs = {}
    for i, src in fontes.items():
        if not os.path.exists(src):
            sys.exit(f"não achei a imagem: {src}")
        gifs[i] = to_gif(src, os.path.join(build_dir, f"slot{i}.gif"))
        marca = "  <- sua imagem" if i - 1 < len(args.imagens) else "  (de fábrica)"
        print(f"   {i}: {os.path.basename(src):<28} {os.path.getsize(gifs[i]):>7} B{marca}")

    proj = os.path.join(build_dir, "file.zip")
    shutil.copy2(PROJETO, proj)
    tmp = proj + ".tmp"
    inv = {v: k for k, v in SLOTS.items()}
    with zipfile.ZipFile(proj) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for it in zin.infolist():
            data = (open(gifs[inv[it.filename]], "rb").read()
                    if it.filename in inv else zin.read(it.filename))
            zout.writestr(it.filename, data)
    os.replace(tmp, proj)

    ide = os.path.join(WORK, "IDE_utils")
    acf_dir = os.path.join(ide, "ACF")
    os.makedirs(acf_dir, exist_ok=True)
    for f in os.listdir(acf_dir):
        if f.endswith(".acf"):
            os.unlink(os.path.join(acf_dir, f))

    print("\ncompilando (compilador do ODM sob wine)…")
    cmd = ["wine", os.path.join(ide, "Gen", "AHMISimGenDemo_og.exe"), "-f", proj,
           "-m", "2", "-c", "0", "-e", "0", "-d", "1" if args.dither else "0", "-o", acf_dir]
    r = subprocess.run(cmd, cwd=os.path.join(ide, "Gen"), input=b"13",
                       env=wine_env(), capture_output=True)
    saida = (r.stdout + r.stderr).decode(errors="replace")
    for linha in saida.splitlines():
        if any(k in linha for k in ("size is about", "successfully", "error", "Totle")):
            print("   |", linha.strip())

    src = os.path.join(acf_dir, "Texture.acf")
    if not os.path.exists(src):
        print(saida[-1500:])
        sys.exit("o compilador não gerou Texture.acf")
    dst = os.path.join(out_dir, "minitela.acf")
    shutil.copy2(src, dst)
    print(f"\npronto: {dst} ({os.path.getsize(dst)} bytes)")

    if args.send:
        ctl = os.path.join(HERE, "minitela_ctl.py")
        print("\nparando o app oficial e gravando…")
        subprocess.run(["pkill", "-x", "minitela"])
        import time; time.sleep(2)
        subprocess.run([ctl, "send", dst, "-y"])
        print("\nreabra o app pelo botão dedicado do teclado (ou pelo menu).")
    else:
        print("\npara gravar:")
        print(f"   pkill -x minitela && ./minitela_ctl.py send '{dst}' -y")


def main():
    p = argparse.ArgumentParser(description="Coloca imagens suas na Minitela do Vision R15M")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup", help="monta o workspace a partir do app instalado").set_defaults(fn=cmd_setup)
    b = sub.add_parser("build", help="gera o .acf com as suas imagens")
    b.add_argument("imagens", nargs="+", help="1 a 3 imagens (as que faltarem ficam as de fábrica)")
    b.add_argument("--send", action="store_true", help="grava na minitela ao terminar")
    b.add_argument("--no-dither", dest="dither", action="store_false")
    b.set_defaults(fn=cmd_build)
    a = p.parse_args()
    if a.cmd == "build" and len(a.imagens) > 3:
        sys.exit("no máximo 3 imagens")
    a.fn(a)


if __name__ == "__main__":
    main()
