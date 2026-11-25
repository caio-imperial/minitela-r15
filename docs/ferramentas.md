# Ferramentas

Todas em Python, só com a stdlib. Elas se carregam por caminho, então devem ficar na raiz
do repositório.

## Para usar

| ferramenta | o que faz | exemplo |
|---|---|---|
| **`minitela_patch.py`** | troca imagens e GIF num `.acf` que já funciona; valida antes de gravar | `./minitela_patch.py --template base.acf --out novo.acf foto.jpg --send` |
| **`minitela_ctl.py`** | protocolo AHMI puro: gravar, página, brilho, info, monitor | `./minitela_ctl.py info` |
| **`minitela_tags.py`** | relógio, bateria, CPU, wifi, notificações (sem tocar na flash) | `./minitela_tags.py daemon` |
| **`minitela_gui.py`** | painel tkinter com tudo isso | `./minitela_gui.py` |
| **`minitela_build.py`** | imagem → projeto → compilador do ODM → `.acf` (wine) | `./minitela_build.py build foto.jpg` |
| **`minitela_recover.py`** | regrava o tema de fábrica quando a tela trava | `./minitela_recover.py` |
| **`criar_tela.py`** | clona uma página existente do projeto para uma vazia | `./criar_tela.py --de 4 --para 8 --nome MinhaTela` |

## Para entender/validar

| ferramenta | o que faz |
|---|---|
| **`acf_inspect.py`** | lê e valida um `.acf`: magic, versão, `CheckCode` por página, tabela de texturas; `--diagnostico` explica o que quebrou |
| **`acf_anim.py`** | monta N quadros como fatias de uma textura (usado pelo patch) |
| **`acf_codec.py`** | codec STC: decodifica/encodifica blocos 4×4 e calcula o checksum |
| `lab/lab_acf.py`, `lab/exp_bloco.py` | bancada de engenharia reversa (imagens sintéticas + diff das saídas) |
| `lab/patch_acf.py` | **obsoleto** — superado pelo `minitela_patch.py` |

## Verificar antes de gravar

```bash
./acf_inspect.py --textures novo.acf
```

Um arquivo bom imprime `OK` e nenhum problema. É exatamente o que o firmware valida:
`StartOfConfigdata % 16384`, magic `0x494d4841`, versão e o `CheckCode` de cada página
(`0xA55A5AA5 ^ XOR(words)`).

Quando algo falha, `--diagnostico` diz **o quê** e **por quê**:

```bash
./acf_inspect.py --diagnostico meu.acf
# [ERRO ] pg3: CheckCode do bloco nao bate
#         -> o firmware entra no laco de AHMIInterface e nao termina: ...
```

Ele confere ainda `SingleSliceSize` contra `TexWidth/TexHeight`, texturas fora da área,
sobreposição, `GifSliceNum` contra o bitmap do trailer e o alinhamento do tamanho.

## Toolchain de engenharia reversa

```bash
tools/install-re-toolchain.sh   # JDK 25 + Ghidra 12.2 + venv
source tools/re-env.sh
analyzeHeadless "$GHIDRA_PROJ" minitela -import <binario>
```

Fica tudo em `.tools/` (fora do git). Detalhes em
[`tools/README.md`](https://github.com/caio-imperial/minitela-r15/blob/main/tools/README.md).

## Convenções

- tudo o que grava na flash pede confirmação (ou `-y`);
- regiões críticas são recusadas antes mesmo de abrir a porta;
- `--dry-run` existe nos comandos que gravam;
- nenhuma ferramenta precisa de root.
