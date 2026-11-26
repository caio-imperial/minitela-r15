#!/usr/bin/env python3
"""
minitela_ctl.py — controle da Minitela do Positivo Vision R15M no Linux.

Fala o protocolo AHMI (chip GC9002, tela 240x240) direto na porta CDC-ACM,
o mesmo que o app oficial (`minitela` + `MiniPanel-0.1.6.AppImage`) usa.

Sem dependências externas: só stdlib (termios/select).

Protocolo (extraído de MiniPanel-0.1.6.AppImage, src/utils/command.js + port.js):

    frame = 'AH' | controlFlag(2,BE) | cmdType(2,BE) | content | crc(2,BE) | 'MI'

    controlFlag = len(cmdType)+len(content), com bit 0x8000 quando há CRC.
    O app oficial envia TUDO com CRC desabilitado (crc = 0x0000) — fazemos igual.

Uso:
    ./minitela_ctl.py info                     # handshake + status (só leitura)
    ./minitela_ctl.py send Texture.acf         # grava .acf na flash de textura
    ./minitela_ctl.py page 5                   # troca a página exibida (1-based;
                                               #   as três imagens são 5, 6 e 7)
    ./minitela_ctl.py brightness 100           # 0-100
    ./minitela_ctl.py monitor                  # dump dos frames recebidos
"""

import argparse
import hashlib
import os
import select
import struct
import sys
import termios
import time

# ---------------------------------------------------------------- protocolo

START = b"AH"
END = b"MI"

CMD = {
    "HANDSHAKE": 0x0080,
    "HANDSHAKE_RESPONSE": 0x00C0,
    "GET_DOWNLOAD_STATUS": 0x0085,
    "GET_DOWNLOAD_STATUS_RESPONSE": 0x00C5,
    "GET_OFFSET": 0x0086,
    "GET_OFFSET_RESPONSE": 0x00C6,
    "REQUEST_DOWNLOAD": 0x0081,
    "REQUEST_DOWNLOAD_RESPONSE": 0x00C1,
    "DOWNLOAD_DATA": 0x0082,
    "DOWNLOAD_DATA_RESPONSE": 0x00C2,
    "DOWNLOAD_COMPLETE": 0x008F,
    "DOWNLOAD_COMPLETE_RESPONSE": 0x00CF,
    # Leitura de flash. Documentado no "GC9002串口升级协议" v0.2 (planilha do fabricante),
    # mas o app oficial nunca usa. O codigo de resposta nao esta na planilha: 0x00C3 e
    # inferido do padrao (0x0080->0x00C0, 0x0081->0x00C1, ...), a confirmar no hardware.
    "UPLOAD_DATA": 0x0083,
    "UPLOAD_DATA_RESPONSE": 0x00C3,
    "SWITCH_STATE": 0x0071,
    "SWITCH_STATE_RESPONSE": 0x00B1,
    "REBOOT": 0x0070,
    "REBOOT_RESPONSE": 0x00B0,
    "SET_REGISTER": 0x0090,
    "SET_REGISTER_RESPONSE": 0x00D0,
}
NAME_OF = {v: k for k, v in CMD.items()}

# Mapa de flash (comentado no electron.js do MiniPanel)
FILE_TYPE_ADDR = {
    "cpu1": 0x08040000,
    "cpu0_config": 0x080F8000,
    "calibration": 0x080FB000,
    "eraseStoreSpace": 0x080FC000,
    "hwconfig": 0x080FE008,
    "product": 0x080FF008,
    "texture": 0x08100000,      # <- é aqui que mora o Texture*.acf
    "texture_gif": 0x08500000,
    "upg_cfg": 0x080F7000,
    "bootloader": 0x08000000,
}

# Endereços que NÃO devem ser tocados por esta ferramenta (risco de brick).
BLOCKED = {"bootloader", "cpu1", "calibration", "hwconfig", "product", "upg_cfg"}

MAX_FILE_BYTES = 6436 * 1024      # limite checado pelo app oficial

# Tags de sistema (tagUtils.js: systemTagNameMap)
SYSTEM_TAG = {
    "page": 2,          # 当前页面序号 — página atual
    "date": 4,
    "time": 5,
    "backlight": 7,     # 背光 — brilho
}


def build_frame(cmd_type: int, content: bytes = b"") -> bytes:
    """Monta um frame AHMI sem CRC (idêntico ao `new Command(type, content, false)`)."""
    data_len = 2 + len(content)
    if data_len > 0x7FFF:
        raise ValueError("conteúdo grande demais para um frame")
    return (
        START
        + struct.pack(">H", data_len)
        + struct.pack(">H", cmd_type)
        + content
        + b"\x00\x00"
        + END
    )


def parse_frames(buf: bytearray):
    """Extrai frames completos de `buf`, consumindo-os. Devolve [(cmd_type, content)]."""
    out = []
    while True:
        i = buf.find(START)
        if i < 0:
            del buf[:]
            break
        if i:
            del buf[:i]
        if len(buf) < 8:
            break
        data_len = struct.unpack(">H", buf[2:4])[0] & 0x7FFF
        total = data_len + 8              # AH(2)+ctrl(2)+data+crc(2)+MI(2)
        if len(buf) < total:
            break
        frame = bytes(buf[:total])
        if frame[-2:] != END:
            del buf[:2]                   # start flag falso: reenquadra
            continue
        cmd_type = struct.unpack(">H", frame[4:6])[0]
        out.append((cmd_type, frame[6 : 6 + data_len - 2]))
        del buf[:total]
    return out


# ------------------------------------------------------------------ serial

class RawSerial:
    """Porta serial em modo raw usando só termios (dispensa pyserial)."""

    BAUDS = {9600: termios.B9600, 115200: termios.B115200, 921600: getattr(termios, "B921600", termios.B115200)}

    def __init__(self, path, baud=115200):
        self.path = path
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        attrs = termios.tcgetattr(self.fd)
        iflag, oflag, cflag, lflag, ispeed, ospeed, cc = attrs
        iflag = termios.IGNPAR
        oflag = 0
        lflag = 0
        cflag = termios.CS8 | termios.CREAD | termios.CLOCAL
        ispeed = ospeed = self.BAUDS.get(baud, termios.B115200)
        cc = list(cc)
        cc[termios.VMIN] = 0
        cc[termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, [iflag, oflag, cflag, lflag, ispeed, ospeed, cc])
        termios.tcflush(self.fd, termios.TCIOFLUSH)
        self.buf = bytearray()

    def write(self, data: bytes):
        view = memoryview(data)
        while view:
            try:
                n = os.write(self.fd, view)
                view = view[n:]
            except BlockingIOError:
                select.select([], [self.fd], [], 1.0)

    def poll(self, timeout=0.2):
        """Lê o que houver e devolve os frames completos disponíveis."""
        r, _, _ = select.select([self.fd], [], [], timeout)
        if r:
            try:
                chunk = os.read(self.fd, 65536)
                if chunk:
                    self.buf.extend(chunk)
            except BlockingIOError:
                pass
        return parse_frames(self.buf)

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass


# ------------------------------------------------------------------ cliente

class Minitela:
    def __init__(self, port, baud=115200, verbose=False):
        self.ser = RawSerial(port, baud)
        self.verbose = verbose

    def close(self):
        self.ser.close()

    def log(self, *a):
        if self.verbose:
            print("   ·", *a, file=sys.stderr)

    def request(self, cmd_type, content=b"", expect=None, timeout=5.0, retries=3):
        """Envia um comando e espera a resposta `expect`, reenviando em caso de timeout."""
        for attempt in range(retries):
            self.ser.write(build_frame(cmd_type, content))
            if expect is None:
                return None
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                for ct, payload in self.ser.poll(0.05):
                    self.log(f"<- {NAME_OF.get(ct, hex(ct))} {payload.hex()}")
                    if ct == expect:
                        return payload
            self.log(f"timeout ({attempt + 1}/{retries}), reenviando {NAME_OF.get(cmd_type, hex(cmd_type))}")
        raise TimeoutError(f"sem resposta {NAME_OF.get(expect, hex(expect))} para {NAME_OF.get(cmd_type, hex(cmd_type))}")

    # --- comandos de leitura -------------------------------------------

    def handshake(self):
        payload = self.request(CMD["HANDSHAKE"], b"", CMD["HANDSHAKE_RESPONSE"], timeout=2.0, retries=5)
        return struct.unpack(">I", payload[:4])[0]      # maxPacketLength

    def download_status(self):
        payload = self.request(CMD["GET_DOWNLOAD_STATUS"], b"", CMD["GET_DOWNLOAD_STATUS_RESPONSE"], timeout=2.0, retries=5)
        return {
            "status": payload[0],
            "file_id": payload[1:17].hex(),
            "offset": struct.unpack(">I", payload[17:21])[0],
        }

    # --- comandos de escrita -------------------------------------------

    def set_num_tags(self, tags):
        """tags: [(reg_id, value)] — no máximo 16 por frame."""
        content = bytearray([(0b1000 << 4) | ((len(tags) - 1) & 0x0F)])
        for reg_id, value in tags:
            content += struct.pack(">HI", reg_id, value & 0xFFFFFFFF)
        return self.request(CMD["SET_REGISTER"], bytes(content), CMD["SET_REGISTER_RESPONSE"], timeout=2.0)

    def show_page(self, page_id):
        return self.set_num_tags([(SYSTEM_TAG["page"], page_id)])

    def read_flash(self, addr, size, chunk=1024, progress=None):
        """Le `size` bytes da flash a partir de `addr` (CMD 0x0083).

        Frame de resposta da planilha do fabricante: Res(4) | Offset(4) | Data(n).
        `Res == 0xFFFFFFFF` significa "processando", a mesma convencao do download.

        TESTADO no hardware em 25/11/2026, duas vezes: com a UI travada (tela
        "Information") e depois de um reboot, com a tela normal. O firmware NAO
        respondeu a 0x0083 em nenhuma das duas, nem com outro codigo de resposta
        (a sonda escutou qualquer frame por 3 s). Conclusao: o comando nao existe
        no firmware de aplicacao da minitela — a planilha documenta o protocolo do
        firmware de upgrade (uartTool/EVB). Para dumpar a flash da minitela ainda
        nao ha caminho conhecido; o codigo fica aqui como referencia.
        """
        out = bytearray()
        while len(out) < size:
            n = min(chunk, size - len(out))
            content = struct.pack(">II", addr + len(out), n)
            payload = self.request(CMD["UPLOAD_DATA"], content,
                                   CMD["UPLOAD_DATA_RESPONSE"], timeout=5.0, retries=3)
            code, off = struct.unpack(">II", payload[:8])
            if code == 0xFFFFFFFF:
                got = None
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and got is None:
                    for ct, p in self.ser.poll(0.1):
                        if ct == CMD["UPLOAD_DATA_RESPONSE"]:
                            got = p
                            break
                if got is None:
                    raise TimeoutError(f"timeout esperando a leitura em {addr + len(out):#010x}")
                payload = got
                code, off = struct.unpack(">II", payload[:8])
            if code != 0:
                raise RuntimeError(f"leitura recusada em {addr + len(out):#010x}: code={code:#x}")
            data = payload[8:]
            if not data:
                raise RuntimeError(f"resposta sem dados (code={code:#x}, offset={off}) "
                                   "— use -v para inspecionar o frame")
            out += data[:n]
            if progress:
                progress(100 * len(out) // size)
        return bytes(out)

    def set_brightness(self, value):
        return self.set_num_tags([(SYSTEM_TAG["backlight"], max(0, min(100, value)))])

    def reboot(self):
        return self.request(CMD["REBOOT"], b"", CMD["REBOOT_RESPONSE"], timeout=3.0, retries=1)

    def upload(self, data: bytes, file_type="texture", progress=None):
        """Grava `data` na região `file_type` da flash, seguindo o fluxo do app oficial."""
        addr = FILE_TYPE_ADDR[file_type]
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"arquivo grande demais: {len(data)} > {MAX_FILE_BYTES}")
        file_id = hashlib.md5(data).hexdigest()

        max_packet = self.handshake()
        self.log(f"handshake ok, maxPacketLength={max_packet}")

        st = self.download_status()
        self.log(f"status=0x{st['status']:02x} fileId={st['file_id']} offset={st['offset']}")
        offset = 0
        if st["status"] in (0x10, 0x11):
            # já em modo download: retoma se for exatamente o mesmo arquivo
            offset = st["offset"] if st["file_id"] == file_id else 0
        elif st["status"] == 0x20:
            if st["file_id"] == file_id:
                if progress:
                    progress(100)
                return "ja-gravado"
            # rodando a UI (AHMI): pede troca para o modo download
            resp = self.request(CMD["SWITCH_STATE"], b"\x10", CMD["SWITCH_STATE_RESPONSE"], timeout=5.0)
            if struct.unpack(">I", resp[:4])[0] != 0:
                raise RuntimeError("falha ao trocar para o modo de download")
        else:
            raise RuntimeError(f"estado de download inesperado: 0x{st['status']:02x}")

        # REQUEST_DOWNLOAD: endereço + tamanho + md5
        content = struct.pack(">II", addr, len(data)) + bytes.fromhex(file_id)
        resp = self.request(CMD["REQUEST_DOWNLOAD"], content, CMD["REQUEST_DOWNLOAD_RESPONSE"], timeout=60.0, retries=1)
        max_page, code = struct.unpack(">II", resp[:8])
        if code == 0xFFFFFFFF:
            # o chip está apagando a flash; espera o segundo C1 com code 0
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                for ct, payload in self.ser.poll(0.1):
                    if ct == CMD["REQUEST_DOWNLOAD_RESPONSE"]:
                        max_page, code = struct.unpack(">II", payload[:8])
                        if code == 0:
                            break
                if code == 0:
                    break
            else:
                raise TimeoutError("timeout apagando a flash (REQUEST_DOWNLOAD)")
        elif code != 0:
            raise RuntimeError(f"REQUEST_DOWNLOAD recusado: code={code:#x}")
        self.log(f"download aceito, maxPageSize={max_page}")

        # DOWNLOAD_DATA em páginas de max_page bytes
        while offset < len(data):
            chunk = data[offset : offset + max_page]
            payload = struct.pack(">I", offset) + chunk
            resp = self.request(CMD["DOWNLOAD_DATA"], payload, CMD["DOWNLOAD_DATA_RESPONSE"], timeout=5.0, retries=5)
            code = struct.unpack(">I", resp[:4])[0]
            if code == 0xFFFFFFFF:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    done = False
                    for ct, p in self.ser.poll(0.1):
                        if ct == CMD["DOWNLOAD_DATA_RESPONSE"] and struct.unpack(">I", p[:4])[0] == 0:
                            done = True
                    if done:
                        break
                else:
                    raise TimeoutError(f"timeout gravando página em offset={offset}")
            elif code != 0:
                continue          # reenvia a mesma página
            offset += len(chunk)
            if progress:
                progress(100 * offset // len(data))

        # DOWNLOAD_COMPLETE (o app oficial ignora erro aqui)
        try:
            self.request(CMD["DOWNLOAD_COMPLETE"], b"", CMD["DOWNLOAD_COMPLETE_RESPONSE"], timeout=5.0, retries=1)
        except TimeoutError:
            pass
        return "ok"


# --------------------------------------------------------------------- CLI

def find_port():
    """A minitela reinicia após cada gravação e re-enumera, então o número do nó
    vai subindo (ttyACM0 -> ttyACM1 -> ...). Pega sempre o mais recente."""
    import glob
    cands = glob.glob("/dev/ttyACM*")
    if not cands:
        return None
    return max(cands, key=lambda p: os.stat(p).st_mtime)


def app_running():
    """A minitela oficial segura a porta; detecta para avisar o usuário."""
    try:
        import subprocess
        out = subprocess.run(["pgrep", "-x", "minitela"], capture_output=True, text=True)
        return bool(out.stdout.strip())
    except Exception:
        return False


def cmd_info(mt, args):
    print(f"maxPacketLength : {mt.handshake()}")
    st = mt.download_status()
    modo = {0x10: "preparando download", 0x11: "em download", 0x20: "rodando a UI (AHMI)"}.get(st["status"], "?")
    print(f"status          : 0x{st['status']:02x} ({modo})")
    print(f"fileId (md5)    : {st['file_id']}")
    print(f"offset          : {st['offset']}")
    for name in ("Texture.acf",) + tuple(f"Texture{i}.acf" for i in range(1, 22)):
        p = f"/usr/share/minitela/resources/ACF/{name}"
        if os.path.exists(p):
            md5 = hashlib.md5(open(p, "rb").read()).hexdigest()
            if md5 == st["file_id"]:
                print(f"gravado agora   : {name}")
                break


def cmd_send(mt, args):
    data = open(args.file, "rb").read()
    if args.pad_to and args.pad_to > len(data):
        # Gravar um .acf menor por cima de um maior deixa o excedente antigo na flash, e o
        # firmware acaba lendo esse lixo como conteúdo (tela suja, e às vezes travamento).
        # O header diz quantos blocos valem; o resto vira zeros.
        falta = args.pad_to - len(data)
        data += b"\x00" * falta
        print(f"padding : +{falta} bytes de zeros (limpa o resíduo até {args.pad_to})")
    if args.type in BLOCKED:
        sys.exit(f"recusado: '{args.type}' é uma região crítica (risco de inutilizar a minitela)")
    print(f"arquivo : {args.file} ({len(data)} bytes, md5 {hashlib.md5(data).hexdigest()})")
    print(f"destino : {args.type} @ {FILE_TYPE_ADDR[args.type]:#010x}")
    if args.dry_run:
        print("dry-run: nada foi enviado.")
        return
    if not args.yes:
        if input("gravar na flash da minitela? [s/N] ").strip().lower() not in ("s", "sim", "y"):
            sys.exit("cancelado")
    t0 = time.monotonic()
    last = [-1]

    def prog(pct):
        if pct != last[0]:
            last[0] = pct
            bar = "#" * (pct // 4) + "." * (25 - pct // 4)
            print(f"\r[{bar}] {pct:3d}%  {time.monotonic() - t0:5.1f}s", end="", flush=True)

    res = mt.upload(data, args.type, progress=prog)
    print(f"\n{'já estava gravado' if res == 'ja-gravado' else 'gravado com sucesso'} em {time.monotonic() - t0:.1f}s")
    if args.page is not None:
        # O firmware reinicia o USB ao terminar o download: o fd antigo morre e o
        # dispositivo volta com outro /dev/ttyACM*. Reabre antes de trocar a pagina.
        time.sleep(4)
        alvo = mt
        for _ in range(20):
            try:
                alvo.show_page(args.page)
                break
            except OSError:
                alvo.close()
                porta = find_port()
                if not porta:
                    time.sleep(0.5)
                    continue
                alvo = Minitela(porta, args.baud, args.verbose)
        else:
            print("aviso: não consegui reabrir a porta para trocar a página")
        print(f"página {args.page} exibida")


def cmd_page(mt, args):
    mt.show_page(args.n)
    print(f"página {args.n}")


def cmd_brightness(mt, args):
    mt.set_brightness(args.n)
    print(f"brilho {args.n}")


def cmd_reboot(mt, args):
    mt.reboot()
    print("reboot enviado")


def cmd_read(mt, args):
    """Le a flash e salva em arquivo. Nao escreve nada no dispositivo."""
    out = args.out or f"dump_{args.addr:08x}.bin"
    t0 = time.monotonic()
    last = [-1]

    def prog(pct):
        if pct == last[0]:
            return
        last[0] = pct
        bar = "#" * (pct // 4) + "." * (25 - pct // 4)
        print(f"\r[{bar}] {pct:3d}%  {time.monotonic() - t0:5.1f}s", end="", flush=True)

    data = mt.read_flash(args.addr, args.size, args.chunk, progress=prog)
    with open(out, "wb") as f:
        f.write(data)
    print(f"\nlido {len(data)} bytes de {args.addr:#010x} -> {out} "
          f"({time.monotonic() - t0:.1f}s, md5 {hashlib.md5(data).hexdigest()})")


def cmd_monitor(mt, args):
    print("escutando (ctrl-c para sair)…")
    while True:
        for ct, payload in mt.ser.poll(0.5):
            print(f"{time.strftime('%H:%M:%S')}  {NAME_OF.get(ct, hex(ct)):<32} {payload.hex()}")


def main():
    p = argparse.ArgumentParser(description="Controle da Minitela do Positivo Vision R15M")
    p.add_argument("--port", default=None, help="porta serial (padrão: autodetecta /dev/ttyACM*)")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--force", action="store_true", help="prossegue mesmo com o app minitela rodando")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="handshake + status (só leitura)").set_defaults(fn=cmd_info)

    s = sub.add_parser("send", help="grava um .acf na flash")
    s.add_argument("file")
    s.add_argument("--type", default="texture", choices=sorted(FILE_TYPE_ADDR))
    s.add_argument("--page", type=int, default=None,
                   help="página a exibir depois de gravar (1-based: imagens em 5, 6, 7)")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("-y", "--yes", action="store_true")
    s.add_argument("--pad-to", type=int, default=0, metavar="BYTES",
                   help="preenche com zeros até esse tamanho, para apagar o resíduo de uma "
                        "gravação anterior maior (o checksum é XOR: zeros não o alteram)")
    s.set_defaults(fn=cmd_send)

    s = sub.add_parser("page", help="troca a página exibida")
    s.add_argument("n", type=int)
    s.set_defaults(fn=cmd_page)

    s = sub.add_parser("brightness", help="ajusta o brilho (0-100)")
    s.add_argument("n", type=int)
    s.set_defaults(fn=cmd_brightness)

    sub.add_parser("reboot", help="reinicia a minitela").set_defaults(fn=cmd_reboot)

    s = sub.add_parser("read", help="le a flash e salva em arquivo (CMD 0x0083, experimental:")
    s.description = ("Le a flash pela planilha oficial do protocolo (CMD 0x0083). "
                     "ATENCAO: o firmware da minitela nao respondeu a este comando no "
                     "hardware; deve existir apenas no firmware de upgrade do EVB.")
    s.add_argument("--addr", required=True, type=lambda x: int(x, 0),
                   help="endereco inicial (ex: 0x08040000)")
    s.add_argument("--size", required=True, type=lambda x: int(x, 0),
                   help="quantidade de bytes (ex: 0x96000 para os 600 KB de cpu1)")
    s.add_argument("--out", default=None, help="arquivo de saida (padrao: dump_<addr>.bin)")
    s.add_argument("--chunk", type=int, default=1024, help="bytes por requisicao (max 1024)")
    s.set_defaults(fn=cmd_read)

    sub.add_parser("monitor", help="dump dos frames recebidos").set_defaults(fn=cmd_monitor)

    args = p.parse_args()
    port = args.port or find_port()
    if not port:
        sys.exit("nenhuma porta /dev/ttyACM* encontrada — a minitela está conectada?")
    if app_running() and not args.force:
        sys.exit(
            "o app oficial 'minitela' está rodando e mantém a porta aberta.\n"
            "  pare com:  pkill -x minitela      (reabre pelo menu depois)\n"
            "  ou passe --force por sua conta e risco."
        )
    mt = Minitela(port, args.baud, args.verbose)
    try:
        args.fn(mt, args)
    except KeyboardInterrupt:
        print()
    finally:
        mt.close()


if __name__ == "__main__":
    main()
