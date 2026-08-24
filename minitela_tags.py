#!/usr/bin/env python3
"""
minitela_tags.py — manda informação em tempo real para a Minitela (relógio, bateria,
clima, notificações, mídia).

Diferente de trocar a imagem, isto **não mexe na flash**: são "tags" (variáveis) que o
firmware já sabe desenhar. Você manda o valor, a tela atualiza na hora. Risco zero.

Formato dos frames (extraído do MiniPanel e conferido contra capturas do app oficial):

    texto:  AH | ctrl | 0090 | 0xD0 | regId(2,BE) | tamanho(2,BE) | UTF-8 | crc | MI
    número: AH | ctrl | 0090 | 0x8N | [regId(2,BE) valor(4,BE)] x (N+1)  | crc | MI

Uso:
    ./minitela_tags.py list                        # tags conhecidas
    ./minitela_tags.py set relogio "23/08 22:02"
    ./minitela_tags.py set bateria 87
    ./minitela_tags.py notify "Fulano" "oi, tudo bem?"
    ./minitela_tags.py daemon                      # relógio + bateria + cpu + wifi
"""

import argparse
import importlib.util
import os
import re
import struct
import subprocess
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("mc", os.path.join(HERE, "minitela_ctl.py"))
mc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mc)

STR_HEADER = 0b11010000

# (id, tipo). Os ids vêm do tagUtils.js do MiniPanel; os marcados com * foram capturados
# dos frames que o app oficial manda de verdade (são tags do projeto, não do SDK).
TAGS = {
    # sistema
    "pagina":        (2, "num"),
    "brilho":        (7, "num"),
    # máquina
    "cpu":           (1080, "num"),
    "gpu":           (1081, "num"),
    "bateria":       (1082, "num"),
    "bateria_tipo":  (1150, "num"),
    "wifi_ssid":     (1083, "str"),
    "wifi_sinal":    (1084, "num"),
    "wifi_status":   (1087, "num"),
    "bt_nome":       (1085, "str"),
    "bt_status":     (1086, "num"),
    # lembretes
    "nota1":         (1090, "str"),
    "nota1_hora":    (1091, "str"),
    "nota2":         (1092, "str"),
    "nota2_hora":    (1093, "str"),
    "nota3":         (1094, "str"),
    "nota3_hora":    (1095, "str"),
    # mídia
    "midia":         (1100, "str"),
    "midia_total":   (1101, "num"),
    "midia_pos":     (1102, "num"),
    "midia_play":    (2003, "num"),
    # notificações (whatsapp)
    "notif1_de":     (1140, "str"),
    "notif1_texto":  (1141, "str"),
    "notif2_de":     (1142, "str"),
    "notif2_texto":  (1143, "str"),
    "notif3_de":     (1144, "str"),
    "notif3_texto":  (1145, "str"),
    # clima (dia 1 = hoje)
    "clima1_tipo":   (1110, "num"),
    "clima1_temp":   (1111, "num"),
    "clima2_tipo":   (1115, "num"),
    "clima2_desc":   (1119, "str"),
    "clima3_tipo":   (1120, "num"),
    "clima3_desc":   (1124, "str"),
    # capturadas do app oficial (*)
    "relogio":       (2006, "str"),   # "23/08 22:02"
    "cidade":        (2027, "str"),   # "Linhares"
    "temp_hoje":     (2030, "str"),   # "19°/26°"
    "temp_amanha":   (2031, "str"),
    "temp_depois":   (2032, "str"),
}


def frame_string(reg_id, texto, encoding="utf-8"):
    dados = texto.encode(encoding, "replace")
    content = struct.pack(">BHH", STR_HEADER, reg_id, len(dados)) + dados
    return mc.build_frame(mc.CMD["SET_REGISTER"], content)


def frame_nums(pares):
    """pares: [(reg_id, valor)] — no máximo 16 por frame."""
    content = bytearray([(0b1000 << 4) | ((len(pares) - 1) & 0x0F)])
    for reg_id, valor in pares:
        content += struct.pack(">HI", reg_id, int(valor) & 0xFFFFFFFF)
    return mc.build_frame(mc.CMD["SET_REGISTER"], bytes(content))


class Tags:
    def __init__(self, port=None, verbose=False):
        port = port or mc.find_port()
        if not port:
            sys.exit("nenhuma porta /dev/ttyACM* — a minitela está conectada?")
        self.ser = mc.RawSerial(port)
        self.verbose = verbose
        self.port = port

    def close(self):
        self.ser.close()

    def _envia(self, frame, esperar=True):
        self.ser.write(frame)
        if not esperar:
            return None
        fim = time.monotonic() + 1.5
        while time.monotonic() < fim:
            for ct, payload in self.ser.poll(0.05):
                if ct == mc.CMD["SET_REGISTER_RESPONSE"]:
                    return payload
        return None

    def set(self, nome, valor):
        if nome not in TAGS:
            sys.exit(f"tag desconhecida: {nome} (veja: ./minitela_tags.py list)")
        reg, tipo = TAGS[nome]
        if tipo == "str":
            r = self._envia(frame_string(reg, str(valor)))
        else:
            r = self._envia(frame_nums([(reg, int(valor))]))
        if self.verbose:
            print(f"   {nome} (reg {reg}) <- {valor!r}  {'ok' if r else 'sem ACK'}")
        return r

    def set_muitos(self, itens):
        """itens: {nome: valor} — agrupa os numéricos num frame só."""
        nums = []
        for nome, valor in itens.items():
            if nome not in TAGS:
                continue
            reg, tipo = TAGS[nome]
            if tipo == "num":
                nums.append((reg, int(valor)))
            else:
                self._envia(frame_string(reg, str(valor)))
        for i in range(0, len(nums), 16):
            self._envia(frame_nums(nums[i:i + 16]))


# ------------------------------------------------------------- coleta (Linux)

def bateria():
    for base in sorted(os.listdir("/sys/class/power_supply")):
        p = f"/sys/class/power_supply/{base}"
        if os.path.exists(f"{p}/capacity"):
            try:
                pct = int(open(f"{p}/capacity").read().strip())
                st = open(f"{p}/status").read().strip() if os.path.exists(f"{p}/status") else ""
                return pct, st
            except (OSError, ValueError):
                pass
    return None, ""


_cpu_ant = None


def cpu_uso():
    """Uso de CPU em % desde a chamada anterior."""
    global _cpu_ant
    try:
        campos = [int(x) for x in open("/proc/stat").readline().split()[1:]]
    except (OSError, ValueError):
        return None
    idle = campos[3] + (campos[4] if len(campos) > 4 else 0)
    total = sum(campos)
    if _cpu_ant is None:
        _cpu_ant = (idle, total)
        return None
    di = idle - _cpu_ant[0]
    dt = total - _cpu_ant[1]
    _cpu_ant = (idle, total)
    return max(0, min(100, round(100 * (dt - di) / dt))) if dt > 0 else None


def wifi():
    """(ssid, qualidade 0-100). Sem dependências além do que o sistema já traz."""
    ssid = None
    try:
        r = subprocess.run(["iwgetid", "-r"], capture_output=True, text=True, timeout=3)
        ssid = r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    qual = None
    try:
        for linha in open("/proc/net/wireless").read().splitlines()[2:]:
            partes = linha.split()
            if len(partes) > 2:
                qual = round(float(partes[2].rstrip(".")) * 100 / 70)
                break
    except (OSError, ValueError, IndexError):
        pass
    return ssid, qual


# --------------------------------------------------------------------- CLI

def cmd_list(t, args):
    print(f"{'tag':<15} {'id':>5}  tipo")
    for nome, (reg, tipo) in sorted(TAGS.items(), key=lambda kv: kv[1][0]):
        print(f"{nome:<15} {reg:>5}  {tipo}")
    print("\nvalores de exemplo: relogio '23/08 22:02' | bateria 87 | cidade 'Linhares'")


def cmd_set(t, args):
    t.set(args.tag, args.valor)
    print(f"{args.tag} = {args.valor!r}")


def cmd_notify(t, args):
    t.set("notif1_de", args.de)
    t.set("notif1_texto", args.texto)
    print(f"notificação enviada: {args.de}: {args.texto}")


def cmd_daemon(t, args):
    print(f"atualizando a cada {args.interval}s (ctrl-c para sair). porta {t.port}")
    cpu_uso()          # primeira leitura só estabelece a base
    while True:
        agora = datetime.now()
        dados = {"relogio": agora.strftime("%d/%m %H:%M")}
        pct, _ = bateria()
        if pct is not None:
            dados["bateria"] = pct
        c = cpu_uso()
        if c is not None:
            dados["cpu"] = c
        ssid, qual = wifi()
        if ssid:
            dados["wifi_ssid"] = ssid
            dados["wifi_status"] = 1
        if qual is not None:
            dados["wifi_sinal"] = qual
        t.set_muitos(dados)
        if args.verbose:
            print(f"  {agora:%H:%M:%S} " + " ".join(f"{k}={v}" for k, v in dados.items()))
        time.sleep(args.interval)


def main():
    p = argparse.ArgumentParser(description="Manda informação em tempo real para a Minitela")
    p.add_argument("--port", default=None)
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--force", action="store_true", help="prossegue mesmo com o app oficial rodando")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="lista as tags conhecidas").set_defaults(fn=cmd_list, precisa_porta=False)
    s = sub.add_parser("set", help="manda um valor para uma tag")
    s.add_argument("tag"); s.add_argument("valor"); s.set_defaults(fn=cmd_set, precisa_porta=True)
    s = sub.add_parser("notify", help="manda uma notificação (remetente + texto)")
    s.add_argument("de"); s.add_argument("texto"); s.set_defaults(fn=cmd_notify, precisa_porta=True)
    s = sub.add_parser("daemon", help="atualiza relógio, bateria, cpu e wifi continuamente")
    s.add_argument("--interval", type=int, default=5); s.set_defaults(fn=cmd_daemon, precisa_porta=True)

    args = p.parse_args()
    if not getattr(args, "precisa_porta", True):
        args.fn(None, args)
        return
    if mc.app_running() and not args.force:
        sys.exit("o app oficial 'minitela' está rodando e segura a porta.\n"
                 "  pare com:  pkill -x minitela\n"
                 "  ou passe --force por sua conta e risco.")
    t = Tags(args.port, args.verbose)
    try:
        args.fn(t, args)
    except KeyboardInterrupt:
        print()
    finally:
        t.close()


if __name__ == "__main__":
    main()
