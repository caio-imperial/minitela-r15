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

## O bit de modo não é binário: são cinco sub-formatos

Os bits baixos do bloco escolhem o decodificador (`stc_rgba_dec`, em `stc.cpp:706`).
Não é "modo 0 ou 1" — é o número de bits 1 no começo:

| bits iniciais | sub-formato | implementado aqui |
|---|---|---|
| `0` | uma partição (o que geramos) | **sim** |
| `01` | duas partições | não |
| `011` | duas partições, dois planos | não |
| `0111` | uma partição, dois planos | não |
| `01111…` | três partições | não |

Os sub-formatos de duas/três partições têm mais cabeçalho, um `seed` de 10 bits que escolhe
a partição de cada pixel (`select_partition`), alfa de 6 bits e uma segunda tabela de pesos.

Distribuição medida numa textura real de foto (240×240, 3600 blocos):

| sub-formato | blocos |
|---|---|
| uma partição | 217 |
| uma partição, dois planos | **3197** |
| duas partições | 142 |
| duas partições, dois planos | 16 |
| três partições | 28 |

Consequências:

- **gerar** não precisa de nada disso: o sub-formato de uma partição representa qualquer
  bloco, com menos fidelidade nas cores não colineares;
- **decodificar** arquivos oficiais exige os outros quatro — é a limitação conhecida do
  `acf_codec.py`, e a próxima melhoria do codec.

Um detalhe que ajuda quem for implementar: o deslocamento dos campos é relativo ao **bit 0
do bloco**, enquanto o nosso stream começa no bit 1 — por isso todo offset do `stc.cpp`
entra com `-1` no código.

Prova bit a bit contra o simulador do SDK: [`RE-acf-source.md`](../RE-acf-source.md) §2.

!!! tip "Quem quiser implementar"
    A tarefa está descrita, com fonte, distribuição medida e critério de aceite
    reprodutível, em [#2](https://github.com/caio-imperial/minitela-r15/issues/2).
