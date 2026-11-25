#!/usr/bin/env python3
"""
gerar_vetores.py — vetores dourados do codec para o porte em Rust.

Gera `fixtures/codec.json` com blocos 4x4 determinísticos: os 16 pixels de entrada,
os 16 bytes que o `acf_codec.py` produz e os pixels que ele decodifica de volta.
Sem arquivos do fabricante — só aritmética.

Uso:
    python3 apps/desktop/tests/gerar_vetores.py
"""

import importlib.util
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
SAIDA = os.path.join(HERE, "fixtures", "codec.json")


def carrega(nome):
    spec = importlib.util.spec_from_file_location(nome, os.path.join(RAIZ, f"{nome}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


codec = carrega("acf_codec")

CASOS = {
    "chapado": lambda x, y: (40, 120, 200, 255),
    "gradiente_h": lambda x, y: (x * 17, 0, 255 - x * 17, 255),
    "gradiente_v": lambda x, y: (0, y * 17, 0, 255 - y * 17),
    "borda": lambda x, y: (255, 255, 255, 255) if x < 2 else (0, 0, 0, 255),
    "diagonal": lambda x, y: (x * 30 + y * 10, y * 30, x * 10 + y * 10, 255),
    "cores": lambda x, y: [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)][(x // 2 + y // 2) % 4] + (255,),
    "alfa": lambda x, y: (200, 100, 50, 255 - y * 60),
}


def main():
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    vetores = {}
    for nome, f in CASOS.items():
        px = [list(f(x, y)) for y in range(4) for x in range(4)]     # raster no bloco
        rgb = bytearray()
        for p in px:
            rgb += bytes(p[:3])
        bloco = codec.encode_image(bytes(rgb), 4, 4)
        volta = [list(p) for p in codec.decode_block_at(bloco + b"\x00", codec.block_base(0))]
        vetores[nome] = {
            "pixels": px,
            "bloco_hex": bloco.hex(),
            "decodificado": volta,
        }
    doc = {
        "gerado_por": "apps/desktop/tests/gerar_vetores.py",
        "descricao": "bloco unico 4x4: pixels RGBA de entrada, 16 bytes codificados e "
                     "os pixels que o decodificador do firmware/Python devolve",
        "block_bytes": codec.BLOCK_BYTES,
        "base_bit": codec.BASE_BIT,
        "casos": vetores,
    }
    with open(SAIDA, "w") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"escrito {SAIDA} ({len(vetores)} vetores)")
    for nome, v in vetores.items():
        print(f"  {nome}: {v['bloco_hex']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
