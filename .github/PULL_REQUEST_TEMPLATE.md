## O que muda

<!-- uma ou duas frases -->

## Evidência

<!-- Para mudança técnica: endereço, offset, arquivo:linha ou saída de comando.
     Para texto: link para o FATO correspondente em docs/RE-*.md. -->

## Verificação

- [ ] `python3 -m py_compile` nos arquivos alterados
- [ ] `./acf_inspect.py /usr/share/minitela/resources/ACF/*.acf` → 0 problemas
- [ ] `mkdocs build --strict` (se mexi em docs)
- [ ] se gravei no hardware: descrevo o arquivo, o comando e o que apareceu na tela

## Cuidado

- [ ] não incluí SDK, datasheet, binário de firmware nem o app da Policorp
- [ ] não gravei em região crítica (`bootloader`, `cpu1`, `calibration`, `hwconfig`, `product`)
