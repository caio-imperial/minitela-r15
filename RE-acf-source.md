# Texture.acf visto pelo código-fonte do SDK 1.10.20 (GC9002)

Este arquivo é a leitura do **firmware** (lado device) do formato `.acf`. Complementa
[`RE-acf.md`](./RE-acf.md) (que é a leitura do **compilador** e da bancada) e
[`RE-firmware.md`](./RE-firmware.md) (flash/NOR). Não substitui nenhum dos dois.

Fonte primária (doravante `LIB/` e `CS/`):

| apelido | caminho |
|---|---|
| `LIB/` | `.tools/vendor/sdk120/v1.10.20_2025.07.02_GC9002/GC9002/GC9002/GC9002LIB/` |
| `CS/`  | `.tools/vendor/sdk120/v1.10.20_2025.07.02_GC9002/GC9002/CommonSource/` |
| `EX/`  | `.tools/vendor/sdk120/v1.10.20_2025.07.02_GC9002/U盘_480x272_CTP/Texture.acf` (amostra real, 480x272) |

Todas as afirmações abaixo têm `arquivo:linha`. O que não tem, está marcado
**hipótese** ou **não documentado**. Nada foi executado e nada foi gravado no device:
a única coisa que rodou foi aritmética em Python sobre bytes da amostra `EX/`.

---

## Resumo executivo

1. O firmware **não valida o checksum do arquivo** (campo `+4`). Ele valida três coisas:
   `StartOfConfigdata % 16384 == 0`, `MagicNumber == 0x494d4841` ("AHMI") e
   `AHMIInfo.Version == AHMI_CPU1_VERSION (0x5A010a13)`
   — `CS/AHMI/FileLoad.cpp:570`, `:582`, `:589`.
2. Mas ele **valida um checksum por página**, e isso é o que RE-acf.md não viu:
   `CheckCode == 0xA55A5AA5 ^ XOR(words do bloco da página)` — `CS/Main/AHMIInterface.cpp:1421`
   + `CS/AHMI/validation.cpp:75`. Provado contra as 9 páginas da amostra real.
   O laço de leitura é `do{...}while(checkCode != newPage->CheckCode)` (`:1387`–`:1423`):
   **em caso de divergência ele não sai nunca**. É a explicação mecânica da "região
   crítica" do FATO 7.
3. O "header" do arquivo não é magic+count: é `u32 StartOfConfigdata` seguido de
   `u32 checksum`, `u32 ?`, e uma string de projeto. O "magic 0x8000 / count" do
   FATO 6 é o **mesmo u32 lido como dois u16**. E a "região crítica" de 772392–801200
   (FATO 7) é simplesmente tudo a partir de `StartOfConfigdata` (802816 no `.acf` de
   fábrica), porque ali começa a config que o `CheckCode` cobre.
4. A "tabela de recursos" que faltava existe e é legível: `TextureClass[totalNumOfTexture]`,
   **48 bytes por registro**, dentro do bloco de cada página, com
   `SingleSliceSize`, `TexAddr`, `mTexAttr`, `TexWidth`, `TexHeight`, …
   — `CS/AHMI/TextureClass.h:59`, `CS/AHMI/DynamicPageClass.cpp:180`.
   `SingleSliceSize` em bytes = `ceil(w/4)*ceil(h/4)*16` (conferido em 3 texturas reais).
5. O decodificador de bloco está no fonte, e **confirma o FATO 5**, com uma ressalva:
   aquilo é o modo **STCRGBA888** (`CS/AHMI/Simulator/stc.cpp:629`). Existe um segundo
   modo, **STCRGB888**, com layout diferente (pesos de **5 bits** a partir do bit 49,
   `stc.cpp:723`). O `acf_codec.py` do repo implementa só o primeiro.
6. A interpolação real não é `peso/15`: é `(w + w/8)/16` com saturação (idem `(w+w/16)/32`
   no modo RGB). Diferença de ~5% no meio da rampa.
7. O "1 byte/pixel" cai do próprio formato: 240×240 = 57.600 B = os 57.600 B medidos no
   FATO 4. O slot de imagem do FATO 7 **é** o formato de blocos; "lixo verde" é sintoma de
   escrever o sub-formato errado (hipótese, ver §2.5).

---

## 1. Como o firmware carrega e valida o `Texture.acf`

### 1.1 Onde o arquivo mora na flash

`GC9002` não tem "flash de textura" separada: o `.acf` está **no mesmo QSPI mapeado em
0x08000000** que o código, e é lido por XIP (dereference byte a byte).

| o que | endereço | fonte |
|---|---|---|
| base da região de config | `0x080F0000` | `CS/Main/AHMIInterface.h:77` (`ROM_CONFIG_BASE_ADDR`) |
| `upg_cfg.bin` | `+0x7000` = `0x080F7000` | `LIB/projects/Bootloader/Source/Upgrade/adapt/upgrade_ci.h:116` |
| `CONFIG_START_ADDRESS` | `+0x8000` = `0x080F8000` | `upgrade_ci.h:114` (recebe `cpu0_config.bin`, `upgrade_ci.h:156`) |
| calibração de touch | `+0xB000` | `CS/Main/AHMIInterface.h:95` |
| store tags (u32) | `+0xD000` | `AHMIInterface.h:89` |
| `product.bin` | `+0xF000` | `AHMIInterface.h:83` |
| **início do `.acf`** | `ROM_CONFIG_BASE_ADDR + 0x10000` = **`0x08100000`** | `CS/AHMI/csi_ahmi/csi_ahmi.h:39-40` |
| fim da área de textura | `0x08400000` (3 MB) | `upgrade_ci.h:82` (`TEXTURE_FLASH_MAX_ADDR`) |
| backup do bootloader | `0x083C0000` | `upgrade_ci.h:84-85` |

`TEXTUREFLASH_START_ADDR = TEXTURE_START_ADDR_FOR_GPU = 0x08100000` e
`TEXTURE_ADDR_OFFSET = TEXTUREFLASH_START_ADDR - 0x08000000 = 0x10000`
(`csi_ahmi.h:41`). Consequência prática: **`TexAddr` gravado no `.acf` é offset de
arquivo**, e o endereço que o GPU recebe é `0x08100000 + TexAddr`
(`CS/AHMI/TextureClass.cpp:791`).

Leitura: `csi_ahmi_SeekReadConfigDataAddr(a)` só faz `base = 0x08100000 + a`
(`CS/AHMI/csi_ahmi/csi_ahmi.c:915-922`); `csi_ahmi_ReadConfigData` chama
`csi_hal_extern_flash_read` (`:908`), que em GC9002 é
`gc9002_hal_internal_flash_read` (`CS/csi_hal/csi_hal_driver/csi_hal_driver_flash.c:516`)
— um `for` de leitura de byte em `addr+i` com espera do bit de busy do CQSPI
(`:185-200`). Não há comando de leitura por chunk.

> Nota: `LIB/projects/AHMI_SW/.../GClib/src/texture_flash.c` (o `DRAM_CACHE`/QSPI2/NAND) é
> código de biblioteca multi-chip; no GC9002 o caminho usado é o acima. O
> `ext_flash_gzip_self_adaption()` (`texture_flash.c:366`), que procura "AHMI" em `0x20` e
> em `0x40000`, está **desligado** (`texture_flash.c:137`, comentado).

### 1.2 A sequência exata (`LoadConfigData`, ramo `EMBEDDED`)

`CS/AHMI/FileLoad.cpp:542-608`. Para `CHIP_GC9002` (linhas 546-563):

```
align_size = 16*1024;            // :548
StartOfConfigdata_Pos = 0;       // :549   (GC9002 nunca usa o caso gzip)

csi_ahmi_SeekReadConfigDataAddr(0);           // :562
csi_ahmi_ReadConfigData(&StartOfConfigdata, 4);// :565   -> u32 em offset 0 do arquivo
if (StartOfConfigdata % align_size != 0) erro; // :570-574
csi_ahmi_SeekReadConfigDataAddr(StartOfConfigdata);     // :577
csi_ahmi_ReadConfigData(mConfigInfo, sizeof(ConfigInfoClass)); // :580
if (mConfigInfo->MagicNumber != 0x494d4841) erro;       // :582-586
if (mConfigInfo->AHMIInfo.Version != AHMI_CPU1_VERSION) erro; // :589-593
screenratio = mConfigInfo->screenratio;                 // :596
cfgString = malloc(CfgStringSize);                      // :598
csi_ahmi_ReadConfigData(cfgString, CfgStringSize);       // :600
```

O outro ramo (`#if !defined(CHIP_GC9002)`, linhas 550-560) usa `align_size = 1024` e
`StartOfConfigdata_Pos = 128*1024-4` quando `DRAM_CACHE->Gzip_EN` — formado o
`ConfigData&TextureCMP.acf`. **No GC9002 esse caminho não existe**: `vector` gzip de
arquivo inteiro é coisa de GC9003/GC9005.

### 1.3 O que é validado, e o que não é

| campo | validado? | onde |
|---|---|---|
| `u32 @0` (StartOfConfigdata) múltiplo de 16 KB | **sim** | `FileLoad.cpp:570` |
| `u32 @4` (checksum do arquivo) | **não** — nenhum leitor no SDK consome esse campo. `grep StartOfConfigdata` só acha `FileLoad.cpp` e o bootloader; nada lê `+4` | — |
| `u32 @8` | não lido por ninguém | — |
| string de projeto `@12` | não lida pelo firmware (o bootloader lê versões *dentro* do ConfigInfo, em `StartOfConfigdata+92/+124`) | `upgrade_ci.h:133-135`, `upgrade_c1.c:1232-1273` |
| `MagicNumber` (ConfigInfo+32) | **sim** | `FileLoad.cpp:582` |
| `AHMIInfo.Version` | **sim**, igualdade exata com `AHMI_CPU1_VERSION` | `FileLoad.cpp:589`, `CS/AHMI/Config/AHMICfgDefinition.h:114` |
| `md5_value[32]` (ConfigInfo+0) | **não** — só existe a declaração, `CS/AHMI/DynamicPageCfgClass.h:96`; nenhum uso no código | — |
| **`CheckCode` de cada página** | **sim**, e é fatal | `AHMIInterface.cpp:1421` |

`AHMI_CPU1_VERSION = 0x5A010a13` (`AHMICfgDefinition.h:114`). A amostra `EX/` traz
exatamente `0x5a010a13` em ConfigInfo+260 — ou seja, o `.acf` e o firmware têm que ser
do mesmo build do gerador, senão o aparelho não carrega.

Falha em qualquer um dos três testes → `startAHMI()` entra em
`for(;;) DrawFivePointPage(...)` (`CS/Main/AHMIInterface.cpp:686-732`): a tela dos cinco
pontos vermelhos, para sempre. No GC9002 o `Feed_WDG1()` está dentro de
`#if defined(CHIP_GC9005)` e o `else` faz `i++` duas vezes (`:717-726`) — laço
deliberadamente infinito.

Falha de `CheckCode` é diferente: o `do{}while` de `AHMIInterface.cpp:1387-1423` relê o
mesmo endereço para sempre (a leitura é XIP, o valor nunca muda). CPU1 trava. **Hipótese**
para o "reinicia em ciclo" do FATO 7: o CPU0 (MCU principal) tem watchdog próprio e
reseta o conjunto quando o CPU1 para de responder.

### 1.4 O header, campo por campo

Medido em `EX/` (480×272, 737.288 B) e conferido contra o struct:

| offset | tipo | valor em `EX/` | significado |
|---|---|---|---|
| `+0` | u32 LE | `0x000B0000` = 720896 | `StartOfConfigdata`: offset **a partir do byte 0 do arquivo** até o `ConfigInfoClass`. Múltiplo de 16 KB. |
| `+4` | u32 LE | `0x1D99EAB8` | checksum: `XOR` de **todas** as words de 32 bits do arquivo, exceto ele mesmo e a última word (ver §3.6) |
| `+8` | u32 LE | `0x00054950` = 346448 | **não documentado**. Observação: é exatamente `TotalTextureSize/2` (692896/2) nesta amostra. Não é lido por firmware nem bootloader. |
| `+12` | char[] | `"480x272_demo1753175099001"` | identificação do projeto (texto, terminado em NUL, o resto até 0x4000 é zero) |
| `+0x4000` | — | blocos STC | início da área de textura (offset físico, não tabelado) |
| `StartOfConfigdata` | — | `ConfigInfoClass` | ver §3.2 |
| `EOF-4` | u32 | `0xA55A5AA5` | footer obrigatório (entra no XOR acima) |

Consequência aritmética (bate com o FATO 2): `tamanho_do_arquivo = 8 + k*16384`
(`EX/`: 8 + 45×16384 = 737288). O `+8` é o header; todo o resto é grade de 16 KB.

### 1.5 Como o firmware consome a config depois disso

`InitialAHMIStruct` (`AHMIInterface.cpp`, a partir de ~`:1000`):

- páginas: `NumofPages` registros de `sizeof(DynamicPageCfgClass)` lidos em sequência
  a partir de `StartOfConfigdata + 284 + CfgStringSize`
  (`:1208` dá a posição corrente, `:1223` e `:1356` fazem o seek, `:1489` pula o array);
- o bloco de dados de cada página fica em `StartOfConfigdata + StoreOffset`
  (`:1363`, `DynamicPageClass.cpp:697`) e tem `TotalSize` bytes;
- os `TotalNumOfTexture` registros de textura ficam **dentro** desse bloco (§2.1);
- sons: `mStartAddr` é offset e vira `0x08100000 + mStartAddr` (`:1508-1512`);
- pages com fundo `STCRGBA888` guardam `TexAddr | 0x80000000` no array de fundos
  (`:1458-1470`, o `| 0x80000000` em `:1469`) — o bit 31 é o flag "STC com alpha" (§2.2).

---

## 2. As 3 imagens custom e o formato de pixel

### 2.1 Onde a informação está (a "tabela de recursos")

Cada página tem seu próprio bloco de dados, com layout fixo definido em
`DynamicPageClass::InitPage` (`CS/AHMI/DynamicPageClass.cpp:155-195`):

```
bass + 0                                    CanvasClass        [NumOfCanvas]
     + NumOfCanvas*|Canvas|                 SubCanvasClass     [NumOfSubCanvas]
     + NumOfSubCanvas*|Sub|                 WidgetClass        [NumOfWidget]
     + NumOfWidget*|Widget|                 AnimationKeyFrame  [mNumOfAnimationKeyFrames]
     + mNumOfAnimationKeyFrames*|AKF|       AnimationAction    [mNunOfAnimationActions]
     + ...*|AA|                             u8 actionInstr      [ActionInstructionsSize]
     + ActionInstructionsSize               >>> TextureClass   [totalNumOfTexture]  <<<
     + totalNumOfTexture*48                 touchWidgetRange   [NumofTouchWidget]
     + ...                                  u16 gifWidgetList  [NumofGifWidget]
     + ...                                  u16 pageAction     [NumOfPageAction]
     + ...                                  u16 canvasAction   [NumOfCanvasAction]
```

Citação: `pBasicTextureList = (TextureClass*)(pActionInstructions + mActionInstructionsSize)`
(`DynamicPageClass.cpp:180`). O bloco é **exatamente** `TotalSize` bytes e começa em
`StartOfConfigdata + StoreOffset`.

`TextureClass` (`CS/AHMI/TextureClass.h:59-90`, sem métodos virtuais ⇒ sem vtable,
`sizeof = 48` com `VERSION_2`) — layout observado e confirmado em arquivo real:

| off | tipo | campo |
|---|---|---|
| 0 | u32 | `SingleSliceSize` — bytes de **uma** fatia |
| 4 | u32 | `TexAddr` — offset no `.acf` (se `&0xF0000000 == 0`) |
| 8 | u32 | `SliceFlagsHeaderAddr` — 0 = sem color-slice; ≠0 = tabela de flags |
| 12 | u32 | `mTexAttr` — bits 7-4 = tipo (§2.2), bit 3 mask, 8 `ADDRTEXTURE`, 15 `DRAWING`, … (`drawImmediately_cd.h:222-300`) |
| 16 | u16 | `TexWidth` |
| 18 | u16 | `TexHeight` |
| 20 | u16 | `FocusedSlice` |
| 22-34 | s16×7 | `OffsetX/Y`, `RotateAngle`, `ShearAngleX/Y`, `ShearAngleZX/ZY` |
| 36,38 | s16 | `ScalerX/Y` (1.9 fixo: 512 = 1.0) |
| 40-43 | s8×4 | `TexLeft/Top/Right/ButtomTileBox` |
| 44 | u8 | `staticTexture` (fatias por bloco de 16 KB; 0 = sem entrelaçamento) |
| 45 | u8 | `useCanvasPoint` |
| 46-47 | — | padding |

Receita para achar a tabela sem conhecer `|Widget|`: quando `NumofTouchWidget`,
`NumofGifWidget`, `NumOfPageAction` e `NumOfCanvasAction` são 0 (caso comum),
`início_da_tabela = TotalSize - totalNumOfTexture*48`.

**Verificado** na página 6 da amostra `EX/` (`StoreOffset=4480`, `TotalSize=3252`,
`totalNumOfTexture=12` → tabela em `3252-576 = 2676`):

| # | SingleSliceSize | TexAddr | attr | tipo | W×H | conferência |
|---|---|---|---|---|---|---|
| 0 | 0 | `0xFFFFFFFF` | `0x00000130` | 3 = PURECOLOR | 480×272 | fundo chapado |
| 1 | 2912 | `0x000A53C0` | `0x00000110` | 1 = STCRGBA888 | 104×26 | 26×7×16 = **2912** ✓ |
| 2 | 16 | `0x000A6A80` | `0x00000110` | 1 | 4×4 | 1×1×16 = **16** ✓ |
| 11 | 13312 | `0x000A6AA0` | `0x00000110` | 1 | 254×51 | 64×13×16 = **13312** ✓ |

Isso prova duas coisas de uma vez: o tamanho de uma textura é
`ceil(w/4)*ceil(h/4)*16`, e texturas **não** são alinhadas a 16 KB entre si
(`0xA53C0 % 0x4000 = 5056`). Só o container e o `StartOfConfigdata` são.

### 2.2 O codec: "STC", 16 B por bloco 4×4, dois sub-formatos

Os tipos no GC9002 (`CS/AHMI/drawImmediately_cd.h:222-249`, ramo `CHIP_GC9002`):

```
STCRGB888   0x00     <- blocos de 16 B, SEM alpha
STCRGBA888  0x10     <- blocos de 16 B, COM alpha
ALPHA1 0x20  PURECOLOR 0x30  RGB565 0x40  RGBA8888 0x50  Y8 0x60
RGB565_RE 0x70  PUREMASK 0x80  ALPHA2 0x90  ALPHA8 0xa0  ALPHA4 0xb0
ARGB1555 0xc0  ARGB4444 0xd0  SFBC 0xe0  RGBA8888_RE 0xf0
```

No GC9002 `0x00`/`0x10` são **STC**, não DXT1/DXT5: no simulador de GPU
`ahmi::cache()` o `SIM_DXT1` (código 0) do GC9003 é trocado por
`stc_rgb_dec()` quando `embedded_platform != EMBEDDED_GC9003`
(`CS/AHMI/Simulator/ahmiv3.cpp:825-875`, chamada em `:872`). O tipo que o hardware
recebe é `TexType = (texture_ctrl & 0x1e) >> 1` (`ahmiv3.cpp:1257`).

Os decodificadores:

| função | arquivo:linha | quando |
|---|---|---|
| `stc_rgba_dec` | `stc.cpp:706-721` | tipo `0x10` (STCRGBA888) |
| `stc_rgb_dec` | `stc.cpp:1189-1201` | tipo `0x00` (STCRGB888) |
| `stc_rgba_one_partition_dec` | `stc.cpp:629-658` | **é o FATO 5** |
| `stc_rgb_one_partition_dec` | `stc.cpp:723-747` | modo 0 do RGB, layout diferente |

O bit 0 escolhe a partição (`stc.cpp:1190-1201`):

```
bit0 == 0        -> one partition          (o "modo 0" do RE-acf.md)
& 0x3 == 0x1     -> two partition          (RGBA) / two plane two partition (RGB)
& 0x7 == 0x3     -> two plane two partition (RGBA) / two partition (RGB)
& 0xf == 0x7     -> two plane one partition
senão            -> three partition
```

### 2.3 Layout de bits — confirmação e correção do FATO 5

**`stc_rgba_one_partition_dec`** (`stc.cpp:629-658`) — bitstream LSB-first:

| bits | campo |
|---|---|
| 0 | flag de partição (0 = one partition) |
| 1-8 / 9-16 | R0 / R1 |
| 17-24 / 25-32 | G0 / G1 |
| 33-40 / 41-48 | B0 / B1 |
| 49-56 / 57-64 | **A0 / A1** |
| 65+4i (i=0..15) | peso de 4 bits do pixel i (o 16º só tem 3 bits reais — ver abaixo) |

Interpolação (`stc.cpp:2-9`):
`tw = w + w/8;  c = clamp(a0 + (a1-a0)*tw/16)`.

**`stc_rgb_one_partition_dec`** (`stc.cpp:723-747`) — sem alpha, pesos de 5 bits:

| bits | campo |
|---|---|
| 0 | flag de partição |
| 1-8 / 9-16 | R0 / R1 |
| 17-24 / 25-32 | G0 / G1 |
| 33-40 / 41-48 | B0 / B1 |
| **49+5i** (i=0..15) | peso de **5 bits**; `w' = w + w/16; c = clamp(a0 + (a1-a0)*w'/32)` (`stc.cpp:11-18`) |

Orçamento de bits — e é aqui que o FATO 5 acertou em cheio:

- **RGBA**: o 16º peso começa no bit 125 e só tem **3 bits reais** (125, 126, 127; o bit
  128 não existe no `u128`, então `weight_table>>60` entrega 3 bits + zero). Peso máximo
  do pixel 15 = **7**. É exatamente o "o peso do pixel 15 nunca passa de 7" medido.
- **RGB**: 49 + 16×5 = 129 > 128 — o 16º peso começa em 124 e tem **4 bits** (0..15 de
  uma faixa 0..31), não 3.

`y*4+x` é a ordem raster dentro do bloco (`stc.cpp:739`, `:649`).

**Prova de que o FATO 5 é o modo RGBA**: o bloco que o compilador do ODM gerou para
16 tons de cinza — `fe 01 fe 01 fe 01 fe ff df 9b 57 13 cf 8a 46 02` (FATO 5) —
decodificado com `stc_rgba_one_partition_dec` dá pesos `15,14,13,…,0` e
R = `0,15,31,47,63,79,95,111,143,159,175,191,207,223,239,255` (rampa monotônica).
Decodificado com o modo RGB (5 bits no bit 49) dá lixo
(pesos `31,31,31,31,30,6,15,21,9,28,25,10,20,17,4,0`).

**Correção ao FATO 5** (única diferença real): a fórmula não é `c0 + (c1-c0)*w/15`
mas `c0 + (c1-c0)*(w + w/8)/16`. Para w=15 o fator é 135/128 (satura); para w=7 é
63/128 = 0,492, contra 7/15 = 0,467 — ~5% de erro no meio da rampa. Um encoder que
queira bater a imagem tem que inverter a função real, não `w/15`.
**Hipótese** (não provada em silício): `interpolate()` é o modelo de referência de uma
tabela de hardware; se o ASIC fizer exatamente `w/15`, o gerador é que estaria
"errado". Os 16 níveis do teste acima são compatíveis com as duas leituras, então a
única forma de decidir é medir luminância na tela ou achar a LUT no RTL.

### 2.4 `SingleSliceSize`, fatias e o 16 KB

`TextureClass.cpp:785-793` calcula o deslocamento da fatia:

```
if (staticTexture == 0)
    addr = FocusedSlice * SingleSliceSize;
else
    addr = 0x4000*(FocusedSlice/staticTexture) + (FocusedSlice%staticTexture)*SingleSliceSize;
TexAddr_final = TexAddr + addr + TEXTURE_ADDR_OFFSET;   // se (TexAddr & 0xF0000000)==0
```

`staticTexture` = "quantas fatias cabem em um bloco de 16 KB" — é o único lugar em que
o 16 KB aparece *dentro* da textura. `img_align()` (`TextureClass.cpp:80-172`) é a
contraparte no gerador: escolhe a largura da fatia para que
`(w+3)/4*4 * (h+3)/4*4 <= 16*1024 - 64` — os 64 bytes são cabeçalho de fatia
(relacionado a `SliceFlagsHeaderAddr`). Para uma textura "normal" (não animada),
`SingleSliceSize` é o tamanho da imagem inteira e `staticTexture = 0`, como se vê nos
12 registros da página 6 da amostra.

### 2.5 Onde estão as 3 imagens custom — o que dá para afirmar

**Fato aritmético**: uma imagem 240×240 em STC ocupa `60×60×16 = 57.600` bytes = 1 B/px.
É *exatamente* a região de 57.600 B em 685992 que o FATO 4 mediu. Portanto o slot de
imagem do FATO 4 **é** o formato de blocos, e a conclusão do FATO 7 ("a região das
imagens custom **não** usa o formato de blocos") está **contradizida** por aritmética
e pelo fonte.

**O que continua não documentado**: os offsets exatos dos 3 slots no `Texture.acf` de
fábrica 240×240 — esse arquivo não está no repo nem no pacote do SDK, então não deu para
ler a tabela. O procedimento para obtê-los em 5 linhas de Python está em §5; ele não
depende do compilador do ODM.

**Hipóteses para o "lixo verde" do FATO 7** (as duas explicam o mesmo sintoma):

1. sub-formato trocado: escrever blocos no layout RGBA (pesos de 4 bits no bit 65) numa
   textura cujo registro diz tipo `0x00` (RGB, pesos de 5 bits no bit 49) — ou vice-versa.
   Como 1 byte/px é o mesmo, o tamanho bate e o resultado é ruído colorido;
2. widget do tipo GIF: o firmware trata widgets de `pGifWidgetList` à parte
   (`AHMIInterface.cpp:400-450`), e nesse caso o dado não é a textura crua e sim um
   bloco comprimido com LUT: `u32@bloco` com `lutSize = valor>>12` (KB), em
   `bloco + lutSize*1024` a string `"AHMI"` e, logo depois, os primeiros 32 B comprimidos
   que `decompress_first256bytes()` expande para o `BlockHeader` de 28 B
   (nome "GIF", w, h, textType, texaddr, singlesliceSize, picnum, delay, res)
   — `CS/gziplib/gzipBlock.cpp:39-91`, `gzipBlock.h:26-38`, `gzip.cpp:1272-1289`.
   Cada frame começa em `0x20 + n*SinglesliceSize`
   (`AHMIInterface.cpp:435`, `:439-443`). Escrever STC cru no início do bloco estraga
   o header comprimido → lixo.

Para decidir, basta ler o registro de textura do widget correspondente: se `attr>>4`
for `0x1`/`0x0` é textura crua; se o widget estiver em `pGifWidgetList`, é bloco LUT.

### 2.6 O compressor (o que o fonte **não** tem)

Não existe encoder STC no SDK: `grep -rn "stc_.*enc\|STC_ENC"` em `CommonSource/` não
retorna nada. O SDK entrega o **decodificador** (simulador de GPU) e o **container**; a
compressão continua sendo o que o `acf_codec.py` já faz. Bom para o repo: a codificação
do FATO 5 é o lado que não precisa mais ser descoberto.

---

## 3. Estrutura exata do container de recursos

### 3.1 Visão geral

```
[0x0000]  u32  StartOfConfigdata     múltiplo de 0x4000
[0x0004]  u32  checksum_arquivo
[0x0008]  u32  ?                     (= TotalTextureSize/2 na amostra)
[0x000C]  char projectID[]           NUL-terminado, zero-padded até 0x4000
[0x4000]  ...  dados de textura STC  (endereçados por TexAddr de cada registro)
[StartOfConfigdata]                ConfigInfoClass (284 B)
[+284]                             cfgString (CfgStringSize B)
[+284+CfgStringSize]               DynamicPageCfgClass[NumofPages]  (56 B cada)
[+...]                             WaveFilter[], WaveFilterStatus[], Sound[],
                                   TagClassCfg + links[], strings, arrays, fontes,
                                   hints, initString, tagValueSpace
[StartOfConfigdata+StoreOffset_i]  bloco de dados da página i (TotalSize_i B)
[EOF-4]   u32  0xA55A5AA5
```

Conferido na amostra `EX/`: `TotalSize` (ConfigInfo+36) = 737.280 = tamanho do arquivo
menos 8; `StartOfConfigdata` = 720.896; área de config = 16.392 B (16 KB + os 8 do
header); a cadeia `StoreOffset` das 9 páginas fecha (`2392, 2740, …, 7784` com
`TotalSize` 348 e a última de 52), e `DynamicPageSize` = 3252 = `TotalSize` da maior
página.

### 3.2 `ConfigInfoClass` (`CS/AHMI/DynamicPageCfgClass.h:93-145`, 284 bytes)

Offsets verificados campo a campo contra `EX/`:

| off | campo | valor em `EX/` |
|---|---|---|
| 0 | `u8 md5_value[32]` | `"8c20d72d…765084"` (não é validado por ninguém) |
| 32 | `u32 MagicNumber` | `0x494d4841` |
| 36 | `u32 TotalSize` | 737280 (= tamanho do arquivo − 8) |
| 40 | `u32 TotalTextureSize` | 692896 |
| 44 | `u32 DynamicPageSize` | 3252 |
| 48 | `u16 NumofTimers` | 0 |
| 50 | `u16 NumofUartBuf` | 1 |
| 52 | `u16 NumofWidget` | 100 |
| 54 | `u16 NumOfWaveFilter` | 0 |
| 56 | `u16 NumOfWaveFilterStatus` | 0 |
| 58 | `u16 NumofTags` | 34 |
| 60 | `u16 NumofTagUpdateQueue` | 30 |
| 62 | `u16 TagValueTotalSize` | 596 |
| 64 | `u8 NumofSound` | 0 |
| 66 | `u16 NumofSysPage` | 3 |
| 68 | `u16 StringSize` | 0 |
| 70 | `u16 PageSwipeMode` | 0 |
| 72 | `u16 CfgStringSize` | 100 |
| 74 | `u16 NumofPages` | 9 |
| 76 | `s16 screenratio` | 512 (=1,0 em 1.9) |
| 78 | `u16 encoding` | 0 |
| 80 | `u32 audioAttr` | 16000 |
| 84 | `u8 AHMIScene` | 0 |
| 86 | `u16 serialBaudRate` | 0 |
| 88 | `u16 NumofStrings` | 0 |
| 90 | `u16 NumOfHints` | 0 |
| 92 | `u8 YTHVersion[32]` | `"1.10.20_build_2025.07.02.10.45"` |
| 124 | `u8 IDEVersion[32]` | `"1.10.20_build_2025.7.9.11.28"` |
| 156 | `u8 CPU0Version[32]` | `"CPU0VERSION"` (placeholder) |
| 188 | `u8 CPU1Version[32]` | `"1.10.20_build_2025.07.02.10.45"` |
| 220 | `u8 DeviceID[32]` | `"CPU0DEVICEID"` (placeholder) |
| 252 | `u16 NumofArrayDatas` | 0 |
| 254 | `u16 NumOfFontRanges` | 0 |
| 256 | `u16 NumOfFont` | 1 |
| 258 | `u8 NumOfKBStates` | 0 |
| 259 | `u8 NumOfMenuStates` | 0 |
| 260 | `u32 AHMIInfo.Version` | **`0x5A010a13`** |
| 264 | `u16 AHMIInfo.ScreenWidth` | 480 |
| 266 | `u16 AHMIInfo.ScreenHeight` | 272 |
| 268 | `u16 AHMIInfo.ColorSpace` | 16 |
| 270 | `u16 AHMIInfo.TileSize` | 32 |
| 272 | `ProjectScreenOptions` (4×u16 + u8 `enable`) | 0,0,0,0,0 |

Confirmação cruzada: o bootloader lê `YTHVersion` em `TEXTURE_START_ADDRESS+92` e
`IDEVersion` em `+124` (`upgrade_ci.h:133-134`, `upgrade_c1.c:1247-1266`), com
`offset = *(u32*)TEXTURE_START_ADDRESS` somado — isto é, **dentro do
`StartOfConfigdata`**. Bate com a tabela acima.

**Divergência anotada**: `DEVICE_ID_STORE_ADDR = TEXTURE_START_ADDRESS + 284`
(`upgrade_ci.h:135`) aponta para o *fim* do struct, mas `DeviceID` está em `+220`
nesta versão. O bootloader dessa mesma SDK provavelmente está defasado nessa constante
(ou o struct do gerador tem 8 bytes a mais entre `IDEVersion` e `DeviceID`). Não é
relevante para o `.acf` em si, mas é armadilha para quem for ler versão de device.

### 3.3 `DynamicPageCfgClass` (56 bytes) — `DynamicPageCfgClass.h:43-75`

| off | campo |
|---|---|
| 0 | `u32 StoreOffset` (relativo a `StartOfConfigdata`) |
| 4 | `u32 TotalSize` |
| 8 | `u32 CheckCode` |
| 12 | `u16 PageAttr` |
| 14 | `u16 totalNumOfTexture` |
| 16 | `u16 ActionInstructionsSize` |
| 18 | `u16 NumOfPageAction` |
| 20 | `u16 NumOfCanvasAction` |
| 22 | `u16 NumOfWidget` |
| 24 | `u16 NumofTouchWidget` |
| 26 | `u16 NumofGifWidget` |
| 28 | `u16 pageAnimationDuration` |
| 30 | `u16 pageReleasingAnimationDuration` |
| 32 | `u16 NumOfCanvas` |
| 34 | `u16 NumOfSubCanvas` |
| 36 | `u8 AnimationType` |
| 37 | `u8 enlightedWidgetID` |
| 38 | `u8 mStartOfStack` |
| 39 | `u8 mNumOfPara` |
| 40 | `u8 timingFun` |
| 42 | `u16 mNumOfAnimationKeyFrames` |
| 44 | `u8 mNunOfAnimationActions` |
| 45 | `u8 VideoType` |
| 46 | `PageScreenOptions` (4×s16) |

### 3.4 Os dois checksums (um ignorado, um fatal)

**(a) checksum do arquivo, `u32 @4`** — não é validado por ninguém, mas existe e é
fácil de gerar:

```
checksum = XOR de todos os u32 LE do arquivo,
           exceto a word em +4 e a última word (footer 0xA55A5AA5)
<=> (XOR de todas as words, incluindo o campo e o footer) == 0xA55A5AA5
```

Verificado em `EX/`: `XOR(todas) = 0xA55A5AA5`; `XOR(sem +4, sem footer) = 0x1D99EAB8`
= valor gravado. (As duas formulações do FATO 6 são equivalentes, porque o footer entra
no XOR do "tudo".)

**(b) `CheckCode` de página** — é o `XORCheck` de verdade
(`CS/AHMI/validation.cpp:75-86`):

```c
u32 XORCheck(u32 *data, u32 datalen) {
    u32 checkCode = 0xA55A5AA5;
    for (i=0; i<datalen; i++) checkCode ^= data[i];
    return checkCode;
}
// chamado com: XORCheck((u32*)PageSpace, TotalSize/4)
```

i.e. `CheckCode = 0xA55A5AA5 ^ XOR(words do bloco, TotalSize/4)`, sobre os
`TotalSize` bytes do bloco da página, em `StartOfConfigdata+StoreOffset`.
`TotalSize % 4 == 0` em todas as páginas observadas.

**Provado contra arquivo real** — as 9 páginas da amostra `EX/`:

| página | TotalSize | `CheckCode` gravado | `0xA55A5AA5 ^ XOR(words)` | ok |
|---|---|---|---|---|
| 0 | 348 | `0xAC5302AC` | `0xAC5302AC` | ✓ |
| 1 | 348 | `0xAC517CAC` | `0xAC517CAC` | ✓ |
| 2 | 348 | `0xAC577EAC` | `0xAC577EAC` | ✓ |
| 3 | 348 | `0xAC5578AC` | `0xAC5578AC` | ✓ |
| 4 | 348 | `0xAC5B7AAC` | `0xAC5B7AAC` | ✓ |
| 5 | 348 | `0x50498A88` | `0x50498A88` | ✓ |
| 6 | 3252 | `0xACC52E20` | `0xACC52E20` | ✓ |
| 7 | 52 | `0x51BAA78A` | `0x51BAA78A` | ✓ |
| 8 | 52 | `0x51BAA78A` | `0x51BAA78A` | ✓ |

O mesmo se aplica ao `ConfigData&Texture.acf` (caminho `PC_SIM`, `FileLoad.cpp:149`) e
às recargas de página em RAM (`DynamicPageClass.cpp:272, 394, 734, 1002, 1090`).

### 3.5 Armadilha: existem dois "AHMI"

| constante | valor u32 | como aparece nos bytes | onde |
|---|---|---|---|
| `MagicNumber` | `0x494d4841` | `41 48 4d 49` = `"AHMI"` | `FileLoad.cpp:582`, ConfigInfo+32 |
| `CFG_MAGIC_NUM` | `0x41484D49` | `49 4d 48 41` = `"IMHA"` | `LIB/projects/Bootloader/Source/Cfg/adapt/cfg_ci.h:30`, `upg_cfg.bin` (offset 0 = `49 4d 48 41`) |

São o mesmo texto com byte-order trocado, em dois formatos diferentes (o `.acf` e o
`upg_cfg.bin`). Um `grep` por `"AHMI"` no binário bruto só acha o do `.acf`; o do
`upg_cfg.bin` não aparece.

---

## 4. Comparação com o `RE-acf.md`

| `RE-acf.md` afirma | fonte diz | veredito |
|---|---|---|
| **FATO 2** — o container é preenchido com zeros até múltiplo de 0x4000; todo `.acf` tem `8 + N*16384` | O `+8` é o header do arquivo (`StartOfConfigdata` + checksum) e o firmware **exige** `StartOfConfigdata % 16384 == 0` (`FileLoad.cpp:570`). O arquivo mede `8 + k*16384` porque `ConfigInfo.TotalSize` (= arquivo − 8) é sempre múltiplo de 16 KB. O arredondamento é do gerador (exe); do firmware vem a *exigência*. | **CONFIRMA** (mecanismo explicado) |
| **FATO 2** — "16 KB cai na granularidade da flash (4 setores)" | Verdade para erase, mas o `.acf` no GC9002 está no **mesmo QSPI do código** (0x08100000) e é lido por XIP; não há flash de textura separada nem erase por chunk | **CORRIGE** (o alinhamento é do container, não da geometria de escrita) |
| **FATO 3** — `[0..4) u32 tamanho do payload`, `[4..8) checksum`, `+32768 de config com 'AHMI' e a5 5a 5a a5` | `@0` é `StartOfConfigdata` (offset até o ConfigInfo), não tamanho. `@4` é o checksum. `@8` e `@12` existem. O "AHMI" fica em `StartOfConfigdata + 32` (dentro do ConfigInfo), **não** numa cauda de 32 KB com magic próprio; o `A5 5A 5A A5` é footer de 4 bytes, não um bloco | **CORRIGE** |
| **FATO 3** — "o `.acf` do IDE não tem a cauda, então a cauda é opcional" | A "cauda" é o bloco de config (`ConfigInfo`+páginas), que o firmware **exige** (magic + versão). Sem ela o aparelho mostra os cinco pontos. O que varia é o tamanho dela (1 bloco de 16 KB na amostra, ~48 KB no de fábrica 240×240) | **CORRIGE** |
| **FATO 4** — imagem do slot = 57600 B em 685992, 3600 blocos de 16 B, raster sem swizzle, bloco (0,0) no offset 0 | `57600 = 240×240×1 byte/px = 60×60×16`; o formato é 1 B/px por bloco 4×4 e a ordem é raster (o decodificador indexa `y*4+x` dentro do bloco e o offset vem de `TexAddr`) | **CONFIRMA** |
| **FATO 5** — bitstream LSB-first a partir do bit 1; R0/R1/G0/G1/B0/B1/A0/A1; 16 pesos de 4 bits a partir do bit 65; `c = c0+(c1-c0)*w/15` | Layout de bits **exato** = `stc_rgba_one_partition_dec` (`stc.cpp:629-658`) — é o tipo **STCRGBA888**. A interpolação é `(w + w/8)/16` com saturação, não `w/15`. E existe o tipo **STCRGB888**, com pesos de **5 bits a partir do bit 49** e `(w+w/16)/32` (`stc.cpp:723-747`) | **CONFIRMA o layout / CORRIGE a fórmula / COMPLETA** (há um segundo layout) |
| **FATO 5** — "o bit 128 nunca é usado; o compilador orienta os endpoints para o último peso caber em 3 bits" | Confere e o motivo é exatamente esse: em RGBA o 16º peso começa no bit 125 e sobra com **3 bits** (máx. 7) porque o `u128` acaba em 127. No modo RGB sobra com **4 bits** (máx. 15 de 0..31) | **CONFIRMA** |
| **FATO 6** — `u16 magic 0x0080`, `u16 count`, header de 16 KB + `count`×64 KB | `@0` é um **u32** `StartOfConfigdata`: o "magic 0x8000" e o "count 12" são os dois u16 desse único u32 (`0x000C8000` → `0x8000` e `12`). Não há magic `0x0080` nem tabela de blocos de 64 KB; os 64 KB são só artefato de ler o offset como par u16 | **CORRIGE** |
| **FATO 6** — checksum = XOR de todas as words pulando o campo e a última word; com o valor certo, XOR de tudo = 0xA55A5AA5 | Exato. Verificado numa amostra independente (480×272): `XOR(tudo) = 0xA55A5AA5`, `XOR(sem +4 e sem footer) = 0x1D99EAB8` = gravado | **CONFIRMA** |
| **FATO 7 / "o que falta" #1** — o firmware **não** valida checksum (teste dedicado) | Não valida o **do arquivo** (`@4`); **valida o `CheckCode` de cada página** e trava em loop infinito se divergir (`AHMIInterface.cpp:1421` + `:1387-1423`) | **CORRIGE** (parcialmente: o teste provou a metade certa) |
| **FATO 7** — "região crítica entre 772392 e 801200; escrever ali reinicia em ciclo" | `StartOfConfigdata` do `.acf` de fábrica 240×240 é **802816** (49×16384; = 851976 − 49160, pela conta do próprio FATO 6). A partir dele começam `ConfigInfo`, `cfgString`, a tabela de páginas e os blocos de página. Qualquer escrita que atravesse 802816 corrompe o `CheckCode` de alguma página → `do{}while` infinito. Isso reconcilia **todos** os pontos medidos: `753192..772392` ok (fica abaixo), `753192..810792` e `686000..801200`+ crash (atravessam) | **CONFIRMA e EXPLICA** (a fronteira é `StartOfConfigdata` = 802816, não 772392; o mecanismo é o checksum de página) |
| **FATO 7** — "as imagens custom não usam o formato de blocos; provavelmente pixel cru" | 57.600 B = 240×240 em STC (1 B/px) exatamente; o formato **é** o de blocos. "Lixo verde" é compatível com sub-formato trocado (RGB↔RGBA) ou com widget GIF (bloco LUT com header comprimido). "Pixel cru" (RGB565 em 686000) não existe como tipo de textura no firmware | **CONTRADIZ** (a conclusão); a observação de tela continua válida |
| **FATO 7** — SideCar: RGB565 cru em `0x4000 + 10*0x10000 + 0x37B0` | `0x4000 + 10*0x10000 + 0x37B0` = 686000, não alinhado a nada; o firmware lê `TexAddr` do registro de textura, não de fórmula. Gravar ali sem atualizar o registro e o `CheckCode` da página = lixo + boot loop, que é o que o RE-acf mediu | **CONFIRMA o sintoma / CORRIGE a causa** |
| **FATO 8** — `flashChecksum @0x020008b0` é stub: o caminho de gravação não valida checksum | Consistente: em nenhum ponto do SDK o campo `@4` do `.acf` é lido ou conferido | **CONFIRMA** |
| "o modo 1 de bloco é necessário só para decodificar arquivos oficiais" | O bit 0 seleciona 5 modos de partição (`stc.cpp:1190-1201`, `:708-718`); "modo 1" é um deles (`&0x3 == 0x1`). O gerador do ODM **usa** os modos ≥1 em arquivos oficiais (a primeira textura da amostra `EX/` tem `bit0=1`, `&0x7==3`) | **CONFIRMA, com correção de escopo** (não é 1 modo extra: são 4) |

---

## 5. Roteiro para gerar o `.acf` sem o compilador do ODM

O que o fonte prova ser necessário (tudo gera em Python puro):

1. **Decidir o mapa de texturas.** Para cada textura: `w`, `h`, tipo
   (`0x00` RGB ou `0x10` RGBA), e o offset `TexAddr`. Não precisa alinhamento entre
   texturas; o primeiro offset livre depois do header (`0x4000`) serve.
2. **Comprimir em STC**: `ceil(w/4)*ceil(h/4)` blocos de 16 B, ordem raster. Modo 0
   (`bit0=0`) é o mais simples; o `acf_codec.py` já gera o sub-formato RGBA (FATO 5),
   que é o tipo `0x10`. Para `0x00` é preciso o layout de 5 bits (§2.3) — **não
   implementado no repo hoje**.
3. **Header**: `u32 @0 = StartOfConfigdata` (múltiplo de 16384, ≥ fim das texturas),
   `@4 = checksum`, `@8` livre, `@12` = nome do projeto.
4. **`ConfigInfoClass`** (284 B) com `MagicNumber=0x494d4841`,
   `TotalSize = tamanho_final - 8`, `NumofPages`, `CfgStringSize`,
   `AHMIInfo.Version = 0x5A010a13` da versão do firmware alvo, `ScreenWidth/Height`.
5. **`DynamicPageCfgClass[NumofPages]`**, `cfgString`, depois os blocos de página, cada
   um com `StoreOffset`, `TotalSize`, `CheckCode = 0xA55A5AA5 ^ XOR(words)`
   e a tabela `TextureClass[totalNumOfTexture]` no fim do bloco (48 B cada).
6. **Footer** `0xA55A5AA5` e o `checksum` do arquivo por último.
7. Sanidade que o device aplica: `StartOfConfigdata % 16384`, magic, versão,
   e `CheckCode` por página. Tudo o resto é livre.

Validador mínimo (o que o firmware faz, e nada além):

```python
assert StartOfConfigdata % 16384 == 0
assert u32(StartOfConfigdata+32) == 0x494d4841
assert u32(StartOfConfigdata+260) == 0x5A010a13      # versão do firmware alvo
for p in pages:                                       # 56 B cada
    blk = data[StartOfConfigdata+p.StoreOffset:][:p.TotalSize]
    assert xor_words(blk) ^ 0xA55A5AA5 == p.CheckCode
```

---

## 6. Não documentado / pendências

1. **Offsets das 3 imagens** no `Texture.acf` de fábrica 240×240 — falta o arquivo.
   Com ele, §2.1 + §5 dão a resposta em minutos (e o `attr` de cada uma decide entre
   RGB/RGBA e entre textura crua e bloco GIF).
2. **Significado de `u32 @8`** do header. Medido: `TotalTextureSize/2` na amostra.
   Nenhum leitor no SDK. Hipótese: tamanho da textura por buffer (par/ímpar).
3. **`DeviceID` em `+284`** (bootloader) vs `+220` (struct desta versão) — divergência
   não resolvida; não afeta a geração do `.acf`.
4. **`interpolate()` vs silício** (§2.3): não dá para decidir só pelo fonte se o ASIC
   usa `(w+w/8)/16` ou uma tabela equivalente a `w/15`. Precisa de medição óptica ou
   do RTL.
5. **`staticTexture` / `SliceFlagsHeaderAddr`** (fatias e color-slice, `TextureClass.cpp:744-795`):
   o mecanismo está claro; a amostra 480×272 não usava (todas as texturas têm
   `staticTexture=0` e `SliceFlagsHeaderAddr=0`). O `SliceFlagsHeaderAddr` foi decodificado
   depois, num arquivo com GIF — ver **§7.4**.
6. **Encoder STC** não existe no SDK — só o decodificador. O lado da compressão
   continua sendo o `acf_codec.py` + FATO 5 (mais a correção da fórmula em §2.3).

---

## 7. GIF animado

Par de arquivos analisado (mesmo projeto, mesmo comando, só o slot 1 muda):

| arquivo | tamanho | `StartOfConfigdata` | páginas | texturas | quadros no slot 1 |
|---|---|---|---|---|---|
| `/tmp/opencode/template_static.acf` | 901.128 B | `0xD4000` | 11 | 98 | 1 |
| `/tmp/opencode/gif75.acf` | 5.160.968 B | `0x4E4000` | 11 | **98** | **75** |

Os dois passam no `acf_inspect.py` (magic, versão e `CheckCode` das 11 páginas).

**Ressalva medida**: os dois builds **não** diferem só no slot 1. Das três texturas
240×240 das páginas 4/5/6: a da pág. 6 é idêntica (MD5 do payload igual), a da **pág. 4**
(o slot do GIF) mudou de conteúdo, e a da **pág. 5** também (no estático é uma imagem, no
`gif75` é um quadro preto — 53.315 dos 57.600 bytes diferentes). Isso importa para
interpretar o número de bytes divergentes da reconstrução (§7.6).

## 7.1 Q1 — onde estão os 75 quadros

**Não existe textura extra.** O número de registros `TextureClass` é **98 nos dois
arquivos**. Os 75 quadros são **75 fatias (slices) de uma única textura**: o registro
`#1` da página 4.

O endereço de cada fatia vem de `TextureClass.cpp:785` (caso `staticTexture == 0`):

```c
addr = FocusedSlice * SingleSliceSize;
sourcebufferaddr[..].Addr = TexAddr + addr + TEXTURE_ADDR_OFFSET;   // :791
```

Medido no registro (pág. 4, `#1`, tabela em bloco+`0x21C`):

| campo | valor |
|---|---|
| `SingleSliceSize` (+0) | `0x0000E100` = 57.600 |
| `TexAddr` (+4) | `0x000A77B0` = 686.000 |
| `SliceFlagsHeaderAddr` (+8) | `0x004C62B0` = 5.006.000 (= `TexAddr + 75*SingleSliceSize`) |
| `mTexAttr` (+12) | `0x00000110` (STCRGBA888 + `ADDRTEXTURE`) |
| `TexWidth/TexHeight` | 240 / 240 |
| `staticTexture` (+44) | 0 (sem entrelaçamento de 16 KB) |

Portanto **quadro *n* = `0xA77B0 + n*0xE100`**, contíguos, na ordem das fatias:

| n | offset | n | offset |
|---|---|---|---|
| 0 | `0x0A77B0` | 49 | `0x3588B0` |
| 1 | `0x0B58B0` | 50 | `0x3669B0` |
| 2 | `0x0C39B0` | 51 | `0x374AB0` |
| 24 | `0x1F8FB0` | 74 | `0x4B81B0` |
| 25 | `0x2070B0` | fim | `0x4C62B0` |

Depois do último quadro vem o *trailer* de fatias (§7.4) e então as texturas das páginas
5 e 6, que foram relocadas:

| região | estático | gif75 |
|---|---|---|
| pág. 4 `#1` (slot 1) | `0xA77B0` + 1×57.600 | `0xA77B0` + 75×57.600 = até `0x4C62B0` |
| trailer do slot 1 | `0xB58B0`, 16 B | `0x4C62B0`, 32 B |
| pág. 5 `#1` | `0xB58C0` | `0x4C62D0` |
| trailer | `0xC39C0`, 16 B | `0x4D43D0`, 16 B |
| pág. 6 `#1` | `0xC39D0` | `0x4D43E0` |
| trailer | `0xD1AD0`, 16 B | `0x4E24E0`, 16 B |
| padding até a config | `0xD1AE0`..`0xD4000` (9.504 B) | `0x4E24F0`..`0x4E4000` (6.928 B) |

**Conta do tamanho**: `4.259.840` (delta de `StartOfConfigdata`) `= 74×57.600 + (32−16) − (9.504−6.928)`
= `4.262.400 + 16 − 2.576`. O crescimento das fatias é absorvido em parte pelo padding
do fim da área de textura.

Os 75 quadros têm só **6 conteúdos distintos** (o gerador gravou as repetições, não
deduplicou): `0`, `1..24`, `25`, `26..49`, `50`, `51..74`. Ele também não reaproveita a
imagem do build estático: o quadro 0 do `gif75` ≠ imagem do `template_static`.

## 7.2 Q2 — como o widget referencia a sequência

O widget é do tipo `GIF` (34) e guarda cinco `u16` consecutivos em
`WDG_u16_userVariables[WIDGET_GENERAL_NUM + 8..12]` (`AHMI/widgetClass_cd.h:152-156`:

```
+8  GifNowTime     +9  GifInterval   +10 GifNowIdx   +11 GifSliceNum   +12 GifID
```

No bloco da página 4 eles ficam em **bloco+`0x178`..`0x181`**:

| offset | índice | campo | estático | gif75 |
|---|---|---|---|---|
| `+0x178` | `[GENERAL+8]` | `GifNowTime` | 0 | 0 |
| `+0x17A` | `[GENERAL+9]` | `GifInterval` | 100 | 100 |
| `+0x17C` | `[GENERAL+10]` | `GifNowIdx` | 0 | 0 |
| `+0x17E` | `[GENERAL+11]` | **`GifSliceNum`** | **1** | **75** |
| `+0x180` | `[GENERAL+12]` | `GifID` | 0 | 0 |

Fluxo em runtime:

- `GifClass::widgetCtrl` pega a textura por índice:
  `texturePtr = &pCurrentPage->pBasicTextureList[p_wptr->StartNumofTex]`
  (`CS/AHMI/Widget/Gif.cpp:201`). A página tem 2 texturas: `#0` = `PURECOLOR`
  (fundo) e `#1` = a imagem 240×240, então o widget só pode estar apontando para `#1`
  (não localizei o campo `StartNumofTex` no bloco, mas é o único valor que faz a
  animação cair sobre a imagem).
- o quadro exibido é `texturePtr->FocusedSlice = p_wptr->GifNowIdx`, validado contra
  `GifSliceNum` (`Gif.cpp:343-354`) — daí o endereço por fatia.
- `ActionProcessor::tickGifOP` (`CS/AHMI/ActionProcessor.cpp:2405-2445`) soma
  `AnimationIntervalTime` (= **30 ms** em `EMBEDDED`, `AHMI/aniamtion.h:30`) em
  `GifNowTime` a cada tick e, quando passa de `GifInterval` (= 100), chama
  `SetValueCtrl` → `GifNowIdx = (GifNowIdx+1) % GifSliceNum` (`Gif.cpp:415`).
  Período efetivo: `ceil(100/30)=4` ticks ≈ **120 ms por quadro**.
  O timer é registrado em `DynamicPageClass.cpp:1464`
  (`setInterval(tickGifOP, NULL, AnimationIntervalTime)`).
- `GifID` fica 0 (`= GZIPTYPE_Intern | id 0`), mas **não é usado neste firmware**
  (§7.3).

**Diff byte a byte dos blocos de página** (o resto do bloco é idêntico):

| página | offset no bloco | campo | antes → depois |
|---|---|---|---|
| 2 | `+0xE52` (u16) | padding do registro `#18` (`TextureClass`+46) — ver §7.6 | `0x0292` → `0x0291` |
| 4 | `+0x17E` | `GifSliceNum` | `1` → `75` |
| 4 | `+0x225..0x226` | `#1.SliceFlagsHeaderAddr` (bytes 1-2) | `0x0B58B0` → `0x4C62B0` |
| 5 | `+0x220..0x222` | `#1.TexAddr` | `0x0B58C0` → `0x4C62D0` |
| 5 | `+0x224..0x226` | `#1.SliceFlagsHeaderAddr` | `0x0C39C0` → `0x4D43D0` |
| 6 | `+0x220..0x222` | `#1.TexAddr` | `0x0C39D0` → `0x4D43E0` |
| 6 | `+0x224..0x226` | `#1.SliceFlagsHeaderAddr` | `0x0D1AD0` → `0x4E24E0` |

E, na tabela de descritores de página (`ConfigInfo`+284+`CfgStringSize`, 56 B por página),
só o `CheckCode` muda — `StoreOffset`, `TotalSize`, contagens e `GifSliceNum` **da página
continuam iguais** (o bloco não cresce):

| página | `CheckCode` antes | depois |
|---|---|---|
| 2 | `0x6E841F06` | `0x6E871F06` |
| 4 | `0xA7056A92` | `0xA7085092` |
| 5 | `0xA7032492` | `0xA7056492` |
| 6 | `0xA7056692` | `0xA7072292` |

⚠️ Ou seja: **mexer no bloco de uma página obriga a recalcular o `CheckCode` daquela
página** — que não é checksum de textura e sim de página (§3.4). O `minitela_patch.py`
hoje não faz isso (ele só mexe antes de `StartOfConfigdata`).

## 7.3 Q3 — os quadros estão crus (STC), não em gzip

Condição de compilação, lida no fonte:

- o `#include` do `gziplib` em `Gif.cpp` é `#ifndef CHIP_GC9002_NoHyper` +
  `#if defined(CHIP_GC9002)` (`Gif.cpp:17-28`);
- mas toda a lógica de bloco comprimido está sob **`#ifdef USE_GZIP_LIB`**
  (`Gif.cpp:203-259`), e em `projects/AHMI_SW/Source/ahmi/app/platform.h:42` a macro está
  **comentada**: `//#define USE_GZIP_LIB`. Idem `AHMIInterface.cpp` (tarefa de 10 ms).
- não existe macro `texture_gif` no fonte; o que decide é `USE_GZIP_LIB`.
- `CHIP_GC9002_NoHyper` só retiraria o `#include`; o caminho gzip depende de
  `USE_GZIP_LIB` de qualquer forma.

Com `USE_GZIP_LIB` **ligado**, `GifID != 0xFFFF` faria o widget buscar
`getGzipBlockInfo(GifID & 0x7FFF, GifID>>15)` e o dado seria um bloco LUT:
`u32@bloco` com `lutSize = valor>>12` (KB), `"AHMI"` em `bloco + lutSize*1024`, header
comprimido de 32 B e cada quadro em `0x20 + n*SinglesliceSize`
(`CS/gziplib/gzipBlock.cpp:39-91`, `Main/AHMIInterface.cpp:435-443`). **Não é o caso
aqui.**

Provas no arquivo:

- não existe a string `"AHMI"` nem `"GIF"` em `[0xA77B0, 0x4C62B0)`;
- os 75 quadros têm exatamente `75 × 57.600 = 75 × 3600 × 16` bytes;
- no quadro 0, **3600 de 3600** blocos têm `bit0 = 0` (STC one-partition, §2.3).

## 7.4 O trailer de fatias (`SliceFlagsHeaderAddr`)

É o que o §2.4 chamava de "tabela de flags" e nenhum arquivo da amostra usava. Layout
lido de `TextureClass.cpp:565-567` + `getSliceRealOffsetWithFlags` (`:441-514`):

```
+0  u32  flagsAddr   = trailer+8
+4  u32  colorsAddr  = trailer+8+(2*ceil(nfatias/16))
+8  u16[ceil(n/16)]  bitmap: bit i = 1 -> fatia i é imagem; 0 -> fatia i é cor
..  área de cores (2*ceil(n/16) bytes nos arquivos medidos; ver ressalva)
padding com zero até múltiplo de 16
```

Detalhes que morderam:

- esses dois primeiros `u32` são gravados como **dois `u16` little-endian**, e lidos de
  volta por `readU32FromTextureBuffer` como `(arr[0]<<16)|arr[1]` (`:377-399`).
  Ex.: `4c 00 b8 62` → `0x004C62B8`. Não é `u32` LE nem BE "de livro".
- o bitmap é lido **MSB-first dentro de cada `u16`** (`readBitFromTextureBuffer`,
  `:401-439`).
- tamanho: `8 + 4*ceil(n/16)` arredondado para 16 B. Dá **16 B** para n ≤ 32,
  **32 B** para 33 ≤ n ≤ 96, **48 B** para 97 ≤ n ≤ 112… É por isso que o trailer do
  slot 1 passa de 16 para 32 bytes com 75 fatias, e o das páginas 5/6 continua 16.
- em `getSliceRealOffsetWithFlags` o retorno é o *índice denso* da fatia imagem
  (conta os bits 1 até `FocusedSlice` e subtrai 1) — com todas as fatias imagem, o
  resultado é o próprio índice, e `addr = realOffset * SingleSliceSize` (`:750-765`).
- **ressalva**: nenhum arquivo analisado tem fatia de *cor*, então o formato exato da
  área de cores (2 bytes por 16 fatias no trailer × leitura `u32` em
  `colorsAddr + idx*4`, `:777`) não foi exercitado. Para GIF (todas as fatias imagem)
  basta zerar essa área.

Conteúdo medido em `0x4C62B0`:
`4c 00 b8 62 | 4c 00 c2 62 | ff ff ff ff ff ff ff ff e0 ff | 00…` →
flagsAddr `0x4C62B8`, colorsAddr `0x4C62C2`, 75 bits 1 seguidos de zeros.

## 7.5 Q4 — o que muda no header e no `ConfigInfo`

| campo | estático | gif75 | delta |
|---|---|---|---|
| tamanho do arquivo | 901.128 | 5.160.968 | +4.259.840 |
| `u32 @0` `StartOfConfigdata` | `0x000D4000` | `0x004E4000` | +4.259.840 |
| `u32 @4` checksum | `0xCBB8713E` | `0x74ADA339` | recalculado |
| `u32 @8` | `0x00067A90` (424.592) | `0x0026FF98` (2.555.800) | +2.131.208 |
| `ConfigInfo+36` `TotalSize` | 901.120 | 5.160.960 | +4.259.840 |
| `ConfigInfo+40` `TotalTextureSize` | 849.184 | 5.111.600 | **+4.262.416** |
| `ConfigInfo+44` `DynamicPageSize` | 6.256 | 6.256 | 0 |
| todo o resto do `ConfigInfo` | — | — | idêntico |

Relações (todas conferidas nos dois arquivos):

- `TotalSize = tamanho_do_arquivo − 8` e `tamanho = 8 + k*16.384`.
- `@8 = TotalTextureSize / 2` (424.592×2 = 849.184; 2.555.800×2 = 5.111.600).
- `delta(TotalTextureSize) = 74×57.600 + (32−16) = 4.262.416` — o campo soma o espaço
  de textura **incluindo os trailers**, por isso difere do delta do arquivo em 2.576
  (o padding que diminuiu).
- o checksum do arquivo é a única coisa que precisa ser recalculada *depois* de tudo
  (§3.4): `XOR` de todas as words, exceto a própria e a última.

## 7.6 Q5 — receita para gerar o animado

Partindo de um `.acf` estático válido e de N quadros já codificados em STC
(`N × slice_bytes`, `slice_bytes = ceil(w/4)*ceil(h/4)*16`):

1. **Localizar o registro do slot.** No bloco da página do slot, a tabela
   `TextureClass[]` está no fim do bloco; o registro da imagem é o que tem
   `mTexAttr>>4 in (0x0,0x1)` e `TexWidth × TexHeight` = tamanho do widget.
   `TexAddr`, `SingleSliceSize`, `SliceFlagsHeaderAddr` e o trailer atual (16 B) saem dele.
2. **Delta** `d = (N−1)*slice_bytes + trailer_novo − trailer_velho`
   (`trailer(n) = 8 + 4*ceil(n/16)` arredondado para 16).
3. **Remontar a área de textura** `[0, StartOfConfigdata)`:
   - `[0, TexAddr)` intacto;
   - N quadros em `TexAddr + i*slice_bytes`;
   - trailer novo em `TexAddr + N*slice_bytes`: `flagsAddr = tr+8`,
     `colorsAddr = tr+8+2*ceil(N/16)`, bitmap com N bits 1 (MSB-first em cada `u16`),
     área de cores zerada, padding até 16;
   - toda textura (e trailer) com `addr > TexAddr` deslocada em `+d`, na mesma ordem
     (o gerador reempacota assim; nenhum alinhamento extra é usado);
   - completar até `StartOfConfigdata_novo` com o padding (qualquer byte — o firmware
     não lê; para reproduzir o gerador, copie o padding antigo truncado).
4. **`StartOfConfigdata_novo`** = `arredonda_16K(fim_da_última_textura + trailer + padding)`.
   Na prática: o arquivo final tem que continuar `8 + k*16.384`; o padding absorve a
   diferença (aqui sobraram 6.928 B).
5. **Patchar os registros de textura** de todas as páginas afetadas:
   `TexAddr += d` e, se `SliceFlagsHeaderAddr != 0`, `+= d`; no registro do slot,
   `SliceFlagsHeaderAddr = TexAddr + N*slice_bytes`.
6. **`GifSliceNum = N`** no bloco do widget (`WDG_u16_userVariables[+11]`, aqui
   bloco+`0x17E`). `GifNowIdx`/`GifNowTime` = 0. `GifID` fica como está.
7. **Recalcular o `CheckCode`** de *cada* página cujo bloco foi tocado
   (`0xA55A5AA5 ^ XOR(words do bloco)`) no descritor `ConfigInfo+284+CfgStringSize+i*56+8`.
8. **Header/ConfigInfo**: `@0`, `TotalSize`, `TotalTextureSize` (`+delta`),
   `@8 = TotalTextureSize/2`, e por último o checksum `@4` e o footer `0xA55A5AA5`.
9. Validar com `./acf_inspect.py` (é o que o firmware checa).

### Validação da receita (reconstrução)

Implementei os 9 passos acima em Python e comparei com o `gif75.acf` original:

| variante | entrada | bytes | divergentes |
|---|---|---|---|
| **B — estrutura** | estático + os 75 quadros do `gif75` + o conteúdo das páginas 5/6 do `gif75` | 5.160.968 | **10** |
| A — estrita | estático + os 75 quadros (conteúdo das páginas 5/6 vem do estático) | 5.160.968 | **53.326** |

A variante A só diverge por **conteúdo**: 53.315 dos 53.326 bytes são os pixels da
página 5 (o estático tem outra imagem ali — §7.1); os 11 restantes são os mesmos 10 de B
mais 1 byte de checksum.

Os **10 bytes** de B, um por um:

| offset | bytes | o que é |
|---|---|---|
| `0x4`..`0x6` | 3 | **checksum do arquivo** — consequência dos outros (recalculado sobre bytes diferentes) |
| `0x4E41FA` | 1 | `CheckCode` da pág. 2 — consequência do byte seguinte |
| `0x4E7136` (`cfg+0x3136` = pág.2 bloco `+0xE52`) | 1 | **padding do registro `TextureClass`** (o struct acaba em `+45`, `useCanvasPoint`; `+46/+47` são padding e o firmware não lê) |
| `0x4E91BE`, `0x4E923A` (pág. 7, bloco `+0x92` e `+0x10E`) | 2 | campo `u16` **não decodificado**, duplicado em `CanvasClass`/`SubCanvasClass` (204 nas págs. 4/5/6; 79→83 na pág. 7). As duas ocorrências mudam igual → o `CheckCode` da pág. 7 não muda (o XOR das duas variações se anula) |
| `0x4EC000`..`0x4EC002` (`cfg+0x8000`) | 3 | lixo de heap do gerador nos 4 bytes antes do footer (`0x8FF2E8C4` vs `0x8FF0E2D4`) |

Ou seja: **nenhum byte de estrutura divergiu**. Dos 10: 4 são lixo/padding do gerador
que o firmware não lê (1 em `TextureClass`+46, 3 antes do footer), 2 são um campo interno
ainda não decodificado e 4 são checksums que são função dos outros bytes.

## 7.7 O que o `minitela_patch.py` precisa mudar

Hoje (`minitela_patch.py:103-120`) ele abre o template, sobrescreve
`data[addr:addr+slice]` com a textura nova (mesmo tamanho, mesmos offsets), chama
`codec.set_checksum` e grava. Isso funciona porque a área de textura **não** é coberta
por nenhum checksum e nada se move.

Para suportar N > 1 quadros é preciso:

1. **Deixar de ser patch in-place.** Com N > 1 o arquivo cresce e tudo depois do slot
   anda; o mínimo é a rotina de "remontar a área de textura + relocar" do §7.6 (passos
   2-5). Alternativa mais simples e mais segura: manter **um template por número de
   quadros** (N=1, N=16, N=32, ... usam trailers de tamanhos diferentes) e só
   sobrescrever os quadros — mas o alvo continua sendo o registro certo, não um offset
   fixo.
2. **Escrever o trailer de fatias** (`SliceFlagsHeaderAddr`) com o tamanho certo
   (16 B até 32 fatias, 32 B até 96, …) e o bitmap todo em 1 para fatias de imagem.
3. **Relocar** `TexAddr` e `SliceFlagsHeaderAddr` de todas as texturas com
   `addr > slot_addr` (aqui as páginas 5 e 6), atualizando os registros nos blocos.
4. **Atualizar `GifSliceNum`** no bloco do widget (não existe campo equivalente na
   página: `DynamicPageCfgClass` não tem contagem de quadros).
5. **Recalcular o `CheckCode`** de toda página cujo bloco mudou (`0xA55A5AA5 ^ XOR`).
   Este é o ponto que hoje não existe e que faria o firmware entrar no
   `do{}while` infinito de `AHMIInterface.cpp:1387-1423` se ficasse para trás.
6. **Atualizar o header**: `@0`, `TotalSize = tamanho−8`, `TotalTextureSize += d`,
   `@8 = TotalTextureSize/2`, e só então `@4` (checksum) — nessa ordem.
7. **Manter `8 + k*16.384`**: o padding do fim da área de textura é a variável de ajuste;
   `StartOfConfigdata` continua múltiplo de 16 KB e `DynamicPageSize` não muda.
8. **Não copiar o padding nem os bytes `TextureClass`+46/+47 do template novo** — são
   lixo de heap do gerador; qualquer valor serve (mas, se quiser reprodutibilidade byte
   a byte, copie do template truncado, como na reconstrução).
9. Ler os quadros do GIF respeitando o `GifInterval` implícito: o firmware consome
   `GifSliceNum` fatias em sequência a `ceil(GifInterval/30)` ticks cada
   (`ActionProcessor.cpp:2405-2437`), então o campo `GifInterval` do bloco tem que
   acompanhar o atraso do GIF se ele mudar.
