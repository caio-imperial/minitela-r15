# Contribuir

O projeto é pequeno e o critério é simples: **toda afirmação técnica precisa de
coordenada**. Endereço, offset, linha de arquivo ou saída de comando. Sem isso, é hipótese
— e hipótese também é bem-vinda, desde que rotulada.

## A regra de evidência

| rótulo | significado |
|---|---|
| **FATO** | provado contra arquivo real, hardware ou código do fabricante; com coordenada |
| **HIPÓTESE** | inferência plausível, marcada como tal |
| **NÃO DOCUMENTADO** | não dá para saber com o que temos |

Nos cadernos (`docs/RE-*.md`), cada fato tem endereço/símbolo/offset. Em código, cada
decisão estranha tem um comentário explicando *por quê* (foi o que evitou repetir becos sem
saída).

## Antes de abrir um PR

- [ ] rodei `python3 -m py_compile` nos arquivos que mexi;
- [ ] rodei `./acf_inspect.py /usr/share/minitela/resources/ACF/*.acf` (deve dar 0 problemas);
- [ ] se mexi em documentação, `mkdocs build --strict` passa (use `python3 -m venv .tools/docs-venv` + `pip install "mkdocs-material==9.*"`);
- [ ] não incluí SDK, datasheet, binário de firmware nem o app da Policorp;
- [ ] se testei no hardware, digo **o que** foi gravado e **como** verifiquei.

## Testar sem brickar

1. Comece por leitura: `./minitela_ctl.py info`, `monitor`.
2. Tenha o `.acf` de fábrica à mão (`/usr/share/minitela/resources/ACF/Texture.acf`).
3. Prefira arquivos pequenos; valide **antes** com `acf_inspect.py`.
4. Só grave regiões de textura. `bootloader`, `cpu1`, `calibration`, `hwconfig` e
   `product` são recusadas pelo `minitela_ctl.py` por um motivo.
5. Se travar: [Recuperar a tela](comecar/recuperacao.md).

## Estilo de código

- Python puro, **stdlib apenas**, sem dependências novas — é o que faz a ferramenta rodar
  em qualquer máquina com Python;
- os módulos se carregam por caminho (`_carrega`), então ficam na raiz;
- mensagens em português, sem acento nos identificadores e nos commits;
- nada de `sudo`; nada de root.

## Onde mexer

| quero… | arquivo |
|---|---|
| mudar o protocolo | `minitela_ctl.py` |
| mandar mais dados sem gravar | `minitela_tags.py` |
| melhorar a compressão/imagem | `acf_codec.py` |
| mexer no patch ou no GIF | `minitela_patch.py`, `acf_anim.py` |
| validar/entender um arquivo | `acf_inspect.py` |
| análise de binário | `tools/` (Ghidra) e `docs/RE-*.md` |

## Documentação

O site é gerado do `docs/` com MkDocs. Regras:

- guia (**Começar**) explica *como fazer*; a **Referência** destila o formato;
- os cadernos `RE-*.md` guardam a prova — não duplique número/offset nos guias, **linke**
  para o FATO (`../RE-acf.md#fato-10-...`);
- "limitação conhecida" é uma seção, não uma promessa.

## Abrindo issue

Há dois modelos no repositório: **bug** (algo não funciona) e **ideia** (algo que daria para
fazer). Para bug, inclua: modelo do notebook, saída de `./minitela_ctl.py info`, o comando
que falhou e o que a tela mostrou. Nunca cole chaves ou dados pessoais.

## Licença

Ao contribuir você concorda em publicar sob as licenças do projeto: código **MIT**, textos
**CC BY-SA 4.0**. Ver [Legal](legal.md).
