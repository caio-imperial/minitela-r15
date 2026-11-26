# App desktop (Tauri + Svelte)

Experimento em paralelo ao Python, **na branch `tauri`**. Nada aqui substitui as
ferramentas atuais: o Python continua sendo a referência e o que está testado no
hardware.

## Por que

O Python resolve o domínio (protocolo, `.acf`, codec, patch) e está validado. O que falta
é uma **UI de verdade** e distribuição sem depender de Python no host. O Tauri entrega as
duas coisas: backend em Rust e front em Svelte, com bundler que gera `.deb` / `.AppImage`.

## Estado

Hoje o app faz isto:

1. **ambiente** — o equivalente ao `minitela doctor`, em Rust, só com o que o app usa:
   `ffmpeg`, `/dev/ttyACM*`, app oficial rodando (varre `/proc/*/comm`), temas de fábrica,
   template 240×240, `nmcli` (wifi) e `bluetoothctl` (bluetooth). Python e wine ficaram na
   fase anterior — o app não chama nenhum dos dois.

2. **leitura/validação de `.acf`** — abre um arquivo e mostra tamanho, tela, páginas,
   texturas e o diagnóstico campo a campo (`CheckCode` por página, magic, versão);
3. **troca de imagem** — lista os três slots do `.acf` (páginas 4/5/6) com miniatura,
   deixa escolher imagem e **enquadramento por slot** (arrastar para recortar, zoom de
   1× a 3×, ou "conter" com barras), e gera um `.acf` novo com todas as trocas de uma vez,
   validando antes de escrever; a gravação já exibe a página do primeiro slot editado;
4. **tags em tempo real** — com a sessão aberta, o app manda a cada 15 s: relógio,
   **bateria em texto** (`"100%"`, reg 1082) + **nível da barra** (1150, 0–3 → 1–4
   pauzinhos), wifi (`nmcli`, 1083) e bluetooth (`bluetoothctl`, 1085). Sem ACK, como o
   Python. Só manda registrador que existe no tema e no tipo certo (`REGISTRADORES`,
   `TEXTO`, `NUMERO` em `device.rs`): id fora da lista ou número num registrador de texto
   já deixou a tela muda;
5. **prévia da textura** — decodifica o slot e devolve PNG para a interface (antes e
   depois de gerar). Em arquivos oficiais aparecem artefatos: só o sub-formato de uma
   partição está implementado (issue #2);
6. **controle da tela** — assume a serial (para o app oficial se preciso), mantém a
   conexão com este app e troca página (lista com as 7 páginas reais — o `.acf` tem 11,
   mas 4 são vazias), brilho e as tags; "devolver ao app oficial" solta a porta e religa
   o app da Positivo. Num tty travado o `close()` prende a thread no kernel (estado D),
   então o descarte da porta acontece fora do lock. A **tecla "mini tela"** do notebook
   (`KEY_PROG1`) é lida dos `/dev/input/event*` e avança a página, pulando as desativadas;
7. **gravar na tela** — protocolo AHMI sobre a serial em Rust (`termios` puro via `nix`,
   sem `serialport`/`libudev`): handshake, troca para modo download, envio por páginas,
   fim e troca de página. Medido no hardware: **4,7 s** para o tema de fábrica. GIF já
   vai como fatias (8 quadros 240×240 gravados e vistos rodando); a velocidade é a do
   `GifInterval` do tema;
8. **clima** — Open-Meteo sem chave, com a cidade configurada na interface: geocodifica,
   pega 3 dias (mín/máx e ícone) e manda `cidade` (2027), faixas (2030–2032), rótulos
   (1119/1124) e ícones (1110/1115/1120). Os ícones do tema foram medidos um a um na
   tela: 0 sol, 1 sol entre nuvens, 2 nuvem, 3 chuva, 4 lua, 5 lua entre nuvens, 6 neve.

O código do porte está em `src-tauri/src/acf/` (`codec.rs`, `inspect.rs`, `patch.rs`) e em
`src-tauri/src/device.rs`, validados contra os fixtures gerados pelo Python e no hardware.

## Perfis e o que fica no disco

Cada perfil é um "save" da tela: o `.acf` que vai para o aparelho **mais** o que é
preciso para reeditar e mostrar sem decodificar de novo.

```
~/.local/share/minitela/perfis/meu-tema/
├── perfil.json      metadados + caminhos relativos (nome, datas, base, página, slots)
├── tema.acf         o que a tela recebe (fonte da verdade)
├── thumbs/          PNG decodificado do próprio .acf (é o que o aparelho desenha)
│   ├── slot-1.png   no tamanho nativo (192 ou 240)
│   └── ...
└── originais/       cópia do arquivo escolhido, para reeditar recorte/zoom depois
```

- O perfil **de fábrica** não tem pasta: aponta para `/usr/share/minitela/.../Texture.acf`.
- Ao assumir o controle, o app compara o **md5** que o firmware guardou (`fileId` do
  `0x0085`) com o do tema do perfil ativo; se for outro, regrava o perfil e volta para a
  página dele.
- Um patch parcial atualiza só os slots gravados — os metadados dos outros ficam.
- A árvore antiga (`~/.local/share/minitela-custom/perfis`) é migrada na primeira execução.
- Ao abrir o app (ou trocar de perfil), as miniaturas salvas ocupam o lugar das do `.acf`
  e o editor reabre com o **enquadramento gravado** de cada slot — dá para ajustar o
  recorte e gerar de novo sem reescolher os arquivos.

## Como está hoje

![app rodando](docs/app.png)

Artefato do CI (AppImage compilado em `ubuntu-22.04`), rodando num Debian 12: o backend
Rust leu o ambiente e a interface listou cada item.

## Como rodar

```bash
cd apps/desktop
npm install
npm run tauri dev        # precisa das libs do webkit (ver abaixo)

npm run tauri build      # gera .deb/.AppImage em src-tauri/target/release/bundle
```

Dependências no Ubuntu:

```bash
sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev \
                 libayatana-appindicator3-dev patchelf libxdo-dev libssl-dev
```

## Estratégia do porte (quando decidirmos)

Ordem pensada para nunca ficar sem ferramenta que funciona:

1. **fixtures dourados** gerados pelo Python: os 22 `.acf` de fábrica, `gif75`, `anim8`,
   e as saídas de `acf_inspect --diagnostico` / `--fix`;
2. **`minitela-core` em Rust**: `acf_codec`, `acf_inspect`, `acf_anim`,
   `minitela_patch`, `minitela_ctl`, `minitela_tags` — cada um comparado byte a byte
   com o Python nos fixtures;
3. **CLI Rust** com o mesmo contrato (`minitela patch|inspect|tags|ctl|doctor`);
4. **UI**: diagnóstico (feito), depois patch com arrastar-e-soltar, preview do `.acf`
   decodificado, escolha de página e brilho;
5. **empacotar** com `tauri build`.

Fica de fora, de propósito:

- `minitela_build.py` (compilador do ODM sob wine) — continua externo;
- `lab/` e `tools/` (bancada e Ghidra);
- qualquer material do fabricante.

## Empacotamento: a glibc do runner vira o mínimo do usuário

O binário carrega a glibc da máquina que compila. Compilado em `ubuntu-latest` (24.04,
glibc 2.39), o AppImage **não abre** em Debian 12 (glibc 2.36) — o sintoma é
`GLIBC_2.38 not found`.

Por isso a pipeline usa **`ubuntu-22.04`** (glibc 2.35): o artefato roda em Debian 12,
Ubuntu 22.04 e mais novos. Se um dia precisar suportar distros mais antigas, é descer o
runner (ou usar container com glibc antiga), nunca subir.

## Regra de ouro

Nenhuma linha de Rust é considerada pronta sem passar nos fixtures. O Python é o oráculo:
se o Rust divergir, o Rust está errado até prova em contrário.
