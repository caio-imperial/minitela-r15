# Minitela GC9002

A **minitela** é a tela secundária de 1,54" (240×240) do notebook Positivo Vision R15M.
Ela **não é um monitor** do X/Wayland: é um módulo com firmware próprio — chip **GC9002**,
GPU AHMI 3 Lite + núcleo RISC-V XuanTie E902 — pendurado no USB como porta serial
(`/dev/ttyACM*`, `0324:0324`).

O app que vem no Policop só deixa escolher entre 21 temas prontos. Este projeto abriu o
resto: trocar as imagens (inclusive **GIF animado**), mandar dados em tempo real e
entender o formato binário por trás de tudo — sem depender do Windows.

!!! warning "Isto grava na flash de um dispositivo"
    Funciona no R15M com Policop; não há garantia. Leia [Recuperar a tela](comecar/recuperacao.md)
    antes de gravar qualquer coisa.

## O que já funciona

| | como | precisa de wine? |
|---|---|---|
| Imagem própria (3 slots) | `minitela_patch.py` sobre um `.acf` que já funciona | **não** |
| GIF animado (até 96 quadros) | idem, com os quadros virando fatias da textura | **não** |
| Trocar tema (21 de fábrica) | `minitela_ctl.py send TextureN.acf` | não |
| Página, brilho, reboot | `minitela_ctl.py page/brightness/reboot` | não |
| Relógio, bateria, wifi, bluetooth, clima, notificações | `minitela_tags.py` (só tags, não toca na flash) | não |
| Painel gráfico com tudo isso | `minitela_gui.py` (tkinter, sem dependências) | não |
| Gerar um `.acf` do zero / mudar layout | `minitela_build.py` (compilador do ODM) | sim, uma vez |

## Por onde começar

- Quer **colocar uma foto**? → [Enviar uma imagem](comecar/imagem.md)
- Quer um **GIF animado**? → [GIF animado](comecar/gif.md)
- Quer **relógio e bateria** na tela? → [Tags em tempo real](comecar/tags.md)
- Prefere **clicar**? → [Painel gráfico](comecar/painel.md)
- A tela **travou**? → [Recuperar a tela](comecar/recuperacao.md)
- Quer entender **como isso foi descoberto**? → [Engenharia reversa](RE-acf.md)

## Estado do projeto

O que está provado no hardware e o que continua aberto está nos cadernos de engenharia
reversa, sempre com endereço e offset como evidência:

- [`RE-acf.md`](RE-acf.md) — o formato `.acf`, o protocolo e as provas;
- [`RE-firmware.md`](RE-firmware.md) — a flash NOR, o bootloader e o protocolo no fonte do SDK;
- [`RE-acf-source.md`](RE-acf-source.md) — o `.acf` lido pelo código do firmware de aplicação.

Projetos relacionados: [SideCar](https://github.com/FreyreCorona/SideCar) (runtime de
displays auxiliares, em Go) e a documentação do IDE AHMI em
[docs.graphichina.com](https://docs.graphichina.com).
