# GIF animado

GIF animado funciona **sem wine** e sem o compilador do fabricante — o mesmo
`minitela_patch.py` da imagem estática dá conta.

```bash
./minitela_patch.py --template ~/.local/share/minitela-custom/out/minitela.acf \
                    --out ~/animado.acf ~/meu.gif --send
```

## Por que o arquivo cresce

O firmware não tem "textura de GIF". Ele tem **fatias**: um único registro de textura com
N quadros de 57.600 B (240×240 RGBA), e o widget GIF avança `GifSliceNum` fatias a cada
`GifInterval` ticks.

```
Texture.acf (cresce N × 57.600 B)
├── cabeçalho
├── texturas estáticas
├── quadro 0 | quadro 1 | ... | quadro N-1   ← as fatias desta textura
├── trailer de fatias (ponteiros + bitmap)
├── demais texturas (relocadas)
└── configuração (páginas, widgets, ações)
```

Por isso o `acf_anim.py` remonta a área de textura: move o que vem depois, corrige os
endereços, o `StartOfConfigdata`, o `TotalSize`, o `TotalTextureSize` e o `CheckCode` de
cada página afetada. Tudo validado antes de gravar.

## Limites

| limite | valor |
|---|---|
| quadros | **96** (tamanho do trailer) |
| tamanho do arquivo | precisa caber na partição de textura: **3, 7 ou 15 MB** conforme a flash |
| quadros por segundo | herdado do `GifInterval` do widget (≈120 ms por padrão) |

!!! warning "Partição de textura"
    Um GIF de 75 quadros dá 5,16 MB e **só cabe** se a flash for de 8 MB ou mais. O
    firmware recusa o download antes de apagar, mas você perde o teste. Para ficar no
    seguro, prefira animações curtas (8–32 quadros).

## Qualidade

Os quadros usam o modo 0 do codec (uma partição por bloco). Em fotos, o erro médio medido
é ~1,8/255, com picos em blocos de cor não colineares — o compilador do fabricante usa o
modo 1 nesses casos, que ainda não implementamos. Em texto e desenhos, a diferença é
imperceptível.

Detalhe técnico completo em
[`RE-acf-source.md`](../RE-acf-source.md#7-gif-animado).

!!! tip "Trocar vários slots"
    Cada execução parte de um template com 1 quadro por slot. Se você animou a imagem 1
    e quer trocar a 2, passe as duas de novo (o GIF e a nova foto) na mesma chamada.
