# Legal e escopo

## O que este projeto é

Interoperabilidade de um aparelho que possuímos: fazer a minitela do nosso notebook
mostrar nossas imagens e dados, no nosso sistema operacional. As ferramentas conversam com
um protocolo documentado pelo próprio fabricante (planilha `GC9002串口升级协议`) e com um
formato de arquivo que o aparelho aceita.

## O que **não** é redistribuído aqui

Para manter o repositório publicável, **nada** de material proprietário entra no git:

- o SDK do fabricante (`v1.10.20`/`v1.10.21`, centenas de MB) e o IDE AHMI;
- datasheets, manuais de referência e planilhas do fabricante;
- binários de firmware (`bootloader.bin`, `cpu1.bin`, `product.bin`, `upg_cfg.bin`);
- o compilador `AHMISimGenDemo_og.exe` e as DLLs que ele usa;
- o app da Policorp (`/usr/share/minitela/`).

O site **linka** para a página pública de downloads do fabricante
([thorsianway.com/download/documentTool](https://www.thorsianway.com/download/documentTool))
e publica apenas o que produzimos: código, medições e conclusões, com endereço/offset como
evidência.

Os cadernos citam nomes de arquivo e endereços do binário analisado — o que é necessário
para reproduzir a análise — mas não incluem os binários.

## Licenças

| o quê | licença |
|---|---|
| código (`.py`, scripts) | [MIT](https://github.com/caio-imperial/minitela-r15/blob/main/LICENSE) |
| textos e diagramas (`docs/`, README) | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/deed.pt-br) |

Se você corrigir um fato técnico, o crédito é seu e a correção fica aberta pelo
share-alike.

## Marcas

Positivo, Vision, Policop, GraphiChina, AHMI, Thorsianway, XuanTie e GC9002 pertencem aos
seus donos. O uso aqui é nominativo, para descrever o aparelho e o formato. Ver
[`NOTICE`](https://github.com/caio-imperial/minitela-r15/blob/main/NOTICE).

## Risco

Gravar na flash de um dispositivo pode inutilizá-lo. O código recusa as regiões críticas
por padrão e o caminho de recuperação está documentado, mas **não há garantia**. Se o seu
aparelho for diferente do R15M com Policop, comece só com leitura (`info`, `monitor`).

## Créditos

- algoritmo do checksum do `.acf`: projeto [SideCar](https://github.com/FreyreCorona/SideCar);
- documentação do IDE AHMI: [docs.graphichina.com](https://docs.graphichina.com);
- núcleo RISC-V E902: [XUANTIE-RV/opene902](https://github.com/XUANTIE-RV/opene902);
- o resto (protocolo, formato de bloco, layout do container, GIF) foi levantado aqui, com
  bancada e teste no hardware.
