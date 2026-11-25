# Engenharia reversa do primeiro firmware GC9002 real — `flash_download.elf`

Companheiro do `RE-acf.md`. Aqui o alvo não é o container `.acf`, é **o outro lado**:
o firmware que o fabricante usa para gravar a flash QSPI NOR que mapeia em `0x08000000`
— o mesmo barramento onde mora o `Texture.acf` (`0x08100000`).

Método: 100% estático. O `.elf` **não foi executado**, nada foi gravado na minitela.
Ferramentas: `llvm-readelf`/`llvm-dwarfdump`, Capstone 5 (`rv32` + RVC) e Ghidra 12.2
(projeto `work/fw142`, ignorado pelo git). Decompilado completo em
`/tmp/opencode/fw/decompiled.c` (efêmero); os endereços citados bastam para refazer.

Regra deste documento: **todo achado tem coordenada**. O que é leitura de código aparece
como `símbolo @ 0xADDR`; o que é inferência está marcado **HIPÓTESE**; o que não dá para
saber por este binário está marcado **NÃO DOCUMENTADO**.

---

## 1. O que é o binário

| propriedade | valor |
|---|---|
| caminho | `.tools/vendor/ext/GC9002芯片支持包/GC9002芯片支持包/flash_download.elf` |
| sha256 | `9d8ba8618cf6ed3074faf767088faff1d07496f1600c09672bc3237f58e5d3eb` |
| tamanho | 690384 bytes (0xA88D0) |
| formato | ELF32 LSB, `EXEC`, RISC-V, **RVC + RVE**, soft-float ABI, static, `not stripped`, `with debug_info` |
| entry | `0x02000000` (`Reset_Handler`, símbolo em `0x02000000`, 114 bytes) |
| header | `e_flags = 0x9` (RVC \| RVE), 1 program header, 23 seções, 242 símbolos |
| segmento | 1× `LOAD` file `0x0400` → vaddr `0x02000000`, filesz=memsz `0x7660`, flags `RWE`, align `0x400` |
| ISA (atributo) | `rv32e1p9_m2p0_c2p0_xtheadse2p0`, `stack_align=4`, priv 1.11 |
| toolchain | `GCC: (Xuantie-900 elf newlib gcc Toolchain V2.6.1 B-20220906) 10.2.0` (.comment) |
| flags de compilação | `-mabi=ilp32e -mtune=e902 -march=rv32emc_xtheadse -g3 -Os -ffunction-sections -fdata-sections` (DWARF `DW_AT_producer`, ex. em `0x00003c57`) |

Seções (VMA / tamanho / offset no arquivo):

| seção | VMA | tam | off |
|---|---|---|---|
| `.text` | `0x02000000` | `0x2c50` (11.344 B) | `0x0400` |
| `.rodata` | `0x02002c50` | `0x190` | `0x3050` |
| `.data` | `0x02002de0` | `0x20` | `0x31e0` |
| `.vectors` | `0x02002e00` | `0xbc` (47 words) | `0x3200` |
| `.bss` | `0x02002ec0` | `0x45a0` | NOBITS |
| `._user_heap` | `0x02007460` | `0x200` | NOBITS |
| `DevDscr` | `0x0` (não alocado) | `0x734` | `0x7a60` |
| debug | `.debug_info` `0x16e9c`, `.debug_str` `0x4d331`, `.debug_macro` `0xef1b`, ... | | `0x8210`+ |

**Não é o firmware da minitela.** É o *flash algorithm* no formato do C-Sky CDK
(`FlashDev.c` + `driver.c`, ver `DW_AT_decl_file` de `FlashDevices` e das funções
`flash*`), que a IDE carrega em SRAM, executa e comanda por uma struct em memória.
É o código que o fabricante usa quando grava a placa na fábrica/upgrade.

O binário é linkado para uma **SRAM de 32 KB em `0x02000000`** (`__ram_end = 0x02008000`,
`.bss` termina em `0x02007460`, heap `0x02007460`–`0x02008000`). O HyperRAM
(`HYPER_DATA_BASE 0x20000000`) é inicializado em `SystemInit` (`0x02002ac8` →
`HAL_HYPER_Init @ 0x02001d1a`) mas **não é usado como memória** por este algoritmo —
só os registradores dele são tocados.

Não há sistema operacional de verdade em uso: `pxReadyTasksLists`/`vTaskSwitchContext`
existem porque o FreeRTOS é linkado (port RISC-V), mas o `main` (`0x02000630`) é um
laço `while(1) { __bkpt_label(); switch(g_func) ... }`.

---

## 2. Mapa de periféricos

Duas colunas: o que o **código realmente toca** e o que só existe como macro nos headers
(que ficou preservado em `.debug_str`, porque `-g3` grava o dump de macros).

### 2.1 Usado de fato pelo binário

| periférico | base | onde aparece |
|---|---|---|
| **CQSPI** (QSPI controller) | `0x40100000` | `csi_qspi_init @ 0x02000bc6` grava `qspi->dev.reg_base = 0x40100000`, `irq_num = 0x21`; `QSPI_MspInit @ 0x02000b8e` compara com ele |
| **CQSPI janela de dados** | `0x08000000` | `cqspi_dev_cfg` em `.data` `0x02002dec` = `{0x40100000, 0x08000000, ...}` (dump: `0x02002dec: 40100000`, `0x02002df0: 08000000`); macro `CQSPI_DATA_BASE (0x08000000UL)` |
| **RCC** | `0x40200000` | `0x40200014` (prescaler CQSPI), `0x40200018` (DQSPI), `0x40200030` (cache), `0x4020003c`; `HAL_RCC_SYSCLKConfig(RCC_PLL_480M, RCC_AHB_Pres_4)` em `SystemInit` |
| **HYPER** (HyperRAM/PSRAM ctrl) | `0x40101000`, janela `0x20000000` | `HAL_HYPER_Init @ 0x02001d1a` (assert em `Instance != 0x40101000`, `MapAHBAddrBase = 0x20000000`, `WDATA=0x8F04`, `OP=0x109`, procura ID `0x5F`) |
| — leitura em `0x40101034` | | `main @ 0x02000630`: `lui a5,0x40101; lw a0,0x34(a5)` → só formata em string de debug (`uint32_to_str @ 0x020005d2`), resultado descartado |
| **DCACHE/CCM** | `0x40102000` | `ccm_EnableDCache @ 0x02001ca0`: `*(0x40200030) |= 1; *(0x40102000) = 0` |
| **CLIC** | `0xE0800000` | `SystemInit`: escreve `0xE0800000`, `0xE0800004`, `0xE080100E`, `0xE080100D` |
| **CORET / MTIME** | `0xE0004000` (mtimecmp), `0xE000BFF8` (mtime) | `csi_tick_config @ 0x02001a48` (tick de 1 ms: `AHB/1000`), IRQ CLIC nível 7 → `CSI_CORET_IRQHandler @ 0x02001ab2`; e o timeout de `qspi_send_cmd @ 0x02002578` lê `0xE000BFF8` (`lw t1,-8(0xE000C000)`) |

Registradores do CQSPI usados pelo driver (base `0x40100000`), extraídos do código:

| off | uso | coordenada |
|---|---|---|
| `0x00` | enable (bit0), remap-enable (bit16), baud div (bits 19–22), **idle (bit31)** | `qspi_enable @ 0x02002212`, `qspi_is_idle @ 0x02002196`, `qspi_set_baud_rate_div @ 0x02002248` |
| `0x04` | opcode de leitura (bits 0–7), modo da instrução (8–9), modo do endereço na leitura (12–13), modo dos dados na leitura (16–17), mode-bit enable (20) | `qspi_cfg_reads_writes @ 0x020021a0`, `qspi_set_spi_mode_base @ 0x020022f2` |
| `0x08` | opcode/dummy/modos do **write** | idem |
| `0x10` | captura de leitura (delay tx/rx, borda de amostragem) | `qspi_cfg_read_capture @ 0x020024cc` |
| `0x14` | nº de bytes de endereço (0–3), **page size (4–15)**, log2(block) (16–20) | `qspi_cfg_addr_bytes @ 0x02002454`, `qspi_cfg_page_size @ 0x0200241e`, `qspi_cfg_block_bytes @ 0x020023e8` |
| `0x24` | offset de remap | `qspi_remap_addr @ 0x0200248c` |
| `0x28` | valor do mode-bit | `qspi_set_mode_bit @ 0x020022ac` |
| `0x50/0x54/0x58` | lower/upper/`write protect` (bit1) | `qspi_write_protection_config @ 0x02002512`, `qspi_write_protection_ctrl @ 0x0200252a` |
| `0x90` | FLASH_CMD_CTRL: opcode, tamanhos, start (bit0), busy (bit1) | `qspi_send_cmd @ 0x02002578` |
| `0x94` | FLASH_ADDR (endereço da transação) | idem |
| `0xA0/0xA4` | FIFO de RX (até 8 bytes) | `csi_spiflash_read_reg @ 0x02001606` usa 1 byte |
| `0xA8/0xAC` | FIFO de TX | `csi_spiflash_write_reg @ 0x02001892` |

### 2.2 Só declarado (macro/IRQ), **sem nenhum acesso no código**

Estes endereços vêm de `.debug_str` (dump de macros do `-g3`) e não aparecem em
nenhum `lui` do `.text`. Servem como mapa do SoC, não como uso:

| periférico | endereço |
|---|---|
| `DQSPI_BASE` / `DQSPI_DATA_BASE` | `0x4010C000` / `0x31000000` (só o clock em `QSPI_MspInit`) |
| `CRC32_BASE` | `0x40108000` ← ver §5 |
| `DCACHE_BASE` | `0x40102000` |
| `UART_BASE` (UART0/1/2) | `0x40001000`, `+0x1000`, `0x4000E000` |
| `GPIOA_BASE` / `GPIOB_BASE` | `0x4000A000` / `0x4000B000` |
| `WDT_BASE` / `RTC_BASE` / `VIDEOCAP_BASE` | `0x40106000` / `0x40105000` / `0x4010B000` |
| `SPI0/1/2`, `I2C0/1`, `I2S` | `0x40007000`, `0x4000C000`, `0x4000D000`, `0x40005000`, `0x40006000`, `0x40008000` |
| `CANFD_BASE` / `DMA_BASE` / `ETH_BASE` | `0x40000000` / `0x50200000` / `0x50400000` |
| `CLIC_BASE` | `0xE0800000` |
| `SYSMAP_BASE` / `TCIP_BASE` / `DCC_BASE` | `0xEFFFF000` / `0xE000E000` / `0xE4010000` |

**Sem UART de verdade:** `putchar @ 0x02001b34`, `fputc @ 0x02001b0c` e
`printf @ 0x02001b38` são stubs que retornam 0; `puts @ 0x02001b10` só chama `fputc`.
As strings de erro (`csi_spiflash_program ERROR.` em `0x02002c80` etc.) existem e são
referenciadas, mas **nunca saem do chip**. Nenhum GPIO é configurado para a flash:
`QSPI_MspInit @ 0x02000b8e` só habilita clock no RCC (nada de GPIOA/B) — o que sugere
pinos dedicados no pacote (**HIPÓTESE**, não há muxing no código).

**Tabela de vetores** (`__Vectors @ 0x02002e00`, 47 words, `.vectors` off `0x3200`):

- `[0]` `0x020001c0` (`Default_Handler`, que é `c.j trap` → `trap @ 0x02000080`)
- `[1..2]` idem, `[3]` `tspend_handler @ 0x02000300`, `[7]` `CORET_IRQHandler @ 0x02000ab4`
- `[16..43]` handlers por periférico, na ordem:
  `16 CANFD, 17 UART0, 18 UART1, 19 UART2, 20 TIM0, 21 TIM1, 22 SPI0, 23 I2C0,
  24 I2C1, 25 SPI1, 26 I2S, 27 GPIOA, 28 GPIOB, 29 SPI2, 30 ADC, 31 WDG, 32 RTC,
  33 CQDPI, 34 VIDEO_CAP, 35 DMA, 36 OTG, **37 AHMI**, 38 DISPLAY, **39 CRC32**,
  40 MOTOR, 41 MAC, 42 EXTENSION, 43 DQSPI`
- Todos os handlers fracos (`WEAK`) são 4 bytes = `mret` (`0x30200073`), ex.:
  `UART0_IRQHandler @ 0x02000b1e`, `AHMI_IRQHandler @ 0x02000b6e`,
  `CRC32_IRQHandler @ 0x02000b76`, `DQSPI_IRQHandler @ 0x02000b86`.

Coordenada interessante para o projeto: **existe um vetor de IRQ chamado `AHMI`**
(`0x02000b6e`, índice 37). O SoC tem um bloco AHMI. **NÃO DOCUMENTADO** o que ele faz —
o handler neste binário é `mret`. (Registro: `irq_num = 0x21` em `csi_qspi_init` aponta
para o índice 33, que a tabela nomeia `CQDPI`; a numeração IRQ do CQSPI não bate com a
ordem nominal da tabela — **não documentado**, possivelmente CLIC source ≠ índice.)

---

## 3. Sequência de erase/write

### 3.1 Protocolo do CDK (entry → funções)

O `main` (`0x02000630`) lê uma struct de comando em SRAM e despacha por `g_func`:

| símbolo | endereço | papel |
|---|---|---|
| `g_checksum` | `0x020040c4` | argumento de `flashChecksum` |
| `g_dstAddress` | `0x020040c8` | **endereço na flash** (ex. `0x08100000`) |
| `g_error` | `0x020040cc` | retorno |
| `g_flashID` | `0x020040d0` | saída do comando 0 |
| `g_func` | `0x020040d4` | comando 0..6 |
| `g_length` | `0x020040d8` | tamanho |
| `g_rwBuffer` | `0x020040dc` | buffer de **8192 bytes** (a transferência é em blocos ≤ 8 KB) |

Comandos: `0` ID, `1` program, `2` read, `3` erase, `4` chip-erase,
`5` uninit, `6` checksum (`main`, casos em `0x02000676`..`0x02000742`).

Wrapper do CDK, `driver.c` (todas com `tDst = dst - (16 << 23)` = `dst - 0x08000000`,
confirmado pelo `DW_AT_GNU_call_site_value` em `0x00003878`):

| função | addr | observação |
|---|---|---|
| `flashInit` | `0x0200075e` | chama `csi_spiflash_qspi_init(&spiflash, 0, NULL)`; erro = `-200` |
| `flashProgram` | `0x0200078a` | se `dst - 0x08000000 > 0x1000000` → **`memcpy` puro** e retorna 0 (endereço fora da flash = "grava" em SRAM/HyperRAM); senão `csi_spiflash_program` |
| `flashRead` | `0x020007ea` | mesma guarda; `flashRead(dst, src, len)` com `src` = flash |
| `flashErase` | `0x0200084e` | mesma guarda — fora da janela **retorna 0 sem fazer nada**; erro `-1` |
| `flashChipErase` | `0x0200088a` | `-1` |
| `flashChecksum` | `0x020008b0` | **stub: `return 0`** |
| `flashID` | `0x02000786` | **stub: `return 0`** |
| `flashTest` | `0x020008b4` | stub |
| `spiflash` | `0x020060dc` | `csi_spiflash_t` de 204 bytes (`.bss`) |

Nota para o `RE-acf.md`: `flashChecksum` devolver 0 sempre significa que **nem o caminho
de gravação do fabricante valida checksum algum** — corrobora o FATO 7 ("o firmware não
valida checksum"). O checksum do `.acf` é calculado/validado em outro lugar (ou em
lugar nenhum).

### 3.2 ERASE — a cadeia real

```
flashErase(0x0200084e)
 └─ csi_spiflash_erase(0x02001856)            ; só aceita bus QSPI; SPI → CSI_UNSUPPORTED
     └─ qspiflash_erase(0x020016e8, SECTOR_ERASE)
```

`qspiflash_erase` (decompilado com nomes do DWARF: `erase_addr`, `erase_end_addr`,
`erase_sectors`, `erase_size`, `erase_opcode`):

1. `csi_qspi_write_protection_ctrl(qspi, false)` → limpa bit1 de `0x40100000+0x58`
   (`qspi_write_protection_ctrl @ 0x0200252a`).
2. `erase_size` e `erase_opcode` saem da tabela SFDP lida na init
   (por tipo: `SECTOR_ERASE`→`sector_size`+`opcode.erase_sector`;
   `HALF_BLOCK_ERASE`→`block_size/2`+`erase_half_block`;
   `BLOCK_ERASE`→`block_size`+`erase_full_block`;
   `CHIP_ERASE`→`capacity`+`erase_chip`).
3. `erase_sectors = ceil(size / erase_size)`.
4. Laço `while (i < erase_sectors && (addr & 0xFFFFF000) <= offset + size)`:
   - `qspiflash_send_opcode(spiflash, opcode.write_enable)` → **WREN 0x06**
     (`qspiflash_send_opcode @ 0x02000ff6`: `csi_qspi_command_t` só com instrução,
     sem endereço/dados → `csi_qspi_send`);
   - `command.address.size = addr & 0xFFFFF000` (o campo se chama `size` na union, mas
     carrega o **valor do endereço**)
     ⚠️ **o endereço é truncado em 4 KB, sempre**, mesmo que `erase_size` seja 64 KB
     (`qspiflash_erase`, `0x02001780`–`0x0200178c`: `lui a3,0xfffff; and a3,a5`);
   - `csi_qspi_send(qspi, &cmd, NULL, 0, -1)` → `qspi_send_cmd @ 0x02002578`
     (programa `0x90`/`0x94`, `0x90 |= 1` para disparar, espera `0x90 & 2` limpar);
   - faz **polling do status**: `csi_spiflash_read_reg(spiflash, opcode.read_sr1, &SR, 1)`
     em laço enquanto `SR.SR1 & 1` (WIP) ≠ 0;
   - `addr += erase_size`, `i++`.
5. `csi_qspi_write_protection_ctrl(qspi, true)`.

`csi_spiflash_chip_erase` (`0x02001872`) é o mesmo caminho com `type = CHIP_ERASE`,
`offset = 0`, `size = 0`: WREN + opcode `erase_chip` (= `0x60` fixo, ver §3.4) + poll.

### 3.3 PROGRAM — a cadeia real

```
flashProgram(0x0200078a)
 └─ csi_spiflash_program(0x02001654)
     ├─ csi_qspi_write_protection_ctrl(qspi, false)
     ├─ csi_qspi_direct_send(0x02000dec)        ; "direct" = modo write-through da janela
     │   ├─ csi_qspi_direct_mode_config(0x02000d2e, QSPI_WRITE)
     │   │    → qspi_set_spi_mode_base(0x020022f2)  (0x04/0x08)
     │   │    → qspi_cfg_reads/writes(0x020021a0)   (opcode de write no 0x08)
     │   │    → qspi_cfg_addr_bytes / page_size / block_bytes (0x14)
     │   └─ qspi_direct_access_write(0x02002828)
     │        → **stores de 32 bits em `0x08000000 + offset`**
     ├─ loop: csi_spiflash_read_reg(opcode.read_sr1) até WIP=0
     ├─ csi_qspi_write_protection_ctrl(qspi, true)
     └─ csi_qspi_direct_mode_config(qspi, cfg, QSPI_READ)   ; volta pro modo XIP
```

Detalhes que importam:

- **Escrita não usa comando explícito**: `qspi_direct_access_write` faz
  `*(uint32_t*)(remap_bus_base + offset + i) = *(uint32_t*)(src + i)` e o
  `remap_bus_base` é `0x08000000` (`cqspi_dev_cfg @ 0x02002df0`). Quem traduz store em
  página de flash é o controlador, configurado com o opcode de page program.
- **WREN explícito não aparece no caminho de program** (só no de erase).
  **HIPÓTESE**: o CQSPI emite `0x06` automaticamente antes de cada página; o que o
  código faz é só habilitar/desabilitar a proteção de escrita do controlador
  (`0x58` bit1). **NÃO DOCUMENTADO** — o `.elf` não mostra o WREN da página.
- O baud rate é **rebaixado para `div = 8`** durante a escrita e restaurado no fim
  (`qspi_get_baud_rate_div`/`qspi_set_baud_rate_div`, `0x02002238`/`0x02002248`).
  Com PLL 480 MHz (`SystemInit`), leitura roda a 120 MHz (`get_qspi_freq_max @ 0x02000eda`
  devolve 120 MHz com PLL 480 MHz, 108 MHz com 432 MHz, 72 MHz com 288 MHz) e a escrita
  a ~60 MHz (480/8) — valor derivado, não constante no binário.
- O `page_size` da SFDP é programado **no hardware** (`0x14` bits 4–15); é o
  controlador que quebra a escrita em páginas. O software não alinha nada.
- **Bug/limitação do laço de erase**: a condição de parada usa
  `(addr & 0xFFFFF000) <= offset + size`; um range que termina no meio de um setor
  apaga o setor inteiro. Some com o truncamento de endereço e o resultado é:
  **erase de 1 byte pode apagar 4 KB.**

### 3.4 Comandos JEDEC — de onde vem cada opcode

Tudo isso é montado em `SFDP_flash_read_parameter @ 0x0200107c`
(é a função que enche `flash_prv_info` e `spiflash->opcode`, structs descritas em
`0x000033c3` e `0x0000353e` do DWARF).

**Fixos no código:**

| comando | opcode | coordenada |
|---|---|---|
| Write Enable | `0x06` | `(spiflash->opcode).write_enable = 6` |
| Write Enable VSR | `0x06` ou `0x50` | depende de SFDP DWORD0 bit `0x10` |
| Read SR1 / SR2 / SR3 | `0x05` / `0x35` / `0x15` | idem |
| Write SR1 / SR2 / SR3 | `0x01` / `0x31` / `0x11` | idem |
| Chip Erase | **`0x60`** | `(spiflash->opcode).erase_chip = 0x60` |
| Enable Reset / Reset | `0x66` / `0x99` | `csi_spiflash_qspi_init @ 0x020018de` |
| SFDP Read | `0x5A` | `qspiflash_get_SFDP_by_addr @ 0x02001036` |
| Enter 4-byte address | `0xB7` | só se SFDP+0x3C bit24 **e** `addr_4_byte` → >128 MB |
| Mode-444 disable / enable | `0xFF`/`0xF5` e `0x38`/`0x35` | SFDP+0x38 |

**Lidos da SFDP (tabela JEDEC Basic Flash Parameter, ponteiro em SFDP+0x0C):**

| campo | origem | valor típico (inferência da norma SFDP) |
|---|---|---|
| 4 KB erase opcode | byte1 do DWORD em `+0x00`, se `(dword & 3) == 1` | `0x20` |
| `sector_size` | `1 << (byte0(+0x1C) & 0x1F)` | 4096 |
| `erase_sector` opcode | byte1 de `+0x1C` | `0x20` |
| `erase_half_block` opcode | byte3 de `+0x1C` | `0x52` (32 KB) |
| `block_size` | `1 << (byte0(+0x20) & 0x1F)` | 65536 |
| `erase_full_block` opcode | byte1 de `+0x20` | `0xD8` (64 KB) |
| `page_size` | `1 << ((byte(+0x28) >> 4) & 0xF)` | 256 |
| `capacity` | DWORD em `+0x04` (densidade em bits; MSB→`1<<(n-3)`) | 16 MB |
| opcode/dummy de leitura | DWORD em `+0x00` (1-4-4 / 1-1-4 / 1-1-2) | `0xEB` / `0x6B` / `0xBB` |
| opcode de page program | derivado do modo de escrita: `0x02` (1-1-1), `0x32` (1-1-4), `0x3E` (1-4-4) | — |

Validado na init: `SFDP` magic `0x50444653` em `0x0` e revisão menor ≤ 1 em `0x4`;
o ponteiro da tabela JEDEC precisa ser `< 0xFF` (macro `CSI_IS_SFDP_PTP_BASE_ADDR(ADDR)`
`((ADDR) < 0xFF)`, presente em `.debug_str`).

Fluxo de clock da init: **reset (`0x66`,`0x99`) e leitura da SFDP a 2.5 MHz**
(`get_qspi_freq_min` = PLL/0xC0), depois sobe para **120 MHz** e roda
`qspi_adapted_capture @ 0x020028fc`, que varre delays de amostragem com o comando
**`0x9F` (Read JEDEC ID)** — é a única leitura de ID de flash no binário inteiro.
No fim a init lê 8 bytes do endereço 0 e exige que a leitura funcione
(`csi_spiflash_read(spiflash, 0, buf, 8)`).

### 3.5 Alinhamento e tamanho de setor — resumo

| item | valor | base |
|---|---|---|
| setor de erase | vem da SFDP; **4 KB** é a premissa do código | `local_58 & 0xFFFFF000` em `qspiflash_erase` |
| bloco | vem da SFDP (64 KB típico) | `flash_info->block_size` |
| página | vem da SFDP (256 B típico), aplicada no HW | `0x14` bits 4–15 |
| alinhamento exigido pelo software | **4 KB** (por causa da máscara) | `0x02001784` |
| alinhamento do `.acf` | **16 KB** = exatamente 4 setores de 4 KB | `RE-acf.md` FATO 2 |
| chunk do CDK | ≤ 8 KB | `g_rwBuffer` = 8192 B em `0x020040dc` |
| janela de flash | `0x08000000` .. `0x08FFFFFF` (16 MB) | guarda `dst - 0x08000000 > 0x1000000` em `flashProgram`/`flashErase` |

O `0x1000000` (16 MB) na guarda é o **limite da janela de endereçamento** do driver,
não o tamanho da flash. Um endereço fora dela cai no `memcpy` (o algoritmo "grava" em
RAM — é assim que o CDK carrega o próprio algoritmo, inclusive).

---

## 4. Tabela de flash suportada (`FLASH_ID_IS_*`)

Recuperada de `.debug_str` (macro dump do `-g3`; as definições estão preservadas como
texto, ex. `FLASH_ID_IS_NOR_16MB(_ID_) (((_ID_) == 0x001840EF) || ...)`):

| macro | IDs (u32, como lido LE de 4 bytes) |
|---|---|
| `FLASH_ID_IS_NOR_4MB` | `0x20164020`, `0x5E16405E` |
| `FLASH_ID_IS_NOR_8MB` | `0x001740EF`, `0x001770EF`, `0xC81740C8`, `0x68174068`, `0x20177020` |
| `FLASH_ID_IS_NOR_16MB` | `0x001840EF`, `0x001870EF`, `0xC81840C8`, `0x68184068`, `0x20187020`, `0x5E18405E` |
| `FLASH_ID_IS_NOR256_32MB` | `0x001940EF`, `GD25Q257D` = `0x001940C8` |
| `FLASH_ID_IS_GD_NAND_Q4_125MB` | `0xC848B1C8` |
| `FLASH_ID_IS_GD_NAND_Q5_125MB` | `0xC841C8FF`, `0xC851C8FF` |
| `FLASH_ID_IS_DS_NAND_125MB` | `0xE571E5FF` |
| `FLASH_ID_IS_WB_NAND_125MB` | `0x21AAEFFF` |

Decodificação (LE, 4 bytes do comando `0x9F`): `[fabricante, tipo, capacidade, ...]`.
O byte de capacidade é a potência de dois em bytes: `0x16`=4 MB, `0x17`=8 MB,
`0x18`=16 MB, `0x19`=32 MB. Fabricantes: `0xEF` Winbond, `0xC8` GigaDevice,
`0x68` Boya, `0x20` Micron/XTX, `0x5E` Zbit, `0xFF`/`0x21` (NAND).
Ex.: `0xC81840C8` → bytes `C8 40 18 C8` = GigaDevice, `0x18` = **16 MB** (GD25Q128).

**O que isso NÃO prova:** estes macros são **definições de header, não código**. Nenhum
`lui/addi` do `.text` constrói `0x001840EF`/`0xC81840C8`/etc., e nenhuma função compara
`flash_id` com eles (busca negativa em todo o `.text`). Ou seja: **este build não usa a
tabela de IDs** — ele é 100% SFDP. A tabela só documenta os parts que o SDK conhece.

Prova de que o descritor é template, não a peça real: `FlashDevices` (`DevDscr`
off `0x7a60`, tipo `const FlashDevice` com 0x734 bytes, `0x00003b67` no DWARF):

```
Ver         = 6
DevName     = "9002flash"
CPU         = "9002"
FlashID     = 0x00123456      ← placeholder óbvio
FlashType   = "NorFlash"
TotalSize   = 0x00080000      (512 KB)
IsAccDirect = 1
rangeNumbers= 1
Devs[0]     = { Start=0x08000000, Length=0x30000000, PageSize=0x1000 }
```

`TotalSize` (512 KB) e `Length` (768 MB) são incompatíveis entre si e com a placa —
são campos que o CDK sobrescreve/preenche em runtime (**NÃO DOCUMENTADO** o que o CDK faz
com eles; o `0x30000000` não fecha com nenhuma geometria plausível).

**Sobre o tamanho da flash da minitela:** o mapa que o app oficial usa
(`minitela_ctl.py`, linhas 74–80, copiado do `electron.js` do MiniPanel) tem
`bootloader 0x08000000`, `texture 0x08100000`, `texture_gif 0x08500000`. Para caber o
`texture_gif` em `0x08500000` a flash precisa de **≥ ~6 MB**, então entre os NOR
suportados só sobra **8 MB ou 16 MB**. 16 MB é o mais provável: é o único com **6**
IDs listados (cobertura de 5 fabricantes) e é o único cujo byte de capacidade (`0x18`)
deixa o `.acf` de 6,4 MB (`MAX_FILE_BYTES = 6436*1024`) caber a partir de
`0x08100000` sem colidir com o bloco de config em `0x080F7000`. **HIPÓTESE** — a
confirmação é ler o JEDEC ID (`0x9F`) no aparelho, operação humana.

---

## 5. CRC32 em `0x40108000`

Fatos, todos verificáveis:

| fato | coordenada |
|---|---|
| `CRC32_BASE (0x40108000UL)` existe | macro em `.debug_str` |
| `CRC32_Typedef`/`CRC32` são referenciados como tipo/macro | `.debug_str` (`CRC32 (CRC32_Typedef *)CRC32_BASE`) |
| `CRC32_IRQn` e `CRC32_IRQHandler` existem | `.debug_str`; handler em `0x02000b76` = **`mret`** (4 bytes) |
| o vetor 39 aponta para ele | `__Vectors[39] = 0x02000b76` em `0x02002e9c` |
| **nenhum acesso a `0x40108000` no código** | todos os `lui` do `.text` dão `0x2004/0x2006/0x2007/0x1000/0x40200/0xe0800/0xf8000/0xe4e2/0xe000c/0x40100/0x40101/0x40102/0x4010c/...` — não existe `0x40108` |

Portanto:

- **O polinômio não é observável neste binário. NÃO DOCUMENTADO.** Não há rotina de
  CRC, nem escrita de `init`/`poly`/`xorout`. Só dá para dizer que o bloco de hardware
  existe no SoC e que o `flash_download.elf` o ignora completamente.
- **Não é o checksum do `.acf`.** O `.acf` usa XOR de words de 32 bits LE, pulando o
  próprio campo e o footer `0xA55A5AA5` (`RE-acf.md` FATO 6). Isso não é CRC32 sob
  nenhum polinômio: não tem polinômio, não tem `init`/`xorout`, não tem reflexão de
  bits, e o invariante medido ("XOR de todas as words == `0xA55A5AA5`") é uma
  propriedade de XOR (comutativo, ordem-independente), não de CRC (onde o resíduo é
  fixo e **não** depende do dado — e aqui o resíduo é o magic do rodapé).
- Corroboração independente: `flashChecksum @ 0x020008b0` é `li a0,0; jr ra`. O caminho
  de gravação do fabricante **não valida checksum nenhum**. Se o CRC32 de hardware é
  usado em algum lugar, é no firmware AHMI (que não temos), não aqui.

---

## 6. O que isso explica sobre a minitela

1. **`0x08000000` é literalmente `CQSPI_DATA_BASE`.** O `Texture.acf` em `0x08100000`
   é o offset `0x100000` da mesma NOR, na mesma janela que o CPU lê como memória
   normal. Leitura de textura é **XIP**: `csi_spiflash_read` só faz
   `qspi_remap_addr(dev,0)` e lê `0x08000000 + offset`
   (`qspi_direct_access_read @ 0x02002762`). Não existe comando de leitura por chunk
   no caminho quente.
2. **Gravar é sempre erase-de-setor + page program.** Não há escrita parcial em NOR.
   Qualquer alteração, mesmo de 1 byte, obriga a apagar 4 KB e reescrever. Isso explica
   mecanicamente o dano colateral do FATO 7 do `RE-acf.md`: patch em `753192` cai no
   meio de um setor e o setor inteiro vai junto.
3. **Pior ainda: o driver trunca o endereço de erase em 4 KB**
   (`addr & 0xFFFFF000`) e o laço continua enquanto `(addr & 0xFFFFF000) <= offset+size`.
   Se o firmware AHMI usar esta mesma HAL (mesmo SDK, strings
   `../../../csi_driver/csi_spiflash.c` em `.debug_str`), um "erase de N bytes" apaga
   `ceil(N/4096)` setores a partir do setor que contém o primeiro byte.
   **HIPÓTESE** para o firmware da tela; **FATO** para este binário.
4. **16 KB do container = 4 setores exatos.** O alinhamento do `.acf` não é exigência
   da flash; é decisão do container que, por coincidência (ou não), casa com 4 setores.
5. **A transferência do app é em blocos ≤ 8 KB** (o `g_rwBuffer` do CDK tem 8192 bytes).
   Isso é consistente com o `UPLOAD_DATA` fatiado do AHMI observado no `minitela_ctl.py`.
6. **A geometria é lida da SFDP em runtime**, não de tabela de IDs. Consequência
   prática: o mesmo firmware serve 4/8/16/32 MB; não dá para inferir o part pelo
   firmware, só pelo SFDP/JEDEC ID do aparelho.
7. **O caminho de gravação do fabricante não verifica checksum** (`flashChecksum` stub).
   Bate com o teste do `RE-acf.md` em que um `.acf` com checksum antigo continuou
   bootando.

### O que continua em aberto

- **Qual é a flash** (fabricante/capacidade). Precisa de `0x9F` no device — operação
  humana, com recuperação armada. Este `.elf` não responde.
- **O firmware AHMI usa esta HAL?** As strings de build (`csi_driver/csi_spiflash.c`,
  `gc9002_ll_qspi.c`, `gc9002_hal_hyper.c`) mostram que o SDK é o mesmo; a prova
  exigiria o dump do firmware da tela.
- **Polinômio do CRC32 de hardware** (`0x40108000`): não está em nenhum artefato que
  temos. Se o firmware AHMI usar, aparece no dump dele.
- **`AHMI_IRQHandler` (vetor 37)**: o SoC tem um bloco AHMI com interrupção própria.
  Saber o que ele faz ajudaria a mapear o protocolo, mas neste binário o handler é
  `mret`.
- **`Devs[0].Length = 0x30000000` e `TotalSize = 0x80000`**: campos inconsistentes do
  descritor; não documentado como o CDK os usa.
- **WREN no page program**: o `.elf` não emite; presumo que o controlador emita
  (HIPÓTESE). Um teste no hardware (escrever e ler o SR1 antes/depois) resolve, mas é
  operação humana.

---

## 9. O protocolo no código-fonte do SDK (v1.10.20)

A partir daqui a fonte é o SDK com código: `.tools/vendor/sdk120/v1.10.20_2025.07.02_GC9002/`.
Para encurtar as citações:

- `$SDK` = `.../GC9002/GC9002/GC9002LIB`
- `$CS`  = `.../GC9002/GC9002/CommonSource`

Tudo abaixo é leitura de código/binário. Nada foi executado.

### 9.1 Onde o `AH`…`MI` está — e onde **não** está

O protocolo com `'A','H'` / `'M','I'` e os comandos `0x0080`…`0x008F` existe em **um único
lugar** neste SDK: o **bootloader**, em
`$SDK/projects/Bootloader/Source/Upgrade/core/upgrade_uart_platform.c`, com transporte
**UART** (`HAL_UART_Receive_IT`/`HAL_UART_Transmit_IT`).

No firmware de **aplicação** (`projects/AHMI_SW`) ele **não existe**. Evidências:

| verificação | resultado |
|---|---|
| `grep -rn "UPG_CMD" $SDK/projects/AHMI_SW` | zero ocorrências |
| `grep -rn "0x0080\|0x0081\|…\|0x008F" $SDK/projects/AHMI_SW $CS --include=*.c,*.cpp,*.h` | nenhum hit de comando (só `ActionProcessor.h:122-148`, que são códigos de animação, e o CRC do protocolo 0xA5/0x5A) |
| mapa de link do app `$SDK/projects/AHMI_SW/Lst/GC9002AHMI.map` | só 7 linhas casam `upgrade|UPG`, todas de **gzip** (`upgrade_block`, `upgrade_InterGzip_block`) ou `UpgradeProductPara` — nenhum `UPG_UART_vParseCmd`, nenhum `UPG_PAS_*` |
| varredura do `.text` do app (`Obj/GC9002AHMI.elf`, 0xA4D30 bytes, entry `0x08040060`) | nenhuma comparação com `0x4148`/`0x494D`, nenhum `li …,65/72` seguido de `li …,73/77` que forme parser. Os hits de `li a0,65/72/73/77` em `0x080907xx` são o init do sensor **OV7670** (`OV7670_Init @ 0x0809029c`, writes I²C) |
| hook do cliente | `$SDK/projects/AHMI_SW/CustomerApp/CustomerAppMain.c:11-20` — `CustApp_vInitEnterance()` **vazio**; chamado por `main.cpp:107-109` |

O que o app **tem** de link com host:

1. **Protocolo de registradores 0xA5/0x5A** (UART), documentado em
   `$SDK/projects/AHMI_SW/Source/ahmi/ahmi_com_protocol/ahmi_com_prot.md:3-20`:
   frame `0xA5|0x5A` + versão + flags + função + nº de registros + dados + CRC16-MODBUS
   + `0xC3`. Nada a ver com o nosso (`0xA5` = 底板→módulo, `0x5A` = módulo→底板).
2. **USB CDC de demonstração**: `$SDK/libs/GC9002_HAL_Driver/Src/gc9002_hal_usbd.c`.
   O callback de recepção **descarta os dados**:
   `usbd_cdc_acm_bulk_out()` (`:121-129`) só rearma `usbd_ep_start_read(CDC_OUT_EP,
   read_buffer, 128)`; `read_buffer` (`:99`) nunca é interpretado. VID/PID são
   `0xFFFF/0xFFFF` (`:24-25`), não `0324:0324`. E `cdc_acm_init()` (`:156-165`) **não é
   chamada em lugar nenhum** da árvore do bootloader nem do app (grep) — está linkada e
   morta.

**Conclusão (com etiqueta):** neste SDK o protocolo `AH`…`MI` é o protocolo de
**upgrade do bootloader sobre UART**. O firmware que responde em `0324:0324` (CDC-ACM) com
o conjunto `0x0070/0x0071/0x0080/0x0081/0x0082/0x0083/0x0085/0x0086/0x008F/0x0090` **não é
este** — é um build do ODM que este SDK não contém (**HIPÓTESE**, mas o conjunto de
evidências acima é fechado para o que está no pacote).

### 9.2 Formato do frame, direto da fonte

| campo | tamanho | detalhe | coordenada |
|---|---|---|---|
| head | 2 | `'A'` no offset 0, `'H'` no offset 1 | `upgrade_uart_platform.h:19-32`, `.c:309`, `.c:323` |
| ctrl | 2 | `len:11` (inclui cmd+content), `res:4`, `crcEn:1` (bit 15); transportado **big-endian** | `.h:115-124`, `.h:72-80`, `.c:338-342` |
| cmd | 2 | big-endian | `.h:35`, `.c:371-372` |
| content | `len-2` | | `.h:36-39` |
| tail | 2 | `'M'`,`'I'` em `TAIL_OFFSET(len)` = `CMD_OFFSET + len` | `.h:39`, `.c:357-364` |
| reply | — | mesmo frame, com `cmd = cmd + 0x40` e **4 bytes** de conteúdo (u32 BE) | `.h:69`, `.c:405-437` |

O bit `crcEn` é **ignorado na recepção** (`.c:341-342`: "Ignore the CRC Enable bit") e
nunca é setado na resposta (`.c:421`: "CRC not used"). É exatamente o que o
`minitela_ctl.py:12-15` já dizia (`crc = 0x0000`).

Limite de dados por frame de download: **64 B** de dados (`UPG_UART_DOWNLOAD_MAX_DATA_LEN`,
`.h:49`), com `len ≤ 70` no parser (`UPG_UART_DOWNLOAD_MAX_CONTENT_LEN = 2 + 4 + 64`,
`.h:57-60`, `.c:344`). É por isso que o `g_rwBuffer` de 8 KB do flash algorithm (§3.1)
nunca é usado inteiro por este caminho.

### 9.3 O dispatcher

`UPG_UART_vParseCmd()` — `upgrade_uart_platform.c:453`, `switch` em `:464`.

| cmd | handler | semântica | linha |
|---|---|---|---|
| `0x0080` | `UPG_SUBSM_PAS_vUartWork()` + reply | marca `bFlagUartWork = TRUE` (a SM passiva sai de "FirstIn"); responde `u32 maxPackageSize = 64` (BE) | `.c:466-474`, `upgrade_subsm_passive.c:220-223` |
| `0x0081` | `UPG_PAS_i32SetUpgFileAndSize(addr, size)` | `addr` e `size` BE→LE; **`addr` tem que ser exatamente um dos destinos da tabela**; **apaga a região inteira** antes de responder; resposta = `res` | `.c:476-492`; `upgrade_passive.c:269-341` |
| `0x0082` | `UPG_PAS_i32GetData(payload, len-6)` | conteúdo = `u32 offset` (BE) + dados (máx. 64 B); o **offset é ignorado** ("Currently no use of offset", `.c:497`) e só serve para dedup por `u16LastOffset` (`:501-516`); resposta = `res` | `.c:494-525` |
| `0x008F` | reply `0` + `UPG_SUBSM_PAS_vCanUartRunQuit()` | encerra: a SM passiva vai para `CanUart_Quit` → `JumpToApp` | `.c:527-535`; `upgrade_subsm_passive.c:202-208` |
| outro | — | silêncio (sem NAK) | `.c:536-538` |

Se a escrita/erase demorar, um timer de serviço responde `0xFFFFFFFF` (`UPG_REPLY_DELAY_FLAG`)
para o cmd corrente a cada 30 s (`upgrade_uart_platform.h:70,82-85`; `.c:442-450`).

### 9.4 Como o byte vira flash

1. `0x0081` → `UPG_PAS__i32SetUpgFileAndSize()` percorre a tabela `UPG_astPrebuildConfig`
   (`upgrade_ci.h:148-159`, gerada de `UPG_PRECONFIG`) comparando o `addr` recebido com
   `pstPbConfig[i].pu8UpgFlashStartAdress`. **Não bate = `EM_enErrInAddrInvalid`, nada é
   escrito** (`upgrade_passive.c:274-330`).
2. Ainda dentro do `0x0081`, `UPG_PAS__i32EraseFlash()` **apaga o arquivo inteiro** antes
   do primeiro byte de dados (`upgrade_passive.c:334-335`).
3. Cada `0x0082` acumula em `myUpgradebuffer` (2048 B, `upgrade_c1.h:45`) e descarrega
   quando enche; a escrita escolhe a HAL pelo endereço (`upgrade_passive.c:422-446`):
   `[0x08040000,0x08100000)` → `csi_hal_internal_flash_write`; `[0x08100000, +maxTexture)`
   → `csi_hal_extern_flash_write`. No GC9002 **as duas são a mesma função**
   (`csi_hal_driver_flash.c:440-456`) — um só chip QSPI.
4. `0x008F` responde 0 e manda o bootloader saltar para o app.

Destinos graváveis (tabela compilada, `upgrade_ci.h:148-159`):

| arquivo | endereço | observação |
|---|---|---|
| `bootloader.bin` | `BOOTLOADER_SAVE_ADDR` = `0x083C0000` (ou `0x08000000+TextureFlashSize-0x40000`) | **self-upgrade**: só é copiado para `0x08000000` no `JumpToApp` |
| `Texture.acf` | `TEXTURE_START_ADDRESS` = **`0x08100000`** | `upgrade_ci.h:109-110` — igual ao nosso `minitela_ctl.py:74` |
| `VectorFont.acf` | `0x80000000` | |
| `CmpGIF_N.acf` | `0x80000000 + N*2 MB` (64 slots) | `upgrade_sm.c:137-156` |
| `cpu1.bin` | `0x08040000` | o app |
| `product.bin` / `hwconfig.bin` | `0x080FF008` / `0x080FE008` (`BANK_WRITE_START_ADDR_* + 8`, `ParsePara.h:20,25`) | iguais ao mapa do `minitela_ctl.py:72-73` |
| `calibration.bin`, `EraseStoreSpace.bin` | `0x080FB000` / `0x080FC000` (`ParsePara.h:16`, `upgrade_ci.h:120`) | |
| `cpu0_config.bin` | `0x080F8000` | |
| `upg_cfg.bin` | **`0x080F7000`** | `upgrade_ci.h:116` |

O limite de tamanho do `.acf` no **bootloader** é `TextureFlashSize - 0x100000`
(`upgrade_c1.c:74-86`), e não os `MAX_FILE_BYTES = 6436 KB` do app: num part de 16 MB isso
dá 15 MB; se o bootloader não reconhecer o ID (ver §12.3) cai para 3 MB
(`TextureFlashSize` default `0x400000` em `csi_hal_driver_flash.c:9`).

---

## 10. Comandos implementados × `minitela_ctl.py`

`minitela_ctl.py:39-63` define 10 comandos (+ respostas). O que o SDK implementa:

| cmd | nome no python | SDK (bootloader UART) | resposta | veredito |
|---|---|---|---|---|
| `0x0080` | HANDSHAKE | ✅ `.c:466` | `0x00C0` | **bate** (mas o payload é `u32=64`, não um "status") |
| `0x0081` | REQUEST_DOWNLOAD | ✅ `.c:476` | `0x00C1` | **bate** |
| `0x0082` | DOWNLOAD_DATA | ✅ `.c:494` | `0x00C2` | **bate** (máx. 64 B/frame) |
| `0x008F` | DOWNLOAD_COMPLETE | ✅ `.c:527` | `0x00CF` | **bate** — e **derruba** o bootloader para o app |
| `0x0083` | UPLOAD_DATA | ❌ só o `#define` (`.h:66`), sem `case` | — | **sobra no SDK** (§12) |
| `0x0085` | GET_DOWNLOAD_STATUS | ❌ não existe | — | **sobra** |
| `0x0086` | GET_OFFSET | ❌ não existe | — | **sobra** |
| `0x0070` | REBOOT | ❌ não existe | — | **sobra** |
| `0x0071` | SWITCH_STATE | ❌ não existe | — | **sobra** |
| `0x0090` | SET_REGISTER | ❌ não existe | — | **sobra** |

Observações que fecham o quadro:

- Todas as respostas do python seguem `cmd + 0x40` (`0x0080→0x00C0`, `0x0090→0x00D0`,
  `0x0070→0x00B0`, `0x0071→0x00B1`), que é exatamente a regra do SDK
  (`upgrade_uart_platform.h:69`). Ou seja: **o python e o SDK são a mesma família de
  protocolo**, e o firmware da minitela é um **superconjunto** do bootloader do SDK.
- Os 6 comandos que sobram são justamente os de **runtime** (`0x0071` troca de página,
  `0x0090` seta registro, `0x0070` reboot, `0x0085`/`0x0086` acompanham o download) e o
  `0x0083` de leitura. Nenhum deles tem implementação neste SDK, nem no app nem no
  bootloader.
- O SDK tem, no app, o equivalente **funcional** de `0x0090`/`0x0071` — mas por outro
  protocolo (0xA5/0x5A, registradores `IDE_SYSTEM_REG_*`, `GeneralCom_Moduleinfo.h:17-31`
  e `MODULE_INFO_REG_*:53-104`), e não pelo frame `AH`…`MI`.

### 10.1 Diferenças finas entre o `minitela_ctl.py` e o SDK

O python é mais novo que o bootloader deste SDK. Onde os dois divergem:

| detalhe | SDK (`upgrade_uart_platform.c`) | `minitela_ctl.py` |
|---|---|---|
| conteúdo do `0x0081` | **8 B**: `u32 addr`, `u32 size` (`upgrade_uart_platform.h:140-144`) | **20 B**: `>II` addr+size **+ 16 B de `file_id` (md5)**, `minitela_ctl.py:321`. O SDK copia até 68 B para a union e simplesmente **ignora** o md5 |
| resposta do `0x0081` | **4 B**: `u32 res` (`UPG_tunUartRplContent`, `.h:170-174`) | **8 B**: `>II` `maxPageSize` + `code` (`minitela_ctl.py:323`) |
| "ocupado" | timer de 30 s responde `0xFFFFFFFF` (`UPG_REPLY_DELAY_FLAG`, `.h:70`) | **mesma convenção**: `code == 0xFFFFFFFF` → espera o próximo frame com `code == 0` (`minitela_ctl.py:324-336,347-357`) |
| tamanho de página | fixo em 64 B (`UPG_UART_DOWNLOAD_MAX_DATA_LEN`, `.h:49`) | vem do `maxPageSize` da resposta do `0x0081` |
| `0x0082` | `u32 offset` + dados, offset ignorado (só dedup) | idêntico (`minitela_ctl.py:344`) |

Ou seja: o `0xFFFFFFFF` de "apagando/gravando, espere" é a **impressão digital** que liga o
python ao SDK — mas o resto (md5, `maxPageSize`, `0x0085`, `0x0086`, `0x0070`, `0x0071`,
`0x0090`) é firmware de produção, não este.

O que o python revela da **semântica** dos comandos que faltam (e que o SDK não documenta
em lugar nenhum):

- `0x0085` devolve **21 bytes**: `status` (1) + `file_id`/md5 (16) + `offset` (u32 BE)
  (`minitela_ctl.py:223-228`). `status` `0x20` = UI rodando; `0x10`/`0x11` = em download
  (`:305-318`).
- `0x0071` (`SWITCH_STATE`) com payload `0x10` pede para **sair da UI e entrar em modo
  download** sem reset (`:314`).
- `0x0086` é o `offset` "solto" (o mesmo que já vem no `0x0085`).
- `0x0070` (`REBOOT`) reinicia o módulo → cai no bootloader (§11).

---

## 11. Entrada no bootloader

**Resposta curta.** Neste SDK a entrada no bootloader é uma **janela de tempo no boot**,
não um flag: o bootloader sempre roda primeiro, espera um handshake `0x0080` por
`can_uart_wait_ms` (default 500 ms) e, se ninguém falar, salta para o app. Não há GPIO,
flag em RAM no-init, campo em `upg_cfg.bin` nem comando que mude isso (§11.3). O firmware
de produção tem um caminho extra — `0x0071` põe o **app** em modo download sem reset —,
mas isso não está neste SDK. E, mesmo entrando no bootloader, **não há dump**: o
`0x0083` não tem handler (§12).

### 11.1 Por que o bootloader sempre roda

O bootloader é a imagem em `0x08000000` (`Bootloader.elf`: entry `0x08000000`, `.text`
`0x08000000+0x2FC54`). O `.bin` de produção tem um header de 16 B gerado por
`boot_headInfo_add.sh`:

```
0x00 u32 size     0x04 u32 CRC32(code)
0x08 u32 magic 0x48494948    0x0C u32 0
0x10 code
```

O app fica em `0x08040000` e o seu primeiro setor é o "cartão de visita" lido pelo
bootloader (`od` do `GC9002AHMI.elf`, VMA `0x08040000` = offset `0x400`):

```
0x08040000  "1.10.20_build_2025.07.02.10.45"   <- CPU1_VERSION_ADDRESS
0x08040020  "Jul 22 2025"                      <- compile date
0x08040030  "16:54:23"                         <- compile time
0x08040040  "GC9002"                           <- CPU1_APP_COMPILE_ADDR_STORE_ADDR
0x08040060  entry (APP_FUNCTION_START_ADDR)
```

`main()` do bootloader: `CFG_vInit()` → `HardwareInit()` → `SoftwareInit()`
(`UPG_Main_vInit`) → scheduler (`main.c:89-101`). A primeira coisa que a task de upgrade
faz é `UPG_SUBSM__vGetComMode()` (`upgrade_subsm.c:951`).

### 11.2 A janela de espera (o único mecanismo que existe)

`UPG_SUBSM__vGetComMode()`:

1. se `cfg_sd` → probe de SD/SPI (`:960-982`);
2. se `cfg_can` → init CAN (`:988-996`);
3. se `cfg_uart` → `UPG_UART_vInit()` (UART + task de RX) (`:997-1005`);
4. laço de `CFG_Get_can_uart_wait_ms()` iterações com `vTaskDelay(1)` esperando
   `bFlagCanWork`/`bFlagUartWork` (`:1007-1033`);
5. se nada e `cfg_usb` → `usbh_initialize()` + `checkMSDDevice()` + mount `"2:"`
   (USB **host**, pen drive) (`:1038-1066`);
6. esgotou `UPG_GET_MODE_TRY_TIMES` (=1, `upgrade_ci.h:62`) e `UPG_bIfCpu1HasCode()`
   → `enMainSM = JumpToApp` (`:1068-1080`).

`bFlagUartWork` só é setado quando chega um frame `0x0080` **válido** (parser completo,
`.c:466-468` → `upgrade_subsm_passive.c:220-223`). Ou seja: a entrada no bootloader é
"**reset + handshake dentro da janela**", não um flag.

Defaults do blob compilado (`cfg_autogen_ca.c:8-21`, usado quando `0x080F7000` é inválido):

| campo | valor | significado |
|---|---|---|
| magic/version | `0x41484D49` / `0x0102` | `cfg_ci.h:30-31` |
| `cfg_uart` | **1** | upgrade UART ligado |
| `cfg_can` | 0 | |
| `cfg_sd` | 1 | |
| `cfg_usb` | 1 | (USB **host**/MSC) |
| `can_uart_wait_ms` | **500** | janela de 500 ms |
| `UartCfg` | ch=2, tx=PB9, rx=PB8, baud=3 | **UART2 @ 115200**, `cfg_ca.c:203-226,294-313`, `upgrade_uart_platform.c:134-139` |

Validação do `upg_cfg`: magic + version + soma de 16 bits dos bytes após o header
(`cfg_c1.c:47-73`); se o bloco em `0x080F7000` falhar, o bootloader usa o blob compilado
(`cfg_c1.c:20-35`) — **nunca fica sem config**.

### 11.3 O que NÃO existe (procurei e não há)

| mecanismo | situação |
|---|---|
| flag em RAM no-init | `UPG_u32CanUartUpgFlag` foi **desativado**: `static uint32_t` e o `__attribute__((at(...)))` está comentado (`upgrade_subsm_passive.c:24-25`). Não sobrevive a reset |
| GPIO / boot pin | `HardwareInit()` não lê pino nenhum (`main.c:20-81`); `UsbCfg` tem `usb_ctrl_enable_port/pin` e `insert_check` (`cfg_autogen_ct.h:65-74`) mas os getters (`cfg_autogen_ca.c:252-290`) não são usados pelo upgrade |
| comando "reboot to upgrade" | o app tem `MODULE_INFO_REG_SYSTEM_RESET = 10056`, mas o handler está com o corpo **comentado** (`GeneralCom_Moduleinfo.c:74-80`) → não reseta |
| flag em `upg_cfg.bin` | os campos são só `cfg_uart/cfg_can/cfg_sd/cfg_usb/can_uart_wait_ms` (`cfg_autogen_ct.h:17-25`). Não há one-shot de boot |
| comando do app p/ modo download | **não existe no SDK**. No firmware de produção é o `0x0071` com payload `0x10` (`minitela_ctl.py:314`), que troca o estado de `0x20` (UI) para `0x10/0x11` (download) **sem reset** — ou seja, o app de produção tem um modo de recepção embutido, que este SDK não tem |
| watchdog / reset reason | nada no caminho do bootloader |
| `upg_cfg` gravável por comando | sim: `upg_cfg.bin` é destino válido (`upgrade_ci.h:159`) — mas isso muda o **futuro**, não entra em modo upgrade |

### 11.4 Procedimento (válido **se** o bootloader da minitela for este)

1. Reset (power cycle; um reboot por software também serve, porque o bootloader é quem
   roda primeiro).
2. Em **≤ 500 ms** (`can_uart_wait_ms`), enviar `0x0080` no canal configurado —
   por default **UART2, PB9=TX/PB8=RX, 115200 8N1** (não é o CDC-ACM).
3. Receber `0x00C0` + `u32 64`. A partir daí a SM passiva fica em `CanUart_Run`
   (`upgrade_subsm_passive.c:126-152`) e **não** salta mais.
4. `0x0081 {addr, size}` com `addr` **idêntico** a um destino da tabela (§9.4);
   `0x0082` em blocos de ≤ 64 B; `0x008F` no fim.
5. `0x008F` **derruba** o bootloader para o app — não existe "ficar no bootloader".

### 11.5 Risco

- **Não dá para dumpar** por aqui: não há comando de leitura (§12). O melhor que o
  protocolo faz é responder 4 bytes de resultado.
- `0x0081` **apaga antes de receber** (`upgrade_passive.c:335`). Um `0x0081` para
  `Texture.acf` abortado deixa `0x08100000` apagado → tela sem textura (recuperável
  repetindo o download). Um `0x0081` para `cpu1.bin` abortado apaga o app; o bootloader
  então não acha `"1."` em `0x08040000` (`upgrade_c1.c:1384-1399`) e vai para
  `UPG_enMainSM_Error` (`upgrade_subsm.c:1076-1087`), que **não salta** — só volta a
  funcionar pelo próprio bootloader (UART). É o cenário de "tijolo recuperável".
- `bootloader.bin` é destino válido e escreve em `BOOTLOADER_SAVE_ADDR`; com
  `bFlagUpgWithSelfUpg = TRUE` (`upgrade_ci.h:149`) o bootloader **se sobrescreve em
  `0x08000000`** no `JumpToApp` (`upgrade_sm.c:296-307`). Aqui o tijolo é real.
- `upg_cfg.bin` também é gravável: um `cfg_uart=0` + reset **fecha a porta de
  recuperação** (sobra só SD/USB-host).
- O `addr` do backup do bootloader depende de `TextureFlashSize`
  (`upgrade_sm.c:161-168`), que depende do JEDEC ID lido no boot (§12.3) — em part não
  reconhecido ele usa o default de 4 MB.

---

## 12. Leitura de flash: veredito

### 12.1 Não existe comando de leitura no SDK

| caminho | comandos | leitura de flash/memória? |
|---|---|---|
| bootloader, `AH`…`MI` | `0x0080/0x0081/0x0082/0x008F` | **não** |
| bootloader, CAN/UDS | SID `0x10`, `0x11`, `0x28`, `0x64/0x66/0x67` (`$SDK/projects/Bootloader/Source/CAN_Diag/SRV/SIDSource/`) | **não** (nem `0x22` ReadDataByIdentifier, nem `0x23`/`0x34`/`0x36`/`0x37`) |
| app, `0xA5/0x5A` | set/get de **registrador AHMI** (`GeneralComExe.c:267,428,509,551`) | **não** — IDs 10000…11000 são estado/versão/backlight/RTC (`GeneralCom_Moduleinfo.h:53-104`); nenhum mapeia flash |
| app, USB CDC | nenhum (callback descarta, §9.1) | **não** |

O único dado "de leitura" que o protocolo devolve são os 4 bytes de resultado
(`UPG_tunUartRplContent`, `upgrade_uart_platform.h:170-174`): tamanho de pacote no
handshake e código de retorno nos demais.

### 12.2 `UPG_CMD_UPLOAD` — confirmado morto

- **Definição:** `upgrade_uart_platform.h:66` — `#define UPG_CMD_UPLOAD (0x0083)`.
- **Uso:** zero. O `switch` de `UPG_UART_vParseCmd` (`upgrade_uart_platform.c:464-540`)
  tem só 4 `case` e um `default` mudo.
- **Confirmação no objeto:** no `projects/Bootloader/Obj/core_upgrade_uart_platform.o`,
  a seção `.text.UPG_UART_vParseCmd` (`llvm-readelf -S`: seção 129) desmonta para
  `li a4,130` / `bltu a4,a5,…` / `li a4,128` / `li a4,129` — os casos `0x82`, `>0x82`
  (`0x8F`), `0x80` e `0x81`. **Não existe comparação com `0x83`.**
- **Nenhum handler em outro lugar:** `nm` em todos os `Obj/*.o` do bootloader não devolve
  nenhum símbolo com "upload"; `grep -rl UPG_CMD_UPLOAD` só encontra o header e arquivos
  `.o`/`.elf` onde a string aparece no **dump de macros do `-g3`** (`.debug_macro`),
  não como código. O mesmo vale para o app (`Obj/*.o`): nada.
- **Sem handler em `.a`:** o `Bootloader.map` só puxa `libm.a`/`libc` (`Bootloader.map:77-88`);
  nenhum arquivo de biblioteca implementa upgrade.

### 12.3 O que existe de leitura (interna, não exposta)

| função | coordenada | para que serve |
|---|---|---|
| `csi_hal_extern_flash_read` | `Source/csi_hal_driver/csi_hal_driver_flash.c:440` | verify-after-write e self-upgrade do bootloader |
| `csi_hal_internal_flash_read` | idem (`#if CHIP_GC9002` → mesma função) | idem |
| `ext_flash_read` / `qspi2_nor_read` / `qspi_nand_read` | `Source/ahmi/GClib/src/texture_flash.c:461`, `:1632`, `:1523` (e `qspi_gd_nand_read` `:1427`) | o app lendo textura/tags do flash |
| `UPG_u32ReadTextureFlash` | `Source/Upgrade/core/upgrade_c1.h:84` | verificação do `.acf` depois de gravar |
| `qspi2_CheckTextureFlashType` | `texture_flash.c:482-560` | **lê o JEDEC ID (0x9F)** e define `TextureFlashType`/`TextureFlashSize` (4/8/16/32 MB NOR; 125 MB NAND) |
| `gc9002_hal_flash_init` | `Source/csi_hal_driver/csi_hal_driver_flash.c:90-160` | o mesmo no bootloader: `FCCR=0x9FB00001`, lê `FCRLDR`, **mascara com `0x00FFFFFF`** e reconhece só `0x1940C8` (32 MB), `0x17405E`/`0x174020` (8 MB), `0x164020` (4 MB), `0x184020`/`0x18405E` (16 MB) |

Nota que corrige a §4/§6 deste documento: `qspi2_CheckTextureFlashType`
(`texture_flash.c:496-560`) é a **tabela de IDs do firmware de aplicação** — a mesma
família `FLASH_ID_IS_*` do flash algorithm, agora com nome de part no comentário
(`W25Q128/GD25Q127/BY25Q128/XM25QH128/ZB25VQ128`, `W25Q64/...`, `W25Q256/GD25Q257`,
`XM25QH32/ZB25VQ32`, NAND WB/GD/DS). E o bootloader (`csi_hal_driver_flash.c:90-160`)
usa uma lista **mais estreita** e mascara o 4º byte: um **Winbond `0x1840EF` não está na
lista do bootloader** (só `0x184020` e `0x18405E`) → `TextureFlashSize` fica no default de
4 MB e o `DRIR` (fast read) não é programado. **HIPÓTESE**: o part da minitela é um dos
reconhecidos pelo app (senão a textura não renderizaria), e o bootloader de produção pode
ter uma lista diferente desta do SDK.

### 12.4 Veredito

**Não há caminho de software, neste SDK, para ler a flash pelo protocolo.** O
`AH`…`MI` é *write-only* (handshake + download + fim), o `UPG_CMD_UPLOAD` é uma constante
órfã, e o USB CDC do SDK descarta o que chega. Para dumpar a flash sobram dois caminhos,
ambos fora do escopo deste repositório: (a) **SWD/JTAG com o CDK** — o mesmo caminho que
o `flash_download.elf` da §1-§8 usa, com o algoritmo de flash em RAM; (b) um firmware
próprio rodando no chip. Se algum dia aparecer o dump do **firmware de produção**
(o que responde em `0324:0324`), aí sim vale procurar um `case 0x0083` nele: o `python`
já assume que ele existe (`minitela_ctl.py:52-56`) mas **nada neste SDK confirma**.

---

## Apêndice — como reproduzir

```bash
source tools/re-env.sh

F=".tools/vendor/ext/GC9002芯片支持包/GC9002芯片支持包/flash_download.elf"
sha256sum "$F"

# cabeçalho, seções, símbolos, vetores
llvm-readelf -h -S -sW -l "$F"
llvm-objcopy --dump-section .debug_str=/tmp/ds.bin "$F" /dev/null
strings -a /tmp/ds.bin | grep -E "FLASH_ID_IS|0x40[0-9A-F]{6}"

# structs e assinaturas (DWARF)
llvm-dwarfdump --name=csi_spiflash_t --name=FlashDevice --name=Device "$F"
llvm-dwarfdump --debug-info --show-children "$F" | less

# descompilado (projeto fica em work/, ignorado pelo git)
analyzeHeadless "$GHIDRA_PROJ" fw142 -import "$F" -processor RISCV:LE:32:default \
  -scriptPath /tmp/opencode/fw/scripts -postScript DumpAll.java
```

O script `DumpAll.java` (decompila todas as funções para um `.c` único) está em
`/tmp/opencode/fw/scripts/` — é efêmero; são ~30 linhas de API do Ghidra
(`DecompInterface` + `FunctionManager`), trivial de recriar. O Capstone usado para o
disassembly anotado: `CS_ARCH_RISCV, CS_MODE_RISCV32|CS_MODE_RISCVC`.
