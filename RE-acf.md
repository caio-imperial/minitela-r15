# Engenharia reversa do formato Texture.acf (GC9002 / AHMI)

Objetivo: gerar `.acf` nativamente no Linux, sem o compilador Windows do ODM.
Este arquivo é o caderno de laboratório — o que já é fato, o que é hipótese, e o que falta.

Binário analisado: `AHMISimGenDemo_og.exe` (PE32 i386, 3,7 MB), extraído de
`/usr/share/minitela/resources/MiniPanel-0.1.6.AppImage` → `resources/IDE_utils/Gen/`.

PDB deixado no binário: `D:\git\AHMI_SW\AHMI_SW_Graphichina\AHMI_Software\AHMISimGen\Release\AHMISimGenDemo.pdb`
— o fabricante é a **GraphiChina** (docs públicas em https://docs.graphichina.com).

## FATO 1 — o codec de pixel é DXT1/DXT5, não é proprietário

Isto derruba a conclusão anterior de "codec proprietário". As strings do gerador mostram
que ele **terceiriza a compressão** para o `texconv` da Microsoft (DirectXTex):

```
zip32\texconv -f DXT1 -o json          zip64\texconv -f DXT1 -o json
zip32\texconv -f DXT5 -o json          zip64\texconv -f DXT5 -o json
zip32\texconv -f A8R8B8G8 -ft PNG -o json
zip32\texconv -f R8G8B8   -ft BMP -o json
```

E os binários estão lá: `IDE_utils/Gen/zip64/texconv.exe` + `D3DX9_41.dll` + `7z.exe`.

Pipeline do gerador, então:

```
file.zip --7z--> PNGs/GIFs --> frames PNG (pasta json/) --texconv--> DDS DXT1/DXT5
         --> montagem do container --> Texture.acf
```

DXT1 = 8 B por bloco 4x4 (BC1); DXT5 = 16 B (BC3, alpha + BC1). Ambos triviais de
gerar em Python/Rust/C — existem implementações livres. **A parte "difícil" do codec
está resolvida: não precisamos inventar nada.**

A pasta `IDE_utils/Gen/json/` ainda tem os PNGs intermediários do último build do IDE
(inclusive os `*_copy.png`, que são a entrada exata do texconv) — material de teste
pronto para validar um encoder nosso.

## FATO 2 — alinhamento de 16 KB no container

Em `0x40ACE1` (na função que escreve a textura):

```asm
mov 0x8(%edi),%ecx        ; fim do buffer
sub 0x4(%edi),%ecx        ; posição atual = fim - início
and $0x80003fff,%ecx      ; posição % 16384
je  ...                   ; já alinhado? segue
mov $0x4000,%eax          ; 16384
sub %ecx,%eax             ; bytes de padding
loop: push 0; call push_back
```

Ou seja: o buffer é preenchido com zeros até múltiplo de **0x4000 (16 KB)**.
Bate com a medição dos arquivos reais — todo `.acf` tem `tamanho = 8 + N*16384`
(os do pacote levam ainda um bloco extra de 32768, ver FATO 3):

| arquivo | tamanho | payload | payload/16384 |
|---|---|---|---|
| Texture.acf (IDE) | 819208 | 819200 | 50 |
| Texture.acf (pacote) | 851976 | 819200 | 50 (+32768 de cauda) |
| Texture21.acf | 1507336 | 1474560 | 90 (+32768) |

## FATO 3 — estrutura de alto nível do arquivo

```
[0..4)     u32 LE  tamanho do payload
[4..8)     u32     checksum/hash do payload
[8 .. 8+N) payload (seções alinhadas a 16 KB)
[fim]      nos arquivos do pacote: +32768 bytes de config,
           magic 'AHMI' no início e a5 5a 5a a5 nos últimos 4 bytes
```

O `.acf` que sai do IDE **não tem** a cauda de 32 KB (819208 bytes), e é exatamente esse
arquivo que o app do Windows envia (`electron.js`: lê `ideDir/Acf/Texture.acf` e manda
direto). Então a cauda é opcional para o firmware.

Nomes de saída conhecidos do gerador: `Texture.acf`, `Texture_add.acf`, `TextureEven.acf`,
`TextureOdd.acf`, `TextureVideo.acf`, `ConfigData&Texture.acf`, `GIF_0.acf`.

## Endereços úteis no .exe (para retomar)

Seções: `.text` VMA 0x401000 (file 0x400) | `.rdata` VMA 0x52C000 (file 0x12A800)

| o que | endereço |
|---|---|
| "TextureData size is about Equal to: " | ref em `0x40A9DC` |
| **"start writing texture ..."** | ref em `0x40AC59` |
| padding de 16 KB | `0x40ACE1`–`0x40AD22` |
| "start writing add_texture ..." | ref em `0x40B140` |
| "writing ConfigData&Texture.acf file done." | ref em `0x40B53E` |
| "start compress file..." | ref em `0x40B83E` |
| "Texture address over " (erro de estouro) | refs em `0x43C31A`, `0x43CB48`, `0x43CF97`, `0x43DE5E`, `0x46D69A`, `0x46D75B` |

Toda a montagem do arquivo vive em `0x40A900`–`0x40B900`. As funções que *produzem* os
dados de textura (e decidem endereço de cada recurso) estão na faixa `0x43C000`–`0x46E000`,
apontadas pelas referências de "Texture address over".

## FATO 4 — a bancada funcionou: layout da imagem localizado

Wine 8.0 + prefixo **win64** (`~/.wine-mt64`) roda o compilador em ~5,5 s. Detalhes que
custaram tentativa: num prefixo win32 ele procura `zip32\7z.exe` (que não existe no
pacote — só vem `zip64/`), e sem `wine64` instalado o prefixo win64 não sobe.

Com `lab_acf.py`, compilando imagens sintéticas e comparando as saídas:

| experimento | resultado |
|---|---|
| vermelho liso vs azul liso | **uma única região muda: offset 685992, 57600 bytes** |
| marker (bloco 4x4 branco em (0,0) e em (236,236)) vs preto | exatamente **2 grupos**: offsets 0–6 e 57584–57590 |
| quad (4 cores) vs preto | 3600 grupos de 3 bytes, um a cada 16 |
| stripes (60 faixas) vs preto | 3600 grupos de 7 bytes, um a cada 16 |

Disso sai o layout, sem ambiguidade:

- a imagem do slot ocupa **57600 bytes** a partir do offset **685992** do payload;
- são **3600 blocos de 16 bytes**, um por bloco de 4x4 pixels (240/4 = 60; 60x60 = 3600);
- a ordem é **raster simples, sem swizzle**: o bloco (0,0) está no offset 0 e o bloco
  (59,59) no offset 3599x16 = 57584 — foi exatamente o que o marker mostrou.

Bytes de um bloco, por cor de entrada:

```
preto     00 00 00 00 00 00 fe ff 01 00 00 00 00 00 00 00
branco    fe ff ff ff ff ff ff ff 01 00 00 00 00 00 00 00
vermelho  fe ff 01 00 00 00 fe ff 01 00 00 00 00 00 00 00
azul      00 00 00 00 fe ff ff ff 01 00 00 00 00 00 00 00
```

16 B/bloco é o tamanho de DXT5/BC3, e o `texconv -f DXT5` do pipeline corrobora. Mas a
leitura DXT5 canônica (alpha0, alpha1, 6 B de índices de alpha, c0, c1, 4 B de índices)
**não** explica esses bytes: em branco puro, quem muda são os 8 primeiros bytes (o campo
que seria de alpha), enquanto o campo de cor fica `01 00 00 00`. Ou os campos estão em
outra ordem, ou é um bitstream próprio de 128 bits por bloco.

## FATO 5 — o encoding do bloco (RESOLVIDO e validado byte a byte)

Cada bloco de 16 bytes é um **bitstream LSB-first que começa no bit 1**:

| bits | campo |
|---|---|
| 1–8 / 9–16 | R0 / R1 |
| 17–24 / 25–32 | G0 / G1 |
| 33–40 / 41–48 | B0 / B1 |
| 49–56 / 57–64 | A0 / A1 |
| 65–128 | 16 pesos de 4 bits, pixel *i* em `65+4i` (raster dentro do bloco 4x4) |

Cor final: `c = c0 + (c1 - c0) * peso / 15`. Dois endpoints RGBA8888 e um peso por pixel —
a ideia de BC7/ASTC, não o DXT5 canônico (o `texconv -f DXT5` do pipeline é etapa
intermediária, não o formato final; foi o que despistou a análise inicial).

**Detalhe que fecha o formato:** o peso do pixel 15 ocuparia os bits 125–128, e o bit 128
já pertence ao byte do bloco seguinte. O compilador do ODM **nunca usa esse bit** — medido
com pesos forçados (0, 1, 3, 7): o byte seguinte sai sempre `0x00`. Ele orienta os
endpoints (trocando c0 com c1 e invertendo os pesos) para que o último peso caiba em
3 bits. O encoder faz o mesmo.

### Como cada experimento provou

- **níveis de cinza**: os 6 primeiros bytes repetem o tom **deslocado 1 bit à esquerda**
  (8 → `0x10`, 16 → `0x20`, 64 → `0x80`, 192 → `0x180`) — revela o offset de 1 bit e os
  8 bits por canal.
- **cores puras**: vermelho → R0=R1=255, resto 0; azul → B0=B1=255 — prova a ordem
  R0,R1,G0,G1,B0,B1 (pares por canal, não cor0 inteira seguida de cor1).
- **um pixel branco em fundo preto**: endpoints viram (0,0,0) e (255,255,255) e só aquele
  peso vai a 15.
- **posição do pixel**: o peso do pixel *i* acende exatamente os bits `1+4i..4+4i`.
- **transbordo**: o bit 128 é sempre 0; o peso do pixel 15 nunca passa de 7.

### Validação

`acf_codec.py` codifica um bloco de 16 tons de cinza e produz
`fe 01 fe 01 fe 01 fe ff df 9b 57 13 cf 8a 46 02` — **idêntico byte a byte** ao que o
compilador do ODM gera para a mesma entrada. Round-trip sem perda.

Numa foto real (240x240), o encoder nativo dá **PSNR 34,3 dB** e erro médio de 2,64 por
canal, usando só o modo 0 — visualmente indistinguível do original.


## FATO 6 — estrutura do arquivo e checksum (com crédito ao SideCar)

O projeto **SideCar** (github.com/FreyreCorona/SideCar), em Go, ataca a mesma minitela e
resolveu o checksum. Verificado aqui contra 5 arquivos (de fábrica e gerados pelo
compilador do ODM): bate em todos.

```
checksum = XOR de todas as words de 32 bits LE, pulando:
             - o próprio campo (offset 4)
             - a última word do arquivo (FooterMagic 0xA55A5AA5)
Com o checksum correto no lugar, o XOR de TODAS as words == 0xA55A5AA5.
```

O layout do arquivo, na leitura deles (equivalente à minha, vista de outro ângulo — o
campo que eu lia como "tamanho do payload" u32 são os campos magic+count):

```
0x0000  u16  magic         0x0080 texture / 0x0000 config (LE: 0x8000)
0x0002  u16  count         número de blocos de recurso de 64 KB
0x0004  u32  checksum
0x0008  u32  desconhecido
0x000C  24B  projectID     "67004c7703ad6966e4fe0d13"
...
[header 16 KB][count x 64 KB de blocos][dados do projeto]
```

Medido: `Texture.acf` de fábrica tem count=12 (blocos até 802816, sobrando 49160 de
dados de projeto); os `Texture1..21` têm count=27.

**Onde discordamos:** o SideCar trata a imagem como RGB565 cru de 115200 bytes em
`0x4000 + 10*0x10000 + 0x37B0` = 686000. Decodificar o template assim dá ruído, e gravar
RGB565 ali **faz o firmware reiniciar em ciclo** (testado). O README deles diz que o
projeto está em desenvolvimento e o foco é dashboard de métricas — essa parte
provavelmente não foi exercitada.

## FATO 7 — a tela de imagens e a região crítica

O app tem uma tela "Personalizar Imagens" com **três** imagens navegáveis por setas. São
as `resources/gifs_imagens/img{1,2,3}.jpg` do pacote: mascotes Go, símbolo da Positivo e
logo "POSITIVO".

Mapa de gravações feitas no `Texture.acf` de fábrica (offsets no payload):

| região escrita | resultado |
|---|---|
| 685992 – 743592 | ok — logo apareceu com metade suja |
| 714792 – 772392 | ok — régua de cores visível |
| 753192 – 772392 | ok — sujou o rodapé de uma imagem e o topo da seguinte |
| 686000 – 801200 (RGB565) | **firmware reinicia em ciclo** |
| 753192 – 810792 | **firmware reinicia em ciclo** |

Conclusão: existe **região crítica entre 772392 e 801200** — escrever ali derruba o
render. Não é o checksum (os dois casos que quebraram tinham checksum recalculado e
correto; os que funcionaram tinham checksum antigo, e um teste dedicado provou que o
firmware não valida checksum).

E o conteúdo escrito no formato de blocos apareceu como **lixo verde** na tela, não como
a imagem — ou seja, a região das imagens custom **não** usa o formato de blocos do
FATO 5. Provavelmente é onde o SideCar está certo quanto ao formato (pixels crus), só
que no offset errado.

## O que ainda falta

**1. Onde ficam as 3 imagens custom, e em que formato.** É o único bloqueio para a imagem
personalizada. O que se sabe:

- estão nos blocos 10–11 (a escrita em 753192 pegou o fim de uma e o começo da outra);
- **não** usam o formato de blocos do FATO 5 — escrevê-lo ali produz lixo verde na tela;
- há **região crítica entre 772392 e 801200**: escrever ali faz o firmware reiniciar em
  ciclo (recuperável regravando o `Texture.acf` de fábrica).

Correlacionar por luminância com as `img{1,2,3}.jpg` conhecidas não resolveu — as três são
quase todas pretas, então a assinatura não discrimina (erros 11–46, sem pico claro).

Caminho mais promissor: usar a bancada. Compilar o projeto-base com as **três imagens
originais** nos slots e comparar com o `Texture.acf` de fábrica byte a byte. Se as
estruturas casarem, os offsets caem de graça. Hoje elas não casam: o compilado do projeto
intocado dá 868360 bytes contra 851976 do de fábrica (+16384, um bloco de 16 KB), o que
indica que o projeto-base do pacote não é exatamente o de produção, ou que os parâmetros
de compressão usados foram outros.

**2. O modo 1 de bloco** — só necessário para decodificar arquivos oficiais; para gerar,
o modo 0 basta (FATO 5).

## O caminho que funciona (resolvido)

Recompilar o projeto **funciona** — e é a via mais simples, tornando o patch por offset
desnecessário. O que eu vinha errando:

1. usava o `BkpFileZip/file.zip` (um **backup**, com conteúdo diferente) em vez do
   `file.zip` principal do pacote — mesmos nomes de arquivo, tamanhos bem diferentes
   (947 KB contra 2,88 MB; os slots do principal são GIFs de 21, 30 e 44 frames);
2. concluí cedo demais que "o ACF recompilado trava o firmware". Não trava: o compilado
   com as três imagens estáticas nos slots tem **901128 bytes** (count=13, contra 851976 e
   count=12 do de fábrica) e roda perfeitamente. O tamanho maior não é problema.

O travamento do primeiro teste veio da combinação de conteúdo dos slots (uma foto
complexa junto dos GIFs animados grandes), não da estrutura nem do tamanho.

Fluxo validado, implementado em `minitela_build.py`:

```
imagem -> GIF 240x240 de 1 frame (paleta sem dither)
       -> troca o slot no file.zip principal
       -> AHMISimGenDemo_og.exe -f file.zip -m 2 -c 0 -e 0 -d 1 -o ACF/
       -> Texture.acf -> minitela_ctl.py send
```

Os três slots correspondem às três imagens da tela "Personalizar Imagens" do app oficial.

### O que continua em aberto (curiosidade, não bloqueio)

- **Modo 1 de bloco** (`bit0=1`): necessário só para *decodificar* arquivos oficiais; o
  encoder do FATO 5 gera em modo 0 com qualidade excelente.
- **Onde exatamente ficam as 3 imagens** dentro do `.acf` e em que formato: o patch por
  offset chegou a funcionar parcialmente (a régua de calibração localizou a fronteira
  entre duas imagens em 753192), mas ficou obsoleto quando o caminho de recompilar
  funcionou. Fica registrado: há **região crítica entre 772392 e 801200** — escrever ali
  faz o firmware reiniciar em ciclo.

## FATO 8 — a semântica de gravação da NOR (lado firmware da flash)

Análise estática do `flash_download.elf` do pacote GC9002 (o flash algorithm do CDK),
detalhada em [`RE-firmware.md`](./RE-firmware.md). O que muda o entendimento do `.acf`:

- `0x08000000` é `CQSPI_DATA_BASE`; leitura de flash é XIP (loads normais), não comando
  por chunk — `csi_spiflash_read @ 0x020015ba` → `qspi_direct_access_read @ 0x02002762`.
- gravar = **erase de setor (4 KB) + page program**; não existe escrita parcial em NOR,
  então qualquer patch de 1 byte reescreve 4 KB. Isso explica o dano colateral do FATO 7.
- o driver **trunca o endereço de erase em 4 KB** (`addr & 0xFFFFF000`, `0x02001784`) e
  para o laço em `(addr & 0xFFFFF000) <= offset+size`: apagar N bytes apaga
  `ceil(N/4096)` setores inteiros. (Fato neste binário; hipótese para o firmware AHMI,
  que usa o mesmo SDK.)
- **16 KB do container = 4 setores exatos** — o alinhamento do FATO 2 cai certinho na
  granularidade da flash.
- a geometria (setor/bloco/página/opcodes) é lida da **SFDP em runtime**
  (`SFDP_flash_read_parameter @ 0x0200107c`), não de tabela de ID. O binário não diz
  qual é o part; no máximo o byte de capacidade sugere 8 ou 16 MB.
- `flashChecksum @ 0x020008b0` é stub (`return 0`): **nem o caminho de gravação do
  fabricante valida checksum**. Corrobora o FATO 7.

## FATO 9 — as três imagens localizadas, com o mapa do firmware

O `acf_inspect.py` lê o `.acf` com o mapa do código-fonte (`RE-acf-source.md` §3) e
valida o que o firmware valida: `StartOfConfigdata % 16384`, magic `0x494d4841`,
`AHMIInfo.Version == 0x5A010a13` e o `CheckCode` de cada página
(`0xA55A5AA5 ^ XOR(words)`).

**Os 22 `.acf` de fábrica do pacote passam sem um único problema** (11 ou 9 páginas,
94–98 texturas cada). Isso fecha a lacuna de validação que a bancada anterior não tinha:
agora dá para provar que um arquivo gerado é aceitável *antes* de gravar.

### Onde ficam as 3 imagens

São as páginas **4, 5 e 6 (0-based)** — as telas GIF 1/2/3. Cada uma tem duas texturas:

| página | # | tipo | dimensão | endereço (fábrica) | endereço (compilado por nós) |
|---|---|---|---|---|---|
| 4 | 0 | PURECOLOR | 240x240 | `0xff000000` (fundo preto) | `0xff000000` |
| 4 | 1 | STCRGBA888 | fábrica **192x192**, nosso **240x240** | `0x000a77b0` | `0x000a77b0` |
| 5 | 1 | STCRGBA888 | idem | `0x000b07c0` | `0x000b58c0` |
| 6 | 1 | STCRGBA888 | idem | `0x000b97d0` | `0x000c39d0` |

Duas provas de consistência:

- a textura da imagem 1 começa em **`0x000a77b0` nos dois arquivos** — o layout até ali
  é determinístico;
- os tamanhos fecham: `0xA77B0 + 36864 = 0xB07C0` e `0xB07C0 + 36864 = 0xB97D0`
  (fábrica, 192x192 RGBA = 36864 B), e `0xA77B0 + 57600 = 0xB58C0`,
  `0xB58C0 + 57600 = 0xC39D0` (nosso, 240x240 RGBA = 57600 B, com 16 B de alinhamento
  entre fatias).

Consequência: o slot aceita as duas dimensões, e o tamanho de cada fatia é
`ceil(w/4)*ceil(h/4)*16` — o que o `RE-acf-source.md` §2.1 já tinha derivado. A "região
crítica" que travava o render no FATO 7 é a config a partir de `StartOfConfigdata`
(802816 aqui), não a região das imagens.

## FATO 10 — imagem trocada sem o compilador (testado no hardware)

Com a tabela de texturas localizada (FATO 9) e a interpolação correta do codec, dá para
trocar as três imagens **sem recompilar** e **sem wine**:

```
./minitela_patch.py --template <acf que funciona> --out novo.acf foto1.jpg foto2.png --send
```

Por que é seguro: as texturas ficam antes de `StartOfConfigdata`, então nenhum
`CheckCode` de página muda; só o checksum do header (que o firmware não valida) é
recalculado. Verificado por diff: um patch das 3 imagens altera **0 bytes** fora das três
regiões de textura e do campo de checksum.

Codec: a interpolação é `(w + w/8)/16` com saturação (`interpolate()` em
`CS/AHMI/Simulator/stc.cpp`), não `w/15`. O modo 0 (uma partição) gera qualquer bloco;
o compilador do ODM usa modo 1 (duas partições) em blocos de cores não colineares, o que
deixa um resíduo visível nesses blocos — medido em ~1,8/255 de erro médio numa foto.

Testado no hardware em 25/11/2026: imagem "TESTE PATCH" gravada e exibida na tela
Imagens/GIF 1.

## FATO 11 — GIF animado nativo, sem compilador (testado no hardware)

Quadros não são texturas separadas: são **fatias** de um único registro `TextureClass`
(`SingleSliceSize = S`, `SliceFlagsHeaderAddr != 0`, quadro *n* em `TexAddr + n*S`), e o
widget GIF (tipo 34) avança `GifSliceNum` fatias a cada `GifInterval` ticks. O trailer de
fatias fica logo após a última: ponteiros `u32` gravados como u16 alto + u16 baixo, e um
bitmap MSB-first com 1 = fatia opaca. Detalhes e validação da receita em
[`RE-acf-source.md`](./RE-acf-source.md) §7.

Como o arquivo cresce, o `acf_anim.py` remonta a área de textura: reloca tudo depois do
slot, atualiza `TexAddr`/`SliceFlagsHeaderAddr`, `StartOfConfigdata`, `TotalSize`,
`TotalTextureSize`, o campo `@8`, os `CheckCode` das páginas e o checksum do arquivo.

Testado no hardware em 25/11/2026: GIF de 8 quadros (1,31 MB) gravado e **animando** na
tela Imagens, gerado por `minitela_patch.py` sem wine.

Limites práticos: até 96 quadros (tamanho do trailer) e o arquivo tem que caber na
partição de textura (3/7/15 MB conforme a flash; ver FATO 8 e `RE-firmware.md`).
