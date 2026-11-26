# Minitela do Positivo Vision R15M no Linux

App de desktop — **Rust + Svelte (Tauri)** — para usar a **minitela** (tela secundária de
1,54", 240×240) do notebook Positivo Vision R15M no Linux: colocar **suas** imagens e GIFs
nos três slots, controlar página e brilho, e manter as telas de sistema (relógio, bateria,
wifi, bluetooth e clima) atualizadas.

O app que vem no notebook (Policop/Policorp) só oferece temas prontos, e a opção de
imagem própria não funciona no Linux — o compilador de textura que ela usa é um `.exe` de
Windows. Este projeto decifrou o protocolo e o formato de textura para fazer isso nativo.

> 📖 **Documentação**: <https://caio-imperial.github.io/minitela-r15/> — guia de uso,
> referência do protocolo e do `.acf`, e os cadernos de engenharia reversa (fonte em
> [`docs/`](docs/)).

## O que o app faz

- **Três slots** (as imagens do tema, páginas 5/6/7): escolher imagem, arrastar para
  recortar, zoom de 1× a 3×, "conter" com barras, ou tela cheia 240×240. Gera um `.acf`
  novo com as trocas de uma vez e **valida antes de escrever**.
- **GIF animado**: até 96 quadros; a velocidade é a do tema.
- **Gravar na tela**: protocolo AHMI direto na serial, ~5 s para um tema de 1,5 MB;
  reabre a porta sozinho depois que o firmware reenumera o USB.
- **Controle**: páginas (as 7 que o aparelho mostra), brilho, e a **tecla "mini tela"** do
  teclado passa a funcionar com o app no controle (pula as páginas desativadas).
- **Telas de sistema**: relógio, bateria (texto + barra), wifi e bluetooth, atualizados a
  cada 15 s.
- **Clima**: Open-Meteo sem chave, com a cidade que você configurar — três dias com
  mín/máx e ícone (sol, nuvens, chuva, lua, neve).
- **Perfis**: cada perfil é um "save" — o `.acf` que vai para a tela, as miniaturas
  decodificadas e uma cópia das imagens originais. Ao assumir o controle, o app compara o
  md5 que o firmware guardou com o do perfil ativo e regrava se a tela estiver com outro.

Detalhes de implementação, dependências e decisões em
[`apps/desktop/README.md`](apps/desktop/README.md).

## Como rodar

Dependências (Ubuntu/Debian):

```bash
sudo apt install ffmpeg libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev \
                 libayatana-appindicator3-dev patchelf libxdo-dev libssl-dev
```

```bash
cd apps/desktop
npm install
npm run tauri dev      # desenvolvimento
npm run tauri build    # .deb/.AppImage em src-tauri/target/release/bundle
```

O CI compila em `ubuntu-22.04` de propósito: o AppImage gerado em `ubuntu-latest` não abre
em Debian 12 (`GLIBC_2.38 not found`).

## Perfis: o que fica no disco

```
~/.local/share/minitela/perfis/meu-tema/
├── perfil.json      metadados + caminhos relativos (nome, datas, base, página, slots)
├── tema.acf         o que a tela recebe
├── thumbs/          miniatura decodificada do próprio .acf (o que o aparelho desenha)
└── originais/       cópia do arquivo escolhido, para reeditar recorte/zoom depois
```

O perfil **de fábrica** não tem pasta: aponta para o `Texture.acf` instalado pela Positivo.

## Como funciona (resumo)

A minitela **não é um monitor** do X/Wayland. É um módulo com firmware próprio (**GC9002**,
projeto feito no IDE AHMI da GraphiChina) pendurado no USB como porta serial
(`/dev/ttyACM*`, `0324:0324`). O host manda valores de variáveis (tags); para mudar o
visual, regrava a textura inteira na flash (`0x08100000`).

- protocolo `AH` … `MI` sobre CDC-ACM; o app usa `termios` puro (via `nix`), sem
  `serialport`/`libudev`;
- o firmware valida `magic`, versão e o **`CheckCode` de cada página** — se divergir, entra
  em laço infinito e o USB fica mudo;
- o `.acf` guarda a textura em blocos STC de 16 bytes. O app **gera** com o sub-formato de
  uma partição e **decodifica** 99,3% dos blocos dos temas oficiais (`0`, `01`, `0111`);
- a página é **1-based** na API do firmware, e o `.acf` de fábrica tem 11 páginas das quais
  7 aparecem.

O formato de bloco, o checksum e o mapa do arquivo estão em
[`docs/referencia/`](docs/referencia/) e nos cadernos de RE de [`docs/`](docs/).

## Ferramentas Python (referência)

O repositório mantém as ferramentas originais que abriram o caminho — são a **referência e
o oráculo dos testes** do app:

| arquivo | o que faz |
|---|---|
| `minitela_ctl.py` | protocolo AHMI em stdlib pura: envio, página, brilho, status |
| `minitela_tags.py` | relógio, bateria, wifi, bluetooth, clima e notificações |
| `minitela_patch.py` | troca as imagens de um `.acf` que já funciona, sem recompilar |
| `acf_codec.py`, `acf_inspect.py`, `acf_anim.py` | codec, validação e montagem de GIF |
| `minitela_recover.py` | recupera a tela se uma gravação ruim travar o firmware |
| `minitela_build.py` | build pelo compilador do ODM (precisa de `wine`, opcional) |

O guia completo está no site, dividido por tarefa:

| assunto | página |
|---|---|
| instalar (`pipx`), requisitos, `wine` opcional | [Requisitos e instalação](https://caio-imperial.github.io/minitela-r15/comecar/instalacao/) |
| enviar imagem ou GIF (com ou sem `wine`) | [Enviar uma imagem](https://caio-imperial.github.io/minitela-r15/comecar/imagem/) · [GIF animado](https://caio-imperial.github.io/minitela-r15/comecar/gif/) |
| relógio, bateria, clima, notificações | [Tags em tempo real](https://caio-imperial.github.io/minitela-r15/comecar/tags/) |
| painel tkinter | [Painel gráfico](https://caio-imperial.github.io/minitela-r15/comecar/painel/) |
| tela travada | [Recuperar a tela](https://caio-imperial.github.io/minitela-r15/comecar/recuperacao/) |
| referência de cada script | [Ferramentas](https://caio-imperial.github.io/minitela-r15/ferramentas/) |

## Se algo der errado

Gravar um `.acf` que o firmware não consegue renderizar trava o render: a tela congela e o
dispositivo para de responder. É recuperável — só a região de textura é escrita.

1. **tire e recoloque o cabo** da minitela (nesta máquina não há corte de energia por
   software: `uhubctl` não encontra hub controlável, e `authorized=0/1` no sysfs não corta
   alimentação);
2. com a tela respondendo, use **"tema de fábrica"** no app;
3. sem o app, `./minitela_ctl.py send /usr/share/minitela/resources/ACF/Texture.acf -y`.

Se o USB não enumerar mais, a recuperação é por UART na janela do boot — ver
[`docs/comecar/recuperacao.md`](docs/comecar/recuperacao.md).

## Créditos

O algoritmo do **checksum** veio do projeto [SideCar](https://github.com/FreyreCorona/SideCar)
(Go), que ataca a mesma minitela — verificado aqui contra arquivos de fábrica e gerados
pelo compilador oficial. O resto (protocolo, formato de bloco, fluxo de build) foi
levantado de forma independente, com uma bancada que compila imagens sintéticas e compara
as saídas.

## Aviso

Isto mexe na flash de um dispositivo. Funciona no meu R15M com Policop; não há garantia
nenhuma. As regiões críticas (bootloader, cpu1, calibração, hwconfig) são bloqueadas por
padrão — não remova essa trava sem saber o que está fazendo.

Nada de material do fabricante é redistribuído aqui: o SDK, os datasheets, os binários de
firmware e o app da Policorp ficam fora do repositório. Código sob MIT; textos da
documentação sob CC BY-SA 4.0.
