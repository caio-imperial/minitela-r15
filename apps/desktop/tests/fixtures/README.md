# Fixtures dourados

Contrato entre o Python (referência, validado no hardware) e o app em Rust.

## O que é versionado

Só `casos.json` — **expectativas**, não arquivos:

- tamanho, `StartOfConfigdata`, número de páginas e de texturas;
- `CheckCode` de cada página (o que o firmware valida);
- md5 dos arquivos de entrada e saída;
- o resultado esperado do `--fix` (checks antes/depois e a lista de mudanças);
- a versão do ffmpeg usada na geração.

Nenhum `.acf` do fabricante entra no repositório (ver `docs/legal.md`). Os arquivos saem
do tema de fábrica instalado na máquina de quem roda os testes.

## Como gerar

```bash
python3 apps/desktop/tests/gerar_fixtures.py
```

Requisitos: pacote `minitela` instalado (para o `Texture.acf` de fábrica), `ffmpeg` e os
módulos Python do repositório. Os casos:

| caso | o que exercita |
|---|---|
| `estatico_192` | patch no tamanho do slot |
| `estatico_240` | `--tela-cheia` (tamanho + escalonador + tile boxes) |
| `gif_8` | 8 quadros, trailer e `GifSliceNum` |
| `fix` | `CheckCode` de página quebrado de propósito → `--fix` |
| `fabrica` | validação do tema de fábrica (nenhum problema) |

## Como usar no Rust

1. rode o gerador (ou use o `casos.json` já commitado);
2. para cada caso, monte o `.acf` de entrada **com o Python** e passe ao código Rust;
3. compare: tamanho, `start`, páginas, `checks[]` e md5 de saída.

O md5 do caso `gif_8` pode variar entre versões de ffmpeg (paleta). Nesse caso o contrato
são tamanho/páginas/checks; o md5 é informativo.

## Regra

Se o Rust divergir do `casos.json`, **o Rust está errado** até prova em contrário — e a
prova é um teste no hardware, não uma opinião.
