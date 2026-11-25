#!/usr/bin/env bash
# re-env.sh — poe a toolchain de RE do repo no PATH desta sessao do shell.
#
#   source tools/re-env.sh
#   analyzeHeadless "$GHIDRA_PROJ" minitela -import <binario>   # Ghidra
#   python -c 'import pefile'                                   # venv com pefile/binwalk/capstone
#
# Nao escreve nada: so exporta variaveis.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export JAVA_HOME="$REPO/.tools/jdk"
export GHIDRA_HOME="$REPO/.tools/ghidra"
# O Ghidra recusa caminho com componente comecando por '.', entao os projetos
# ficam em work/ (gitignored), nao em .tools/.
export GHIDRA_PROJ="$REPO/work"
export PATH="$JAVA_HOME/bin:$GHIDRA_HOME/support:$REPO/.tools/venv/bin:$PATH"
echo "RE toolchain: java=$("$JAVA_HOME/bin/java" -version 2>&1 | head -1)  ghidra=$GHIDRA_HOME  proj=$GHIDRA_PROJ  python=$REPO/.tools/venv/bin/python"
