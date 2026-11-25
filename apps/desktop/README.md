# App desktop (Tauri + Svelte)

Experimento em paralelo ao Python, **na branch `tauri`**. Nada aqui substitui as
ferramentas atuais: o Python continua sendo a referência e o que está testado no
hardware.

## Por que

O Python resolve o domínio (protocolo, `.acf`, codec, patch) e está validado. O que falta
é uma **UI de verdade** e distribuição sem depender de Python no host. O Tauri entrega as
duas coisas: backend em Rust e front em Svelte, com bundler que gera `.deb` / `.AppImage`.

## Estado

Hoje o app só roda o diagnóstico do ambiente — o equivalente ao `minitela doctor`, mas em
Rust:

- python3 / ffmpeg / wine no `PATH`
- `/dev/ttyACM*`
- app oficial rodando (varre `/proc/*/comm`)
- temas de fábrica em `/usr/share/minitela/resources/ACF`
- template em `~/.local/share/minitela-custom/out/minitela.acf`

É o suficiente para provar a ponte Rust ↔ Svelte e a pipeline.

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

## Regra de ouro

Nenhuma linha de Rust é considerada pronta sem passar nos fixtures. O Python é o oráculo:
se o Rust divergir, o Rust está errado até prova em contrário.
