# Codec STC

Os pixels das texturas não são RGB cru nem DXT: são **blocos de 16 bytes** que descrevem
4×4 pixels como uma interpolação entre duas cores por canal. O firmware chama isso de STC.

## Bloco (128 bits, LSB-first)

```
bit   0        modo (0 = uma partição, 1 = duas partições)
bits  1–8      R0        bits  9–16   R1
bits 17–24     G0        bits 25–32   G1
bits 33–40     B0        bits 41–48   B1
bits 49–56     A0        bits 57–64   A1
bits 65–124    16 pesos de 4 bits (pixel i em 65+4i, raster no bloco 4x4)
bits 125–128   peso do último pixel — só 3 bits cabem
```

O stream da textura começa no **bit 1** do primeiro byte: o bit 0 do arquivo fica fora dos
blocos, e o último pixel de cada bloco perde o bit mais alto do peso (por isso ele é
limitado a 7, ou os endpoints são invertidos para caber).

## Interpolação (a do firmware)

```
true_w = w + w/8            divisão inteira
cor    = clamp(a0 + (a1 - a0) * true_w / 16)
```

Ou seja: peso 15 → `16/16` = 1.0; peso 8 → `9/16`, e **não** `w/15`. Usar `w/15` dá ~5% de
erro no meio da rampa.

## Tipos (`mTexAttr`, bits 7–4)

| valor | tipo | dados |
|---|---|---|
| `0x00` | STCRGB888 | 16 B/bloco, sem alfa |
| `0x10` | STCRGBA888 | 16 B/bloco, com alfa |
| `0x30` | PURECOLOR | sem dados; `TexAddr` é a cor ARGB |
| `0x80` | PUREMASK | máscara chapada |
| `0x90` | ALPHA2 | — |
| `0x40`/`0x50`/`0xC0`/`0xD0` | RGB565, RGBA8888, ARGB1555, ARGB4444 | outros formatos do chip |

O gerador usa `0x00`/`0x10` para as imagens; fundos chapados aparecem como `0x30`.

## O que implementamos

`acf_codec.py` gera e lê o **modo 0** (`0x10`/RGBA). Decisões que valem registrar:

- escolha de endpoints por eixo dominante e peso por busca exaustiva (16 candidatos)
  minimizando o erro sob a interpolação real;
- se o peso do último pixel passar de 7, os endpoints são **invertidos** (peso `15-w`),
  como o compilador do fabricante — é mais fiel do que truncar;
- texturas de qualquer tamanho múltiplo de 4 (o tamanho da fatia é
  `ceil(w/4)*ceil(h/4)*16`).

Fidelidade medida numa foto real: erro médio **1,8/255**, p99 25. Os piores casos são
blocos de cores não colineares — onde o fabricante usa o **modo 1**.

## Limitação conhecida: modo 1

O modo 1 (duas partições) tem cabeçalho de 5 bits, alfa de 6 bits com correção
(`a += a/64`), pesos de 2 bits por canal mapeados por uma tabela
(`{0,1,2,3} → {0,4,11,15}`) e um bit de tipo escolhendo qual canal usa qual peso.

- **decodificar** arquivos oficiais exige o modo 1;
- **gerar** não: o modo 0 representa qualquer bloco, com menos fidelidade nos casos acima.

Implementar o modo 1 é a próxima melhoria óbvia do codec.

Prova bit a bit contra o simulador do SDK: [`RE-acf-source.md`](../RE-acf-source.md) §2.
