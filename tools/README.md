# tools/ — toolchain de engenharia reversa

Ferramentas para analisar o `AHMISimGenDemo_og.exe`, o `app.asar` e o formato `.acf`
sem depender de nada instalado no sistema (exceto binutils).

## Instalar / verificar

```bash
tools/install-re-toolchain.sh          # baixa JDK 25, Ghidra 12.2 e um venv
tools/install-re-toolchain.sh --check  # so verifica o que existe
```

Tudo fica em `.tools/` (gitignored): `jdk/`, `ghidra/`, `venv/` (pefile, capstone,
binwalk). Nada pede sudo.

Por que JDK **25**: o Ghidra 12.2 usa `--enable-native-access` e
`-XX:+UseCompactObjectHeaders`; com o JDK 21 ele aborta com "unsupported java version".

## Usar

```bash
source tools/re-env.sh

# decompilar/importar um binario (projetos ficam em work/, nao em .tools/:
# o Ghidra recusa qualquer elemento de caminho comecando por '.')
analyzeHeadless "$GHIDRA_PROJ" minitela \
  -import ~/.local/share/minitela-custom/IDE_utils/Gen/AHMISimGenDemo_og.exe

# o mesmo, com analise e um script pos-analise
analyzeHeadless "$GHIDRA_PROJ" minitela \
  -import <binario> -postScript MeuScript.java

# PE sem Ghidra
python -c "import pefile; p=pefile.PE('<exe>', fast_load=True); print(hex(p.OPTIONAL_HEADER.ImageBase))"
```

## Nao instalado (opcional)

- `radare2` — `sudo apt install radare2` (triagem rapida com `rabin2`)
- `unblob` — `pipx install unblob` (extracao de firmware/imagens)

O `binwalk` do venv cobre o basico de extracao.
