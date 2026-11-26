# Comunidade

## Projetos relacionados

- **[SideCar](https://github.com/FreyreCorona/SideCar)** (Go, MIT) — runtime de displays
  auxiliares; ataca a mesma família de telas e foi de onde veio o algoritmo de checksum do
  `.acf`. Foco em dashboards, não em textura; a parte de imagem deles ainda não funciona
  nesta tela.
- **[AHMI Docs](https://docs.graphichina.com)** — documentação do IDE e do formato de
  projeto (em chinês e inglês). Boa para entender páginas, widgets e ações.
- **[Thorsianway — downloads](https://www.thorsianway.com/download/documentTool)** —
  datasheet, manual de referência, SDK, chip support pack e as EVBs do GC9002.
- **[opene902](https://github.com/XUANTIE-RV/opene902)** (Apache-2.0) — RTL do núcleo
  RISC-V que roda dentro do chip.

## Ideias que cabem na tela

O `.acf` permite trocar as três imagens e animar GIFs; as tags permitem escrever texto e
números em tempo real. Com isso dá para fazer, sem tocar no firmware:

| ideia | como |
|---|---|
| **Dashboard de sistema** | daemon de tags (bateria, wifi, temperatura) — o `minitela_tags.py daemon` já é um esqueleto |
| **Clima** | API → `cidade`, `temp_agora`, `temp_prev1/2` (a tela mais generosa) |
| **Notificações** | `notify` com remetente e texto; um bridge lendo o barramento do desktop |
| **Mídia** | nome, posição, play/pause nas tags de mídia do projeto original |
| **Galeria de temas** | 3 imagens + 1 GIF; dá para empacotar e compartilhar `.acf` prontos |
| **Home Assistant / MQTT** | um serviço pequeno que traduz estado para tags |
| **Retro / arte** | GIFs animados como “protetor de tela” |

O que **não** dá: vídeo, 3D, gráficos vetoriais arbitrários — o firmware desenha um
conjunto fixo de widgets definido no projeto.

## O que gostaríamos de receber

1. **Gerador de `.acf` sem wine** — o formato está decifrado; falta o montador completo do
   container (páginas/widgets), não só das texturas.
2. **Modo 1 do codec** — decodificar arquivos oficiais com fidelidade total.
3. **Identificação do painel e da flash** desta unidade.
4. **Bindings** (Rust, Go, Node) para o protocolo e o codec.
5. **Alternativas de GUI** — o painel é tkinter; GTK/Qt/tray são bem-vindos.
6. **Serviço de usuário** (systemd) para o daemon de tags sobreviver ao login.

Se você fizer algo com a tela, abra uma issue contando — a ideia é manter uma lista viva
aqui.
