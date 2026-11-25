#!/usr/bin/env bash
# install-re-toolchain.sh — instala as ferramentas de engenharia reversa DENTRO do repo.
#
# Tudo vai para .tools/ (gitignored): JDK, Ghidra e um venv com pefile/binwalk.
# Nada aqui pede sudo. Idempotente: rodar de novo so confere o que ja existe.
#
# Uso:
#   tools/install-re-toolchain.sh          # instala o que falta
#   tools/install-re-toolchain.sh --check  # so verifica
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
TOOLS="$REPO/.tools"

# Ghidra 12.2 usa --enable-native-access e -XX:+UseCompactObjectHeaders: exige JDK 25.
JDK_VERSION="25.0.5.1+2"
JDK_URL="https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.5.1%2B2/OpenJDK25U-jdk_x64_linux_hotspot_25.0.5.1_2.tar.gz"

GHIDRA_VERSION="12.2"
GHIDRA_URL="https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.2_build/ghidra_12.2_PUBLIC_20261016.zip"

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

log() { printf '==> %s\n' "$*"; }
have() { [ -x "$1" ]; }

download() { # url destino
    log "baixando $(basename "$2")"
    curl -fL --retry 3 --retry-delay 2 -o "$2.part" "$1"
    mv "$2.part" "$2"
}

mkdir -p "$TOOLS"

# ------------------------------------------------------------------ JDK 21
if have "$TOOLS/jdk/bin/java"; then
    log "JDK ok: $("$TOOLS/jdk/bin/java" -version 2>&1 | head -1)"
elif [ "$CHECK_ONLY" = 1 ]; then
    log "JDK AUSENTE (esperado em .tools/jdk)"
else
    download "$JDK_URL" "$TOOLS/jdk.tar.gz"
    log "extraindo JDK"
    tar -xzf "$TOOLS/jdk.tar.gz" -C "$TOOLS"
    rm -rf "$TOOLS/jdk"
    mv "$TOOLS"/jdk-* "$TOOLS/jdk"
    rm -f "$TOOLS/jdk.tar.gz"
    log "JDK ok: $("$TOOLS/jdk/bin/java" -version 2>&1 | head -1)"
fi

# ----------------------------------------------------------------- Ghidra
if have "$TOOLS/ghidra/support/analyzeHeadless"; then
    log "Ghidra ok: $("$TOOLS/ghidra/support/analyzeHeadless" 2>&1 | grep -i 'ghidra' | head -1)"
elif [ "$CHECK_ONLY" = 1 ]; then
    log "Ghidra AUSENTE (esperado em .tools/ghidra)"
else
    download "$GHIDRA_URL" "$TOOLS/ghidra.zip"
    log "extraindo Ghidra"
    rm -rf "$TOOLS/ghidra" "$TOOLS/ghidra_${GHIDRA_VERSION}_PUBLIC"
    ( cd "$TOOLS" && unzip -q ghidra.zip )
    mv "$TOOLS"/ghidra_*_PUBLIC "$TOOLS/ghidra"
    rm -f "$TOOLS/ghidra.zip"
    log "Ghidra ok"
fi

# ------------------------------------------------------------- venv Python
if [ -x "$TOOLS/venv/bin/python" ]; then
    log "venv ok: $("$TOOLS/venv/bin/python" -c 'import pefile,sys; print("pefile", pefile.__version__)' 2>/dev/null || echo 'sem pefile')"
elif [ "$CHECK_ONLY" = 1 ]; then
    log "venv AUSENTE (esperado em .tools/venv)"
else
    log "criando venv"
    python3 -m venv "$TOOLS/venv"
    "$TOOLS/venv/bin/pip" -q install --upgrade pip
    "$TOOLS/venv/bin/pip" -q install pefile capstone binwalk
    log "venv ok: $(command -v "$TOOLS/venv/bin/python")"
fi

# --------------------------------------------------------------- sistema
for t in objdump strings file readelf nm; do
    command -v "$t" >/dev/null || log "AVISO: falta $t (binutils)"
done
command -v radare2 >/dev/null || log "radare2 ausente (opcional: sudo apt install radare2)"
command -v unblob  >/dev/null || log "unblob ausente  (opcional: pipx install unblob)"

log "pronto. use: source tools/re-env.sh"
