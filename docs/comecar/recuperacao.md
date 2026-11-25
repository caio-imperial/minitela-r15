# Recuperar a tela

Gravar um `.acf` que o firmware não consegue renderizar trava o render: a tela congela e
o dispositivo para de responder — o app oficial também deixa de abrir, porque bloqueia
esperando resposta.

**É recuperável.** Só a região de textura é escrita; bootloader e calibração não são
tocados.

## O sintoma

- a tela mostra uma página estática ou uma tela de "Information";
- `./minitela_ctl.py info` responde com `status 0x10` e `fileId` zerado;
- o app oficial não abre.

## O primeiro socorro: reboot

Na maioria dos casos um **reboot de verdade** devolve a tela. Não é `authorized 0/1` no
sysfs — o módulo continua alimentado; tem que ser corte real de energia.

Se a tela voltar, siga a vida normalmente. O `status 0x10` com `fileId` zerado é o estado
normal depois do boot, até o app começar a conversar.

## Se voltar travada: regravar

Com o dispositivo respondendo (mesmo que mal), regrave um `.acf` de fábrica:

```bash
pkill -x minitela
./minitela_ctl.py --force send /usr/share/minitela/resources/ACF/Texture.acf -y
```

`--force` serve para tentar mesmo com o app rodando. Se der `EIO`, a porta provavelmente
morreu porque o USB renumerou — espere e use a porta nova (`ls /dev/ttyACM*`).

## Recuperação automática no login

Quando a tela trava no boot e não dá tempo de rodar na mão, arme um `.desktop` em
`~/.config/autostart/`:

```ini
[Desktop Entry]
Type=Application
Name=Recupera minitela
Exec=/bin/bash -c "sleep 3; /caminho/minitela_recover.py --timeout 900 > /tmp/minitela-recover.log 2>&1"
```

Reinicie o notebook. O script fica tentando até conseguir e grava o tema de fábrica assim
que o dispositivo responder na janela do boot. O log fica em `/tmp/minitela-recover.log`.

## Quando o USB não enumera mais

Se o dispositivo sumiu como USB (`device descriptor read/64, error -110`,
`unable to enumerate USB device`), o caminho acima **não alcança**: o USB pertence ao
firmware de aplicação — justamente o que travou. Nesse estado, o `minitela_recover.py`
não tem onde conectar.

A recuperação, nesse caso, é **por UART**, antes de o app rodar:

1. **ROM de boot (2 KB, fixa).** Depois do reset, o chip executa um código em ROM que
   espera, por um tempo determinado, um comando de upgrade pela serial. Se não recebe,
   salta para a flash (`RM201`, ~p. 32 — "hard BOOT").
2. **Bootloader da flash.** Repete a lógica tentando `SD → CAN → UART`, com espera padrão
   de **500 ms** (`upg_cfg.bin` em `0x080F7000` pode mudar isso).
3. **Aplicação.** Só depois disso a UI sobe — e é ela que implementa o protocolo USB
   `AH…MI` que usamos no dia a dia.

!!! warning "Não é a porta USB"
    Não existe janela USB antes do login. Ficar tentando capturar `/dev/ttyACM*` no boot
    não vai funcionar quando o app está travado.

### O que você precisa

- acesso físico a **RX, TX e GND** do módulo (a tela fica atrás do bezel, com flat cable
  curto — é a parte delicada);
- um adaptador USB-serial em **3,3 V** (confira o nível lógico antes de ligar);
- a ferramenta de upgrade do fabricante (`GC9002串口升级协议及工具`, com `uartTool.exe`) e
  os arquivos de firmware.

### Pinos

As fontes divergem, e **quem manda é o `upg_cfg.bin` daquela placa**:

| fonte | pino |
|---|---|
| texto do fabricante (placa de desenvolvimento) | **UART0**, TX `PB14`, RX `PB15`, 115200 |
| default do fonte do bootloader (SDK) | **UART2**, `PB9`/`PB8`, 115200 |

Nenhuma das duas foi confirmada no módulo da minitela. Sem o `upg_cfg.bin` da sua unidade
(que não dá para ler sem acesso), é tentativa e erro — e é por isso que este procedimento
está documentado como **não validado**.

### Como seria a tentativa

1. conecte o adaptador (RX↔TX, GND↔GND; **não** ligue VCC);
2. abra a ferramenta já escutando em 115200;
3. provoque um **corte real de energia** no módulo (desligar o notebook) para cair na
   janela de boot;
4. a ferramenta deve receber o handshake e oferecer os arquivos.

Se o handshake não vier, troque de par de pinos e repita. A janela é curta: a ferramenta
precisa estar rodando **antes** do reset.

!!! danger "O que não fazer"
    Se a janela abrir, grave **só** `Texture.acf` — a menos que você tenha os binários
    originais da sua unidade e um plano para `product`/`calibration`. `cpu1` errado, sem
    backup, é o mesmo estado de novo.

## Caso real: o `CheckCode` de uma página

Uma unidade de outro usuário parou de enumerar USB (`-110`/`-62`) depois de gravar um
`.acf` editado à mão. A reconstrução offline do arquivo mostrou **um único** invariante
quebrado:

```
pg4: CheckCode gravado 0xd0691422, recalculado 0xd0d91492
```

Duas palavras explicavam toda a diferença:

| offset no bloco | antes (controle) | depois (editado) | campo |
|---|---|---|---|
| `+0x1c` | `0x00f000f0` | `0x00c000c0` | `TexWidth/TexHeight` |
| `+0x24` | `0x02000200` | `0x02800280` | `ScalerX/Y` (1.9 fixo) |

`0x300030 ^ 0x800080 = 0xb000b0` — exatamente o delta do `CheckCode`. Nenhuma outra
palavra mudou, e as fatias da animação estavam intactas.

É o retrato do [FATO 12](../RE-acf.md#fato-12-tamanho-da-textura-escalonador-e-tile-boxes-andam-juntos):
**mexer no bloco de uma página exige recalcular o `CheckCode` daquela página**, e o par
tamanho↔escalonador tem de andar junto.

Reparo offline:

```bash
./acf_inspect.py --fix seu.acf --out corrigido.acf
```

Mas atenção: com o app preso **antes** do USB, o arquivo corrigido ainda precisa ser
entregue — e aí só vale o caminho por UART descrito acima.

## Cuidado que evita o problema

- deixar **"limpar resíduo da flash antes"** marcado no painel;
- preferir `minitela_patch.py` (não mexe na configuração) a recompilar;
- antes de qualquer gravação, ter à mão o `.acf` de fábrica — ele está no pacote, em
  `/usr/share/minitela/resources/ACF/`.

!!! danger "O que não fazer"
    Não gravar nas regiões `bootloader`, `cpu1`, `calibration`, `hwconfig` ou `product`
    pelo protocolo. O `minitela_ctl.py` recusa essas regiões por padrão, e não há backup
    delas no pacote — especialmente a calibração, que é por unidade.
