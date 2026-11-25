Este repositorio e a engenharia reversa da minitela do Positivo Vision R15M (chip GC9002,
240x240), que e um modulo com firmware proprio falando AHMI sobre USB CDC-ACM
(/dev/ttyACM*, 0324:0324). Nao e um monitor do X/Wayland.

## Antes de analisar

Leia `docs/RE-acf.md` inteiro. Ele e o caderno de laboratorio e ja contem o que foi provado:
formato de bloco, alinhamento de 16 KB, header, checksum (XOR de words LE, pulando o
proprio campo e o footer 0xA55A5AA5), estrutura de alto nivel e as pendencias.

## Alvos e atalhos

- Compilador do fabricante: `~/.local/share/minitela-custom/IDE_utils/Gen/AHMISimGenDemo_og.exe`
  (PE32 i386). Faixas quentes: `0x40A900-0x40B900` monta o container; `0x43C000-0x46E000`
  produz os dados de textura. PDB original: `AHMI_SW_Graphichina\AHMISimGen\Release`.
- App oficial: `~/.local/share/minitela-custom/appimage/squashfs-root/resources/app.asar`
  (Electron; da para ler o JS e o mapa de enderecos da flash la dentro).
- Projeto compilado que o exe consome: `IDE_utils/Gen/json/data.json` (resourceList,
  pageList, tagList com indexOfRegister, compressLevel/ditherLevel).
- Toolchain local: `.tools/ghidra`, `.tools/jdk`, `.tools/venv` (pefile/binwalk/capstone).
  Use `source tools/re-env.sh` antes de rodar qualquer coisa.

## Regras

- Todo achado carrega coordenada: endereco, offset, simbolo ou hash. Sem coordenada,
  e hipotese, e deve ser rotulada como tal.
- Nunca execute binario do fabricante nem grave nada na minitela. `minitela_ctl.py send`,
  `minitela_recover.py`, `pkill` e reboot sao operacao humana, com recuperacao armada.
- Nao inventar formato: se nao foi provado contra arquivo real ou contra o exe, diga
  "nao documentado".
- Escreva o que descobrir em `docs/RE-acf.md`, na secao certa (fato x hipotese x pendencia),
  em vez de criar notas soltas.
