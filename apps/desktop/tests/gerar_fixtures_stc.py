#!/usr/bin/env python3
"""Gera fixtures/dourados do decodificador STC a partir do simulador do SDK.

O oráculo é o próprio `stc.cpp` do fabricante (`.tools/vendor/.../Simulator`), compilado
com `unsigned __int128` num binário temporário — nada do nosso código entra na resposta.
Só entram os blocos cujo sub-formato já portamos (`0`, `01`, `0111`).

Uso:
    python3 apps/desktop/tests/gerar_fixtures_stc.py
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

RAIZ = pathlib.Path(__file__).resolve().parents[3]
SDK = RAIZ / ".tools/vendor/sdk120/v1.10.20_2025.07.02_GC9002/GC9002/CommonSource/AHMI/Simulator"
ACF = "/usr/share/minitela/resources/ACF/Texture.acf"
SAIDA = pathlib.Path(__file__).parent / "fixtures" / "stc.json"

CABECALHO = """#include <stdio.h>
#include <stdint.h>
#include <string.h>
typedef uint8_t u8; typedef uint16_t u16; typedef int8_t s8; typedef int16_t s16; typedef int16_t sc16;
typedef int32_t s32; typedef uint32_t u32; typedef uint64_t u64;
typedef unsigned __int128 u128;
"""

MAIN = r"""
int main(void) {
    unsigned char b[16];
    if (fread(b, 1, 16, stdin) != 16) return 1;
    u128 bloco = 0;
    for (int i = 0; i < 16; i++) bloco |= (u128)b[i] << (8 * i);
    for (int y = 0; y < 4; y++) {
        for (int x = 0; x < 4; x++) {
            u32 cor = 0;
            stc_rgba_dec(x, y, bloco, &cor);
            printf("%02x%02x%02x ", (cor >> 16) & 0xff, (cor >> 8) & 0xff, cor & 0xff);
        }
        printf("\n");
    }
    return 0;
}
"""


def compila_oraculo(destino: pathlib.Path) -> pathlib.Path:
    h52 = (SDK / "hash52.cpp").read_text().split('#include "stc.h"', 1)[1]
    stc = (SDK / "stc.cpp").read_text().split('#include "stc.h"', 1)[1]
    fonte = destino / "oraculo.cpp"
    fonte.write_text(CABECALHO + h52 + stc + MAIN)
    binario = destino / "oraculo"
    subprocess.run(["g++", "-O2", "-o", str(binario), str(fonte)], check=True)
    return binario


def modo(b0: int) -> str:
    if b0 & 1 == 0:
        return "0"
    if b0 & 3 == 1:
        return "01"
    if b0 & 7 == 3:
        return "011"
    if b0 & 0xF == 7:
        return "0111"
    return "01111"


def main():
    dados = open(ACF, "rb").read()
    sys.path.insert(0, str(RAIZ))
    import acf_inspect

    info, problemas = acf_inspect.parse_bytes(dados, ACF)
    if problemas:
        raise SystemExit(f"o .acf de fábrica não valida: {problemas[0]}")

    blocos = []
    for pg in info["pages"]:
        for t in pg["texs"]:
            if not t["tipo"].startswith("STC") or t["w"] < 200 or t["addr"] >= info["start"]:
                continue
            for i in range(0, t["slice"] // 16):
                ini = t["addr"] + i * 16
                bloco = dados[ini : ini + 16]
                m = modo(bloco[0])
                if m in ("0", "01", "0111"):
                    blocos.append((m, bloco))

    # amostra equilibrada: até 40 de cada modo
    por_modo = {}
    escolhidos = []
    for m, b in blocos:
        if por_modo.get(m, 0) >= 40:
            continue
        por_modo[m] = por_modo.get(m, 0) + 1
        escolhidos.append((m, b))

    with tempfile.TemporaryDirectory() as tmp:
        oraculo = compila_oraculo(pathlib.Path(tmp))
        casos = []
        for m, b in escolhidos:
            saida = subprocess.run([str(oraculo)], input=b, capture_output=True, check=True).stdout
            pixels = []
            for linha in saida.decode().strip().splitlines():
                for v in linha.split():
                    pixels.append([int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)])
            casos.append({"modo": m, "bloco_hex": b.hex(), "pixels": pixels})

    SAIDA.parent.mkdir(exist_ok=True)
    SAIDA.write_text(
        json.dumps(
            {
                "fonte": "stc.cpp do SDK (simulador do fabricante), compilado com __int128",
                "acf": ACF,
                "casos": casos,
            },
            indent=1,
        )
        + "\n"
    )
    print(f"{SAIDA} com {len(casos)} blocos ({por_modo})")


if __name__ == "__main__":
    main()
