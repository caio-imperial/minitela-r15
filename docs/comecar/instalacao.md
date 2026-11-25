# Requisitos e instalação

## O que você precisa

- notebook **Positivo Vision R15M** com o pacote `minitela` instalado (o Policop já traz);
- **Python 3.10+** — as ferramentas usam só a stdlib;
- **ffmpeg** — recorte/escala das imagens;
- **wine** — *opcional*: só para gerar um `.acf` do zero com o compilador do fabricante.
  Trocar imagens e GIFs não usa wine.

```bash
# Debian/Ubuntu
sudo apt install ffmpeg python3

# só se você for usar o minitela_build.py (compilador do ODM)
sudo dpkg --add-architecture i386 && sudo apt update
sudo apt install wine wine32:i386 wine64
```

O `wine64` é obrigatório: num prefixo win32 o compilador procura `zip32\7z.exe`, que não
existe no pacote. O ambiente é criado em `~/.wine-mt64` pelo `setup`.

## Instalação em um comando (recomendado)

Com o repositório clonado, um comando instala o CLI e deixa tudo no `PATH`:

```bash
pipx install .        # ou: pip install --user .
minitela doctor
```

O `doctor` diz o que está pronto e o que falta:

```
[ok  ] python 3.12.3
[ok  ] ffmpeg: /usr/bin/ffmpeg
!     wine: ausente (so necessario para build/layout)
[ok  ] tela: /dev/ttyACM0
!     app oficial: rodando (segura a porta; use pkill -x minitela)
```

A partir daí, um comando só:

```bash
minitela patch --template /usr/share/minitela/resources/ACF/Texture.acf \
               --out ~/minha.acf --tela-cheia ~/foto.jpg --send
minitela tags set cidade "Linhares"
minitela inspect --diagnostico ~/minha.acf
minitela gui
```

Todos os subcomandos: `patch`, `gif`, `tags`, `ctl`, `gui`, `inspect`, `build`,
`recover`, `doctor`, `version`.

## Clone e confira

```bash
git clone https://github.com/caio-imperial/minitela-r15
cd minitela-r15

./minitela_ctl.py info      # handshake + status (só leitura)
```

Se `info` responder `maxPacketLength`, a tela está falando com você.

!!! note "O app oficial segura a porta serial"
    As ferramentas avisam e pedem `pkill -x minitela` antes. Para religar depois, use o
    **botão dedicado do teclado** — é o caminho que funciona sempre.

## Permissão na porta

O pacote `minitela` já instala a regra udev (`/etc/udev/rules.d/99-ttyacm.rules`) e deixa
o `/dev/ttyACM*` acessível ao grupo `dialout`. Se o seu usuário ainda não estiver nele:

```bash
sudo usermod -aG dialout "$USER"   # e abra a sessão de novo
```

## Ferramentas de engenharia reversa (opcional)

Só interessam a quem vai analisar binários ou o SDK:

```bash
tools/install-re-toolchain.sh          # JDK 25 + Ghidra 12.2 + venv (pefile, binwalk)
tools/install-re-toolchain.sh --check  # só verifica
source tools/re-env.sh                 # põe tudo no PATH desta sessão
```

Vai tudo para `.tools/` (fora do git). O JDK precisa ser 25: o Ghidra 12.2 usa
`--enable-native-access` e aborta com o 21.
