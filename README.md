# Minitela do Positivo Vision R15M no Linux

Ferramentas para usar a **minitela** (tela secundária de 1,54", 240x240) do notebook
Positivo Vision R15M no Linux: enviar imagens suas, trocar de tema, controlar página e
brilho — e a documentação da engenharia reversa que tornou isso possível.

O app que vem no Policop só deixa escolher entre 21 temas prontos. A opção de carregar
imagem própria existe na interface, mas não funciona no Linux — o compilador de textura
que ela precisa é um `.exe` de Windows.

> 📖 **Documentação completa**: <https://caio-imperial.github.io/minitela-r15/>
> (guia de uso, referência do protocolo e do formato `.acf`, e os cadernos de engenharia
> reversa). Fonte em [`docs/`](docs/), gerada com MkDocs.

## Colocando uma imagem sua na minitela

Uma vez só, para montar o ambiente:

```bash
./minitela_build.py setup
```

Depois, para cada imagem:

```bash
./minitela_build.py build ~/minha_foto.jpg --send
```

Isso corta a imagem no centro para 240x240, compila o `.acf` (~6 s), para o app oficial,
grava na minitela (~4 s) e devolve o controle. **Reabra o app pelo botão dedicado do
teclado** e vá até a tela **Imagens** — sua foto está lá.

Se a tela de Imagens não aparecer ao passar pelo botão, ela pode estar desabilitada:
abra o app e ligue "Imagens" na lista de telas (ou
`gsettings set org.policorp.minitela saved-screens "[true,true,true,true,true,true,true]"`).

Dá para trocar as três imagens da tela de uma vez — as setas `<` `>` navegam entre elas:

```bash
./minitela_build.py build foto1.jpg foto2.png foto3.jpg --send
```

Aceita JPG, PNG, GIF — qualquer formato que o ffmpeg leia. Sem `--send`, ele só gera o
arquivo e mostra o comando para gravar depois.

### Sem wine (depois de ter um template)

O `build` compila o `.acf` com o compilador do ODM sob wine. Mas, uma vez que exista um
`.acf` que o firmware aceita (o "template"), trocar as imagens não precisa de compilador
nenhum: as texturas ficam antes da config e não entram nos checksums de página.

```bash
./minitela_patch.py --template ~/.local/share/minitela-custom/out/minitela.acf \
                    --out novo.acf foto1.jpg foto2.png --send
```

Ele converte cada imagem para o formato de bloco do chip (STC, 4x4), escreve nos offsets
da tabela de texturas, recalcula o checksum do header e valida com `acf_inspect.py`
antes de gravar. Testado no hardware: a imagem aparece na tela.

Aceita **GIF animado**: os quadros viram fatias de uma mesma textura (`acf_anim.py`), o
`GifSliceNum` do widget é ajustado e o arquivo cresce `N × 57.600 B` — até 96 quadros.
O resultado é validado do mesmo jeito antes de gravar.

```bash
./minitela_patch.py --template base.acf --out animado.acf meu.gif --send
```

O template continua sendo um artefato de build (um por versão de firmware/screen).

Para voltar às imagens de fábrica:

```bash
./minitela_ctl.py send /usr/share/minitela/resources/ACF/Texture.acf -y
```

## Informação em tempo real (relógio, bateria, clima, notificações)

Isto **não mexe na flash**: são *tags* (variáveis) que o firmware já sabe desenhar. Manda
o valor, a tela atualiza na hora. Risco zero — dá para testar à vontade.

```bash
./minitela_tags.py list                          # 40 tags mapeadas
./minitela_tags.py set relogio "23/08 23:54"
./minitela_tags.py set bateria 87
./minitela_tags.py set cidade "Linhares"
./minitela_tags.py notify "Fulano" "oi, tudo bem?"
./minitela_tags.py daemon                        # relógio + bateria + cpu + wifi, a cada 5s
```

Há tags para três lembretes, três notificações, cinco dias de previsão, mídia (nome,
posição, play/pause), CPU, GPU, bateria, wifi e Bluetooth.

**Importante:** o app oficial reescreve todas as tags a cada poucos segundos com os dados
dele — as suas somem quase na hora. Para valer, pare o app (`pkill -x minitela`); um
daemon próprio precisa *substituir* o app, não conviver com ele.

Formato dos frames, conferido contra capturas do app oficial:

```
texto:  AH | ctrl | 0090 | 0xD0 | regId(2,BE) | tamanho(2,BE) | UTF-8 | crc | MI
número: AH | ctrl | 0090 | 0x8N | [regId(2,BE) valor(4,BE)] x (N+1)  | crc | MI
```

Os ids de CPU, bateria, wifi, notificações e lembretes vêm do `tagUtils.js` do MiniPanel.
Os de relógio (2006), cidade (2027) e temperatura (2030–2032) não estão no SDK — foram
capturados dos frames que o app da Positivo manda de verdade.

## Controlando a minitela direto

Sem depender de nada além da stdlib do Python:

```bash
./minitela_ctl.py info               # handshake e status (só leitura)
./minitela_ctl.py send Texture7.acf  # grava um tema
./minitela_ctl.py page 5             # troca a página exibida
./minitela_ctl.py brightness 100
./minitela_ctl.py monitor            # dump dos frames do protocolo
```

O app oficial segura a porta serial: as ferramentas avisam e pedem `pkill -x minitela`
antes. Para religá-lo depois, cuidado com duas armadilhas — ele deixa o socket
`/tmp/minitela_socket` órfão, e detecta instância única com
`pgrep -f /usr/share/minitela/minitela`, que casa com o seu próprio comando de shell se
você digitar o caminho inteiro. O que funciona:

```bash
rm -f /tmp/minitela_socket
cd /tmp && D=/usr/share/mini"tela" && setsid env DISPLAY=:0 GDK_BACKEND=x11 "$D/minitela" &
```

(ou simplesmente reabrir pelo botão dedicado do teclado)

## Requisitos

- notebook Positivo Vision R15M com o pacote `minitela` instalado (o Policop já traz);
- `ffmpeg`;
- `wine` — **opcional**: só o compilador de textura usa. Necessário apenas para criar o
  template do zero (`minitela_build.py`) ou mudar o layout pelo projeto; trocar imagens,
  inclusive GIF animado, é nativo (`minitela_patch.py`):

```bash
sudo dpkg --add-architecture i386 && sudo apt update
sudo apt install wine wine32:i386 wine64
```

`wine64` é obrigatório: num prefixo win32 o compilador procura `zip32\7z.exe`, que não
existe no pacote (só vem `zip64/`). O `setup` cria o prefixo `~/.wine-mt64` sozinho.

## Os arquivos

| arquivo | o que faz |
|---|---|
| `minitela_ctl.py` | protocolo AHMI em stdlib pura (termios, sem pyserial): envio, página, brilho, status |
| `minitela_tags.py` | manda relógio, bateria, cpu, wifi, clima e notificações em tempo real (sem tocar na flash) |
| `minitela_build.py` | imagem → GIF 240x240 → projeto → compilador → `.acf` → grava |
| `minitela_recover.py` | recupera a minitela se uma gravação ruim travar o firmware |
| `acf_codec.py` | codec nativo do formato de textura (encode/decode) + checksum |
| `acf_inspect.py` | lê/valida um `.acf` com o mapa do firmware (páginas, checksums, tabela de texturas) |
| `minitela_patch.py` | troca as 3 imagens de um `.acf` que já funciona, sem recompilar (dispensa o wine) |
| `lab/lab_acf.py`, `lab/exp_bloco.py` | bancada de engenharia reversa (imagens sintéticas + diff das saídas) |
| `lab/patch_acf.py` | obsoleto — o `minitela_patch.py` faz o mesmo com o mapa correto |
| [`docs/RE-acf.md`](docs/RE-acf.md) | o caderno da engenharia reversa: protocolo, formato, provas |

## Como a coisa funciona

A minitela **não é um monitor** do X/Wayland. É um módulo com firmware próprio
(**GC9002**, projeto feito no IDE AHMI da GraphiChina) pendurado no USB como porta serial
(`/dev/ttyACM*`, `0324:0324`). O host manda valores de variáveis; para mudar o visual,
regrava a textura inteira na flash (`0x08100000`).

O protocolo é `AH` … `MI` com CRC (que o firmware ignora), e o `.acf` é o pacote de
textura compilada. Detalhes, incluindo o formato de bloco decifrado e o algoritmo do
checksum, estão em [docs/RE-acf.md](docs/RE-acf.md).

Velocidade real: um tema de 1,5 MB grava em ~4 s — os 115200 baud são fictícios, o
transporte é USB.

## Se algo der errado

Gravar um `.acf` que o firmware não consegue renderizar trava o render: a tela congela e o
dispositivo para de responder (o app oficial também deixa de abrir, porque bloqueia
esperando resposta). É recuperável — só a região de textura é escrita, bootloader e
calibração não são tocados:

1. arme a recuperação para rodar no login, com um `.desktop` em `~/.config/autostart/`:
   `Exec=/bin/bash -c "sleep 3; /caminho/minitela_recover.py --timeout 900 > /tmp/minitela-recover.log 2>&1"`
2. reinicie o notebook (é preciso corte real de energia — `authorized 0/1` no sysfs não
   basta, o módulo continua alimentado);
3. o script pega o dispositivo na janela do boot e regrava o tema de fábrica.

Para voltar ao original a qualquer momento:
`./minitela_ctl.py send /usr/share/minitela/resources/ACF/Texture.acf`

## Créditos

O algoritmo do **checksum** veio do projeto [SideCar](https://github.com/FreyreCorona/SideCar)
(Go), que ataca a mesma minitela — verificado aqui contra arquivos de fábrica e gerados
pelo compilador oficial. O resto (protocolo, formato de bloco, fluxo de build) foi
levantado de forma independente, com uma bancada que compila imagens sintéticas e compara
as saídas.

## Aviso

Isto mexe na flash de um dispositivo. Funciona no meu R15M com Policop; não há garantia
nenhuma. As regiões críticas (bootloader, cpu1, calibração, hwconfig) são bloqueadas por
padrão no `minitela_ctl.py` — não remova essa trava sem saber o que está fazendo.
