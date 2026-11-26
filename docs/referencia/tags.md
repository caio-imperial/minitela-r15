# Tags e IDs

Cada tag é um registrador do firmware, identificado por um `id` de 16 bits. O mapa abaixo
vem do `tagList` do projeto (campo `indexOfRegister`) — é o que este projeto realmente
desenha, não a lista maior do `tagUtils.js` do SDK.

```bash
./minitela_tags.py list          # imprime esta tabela
./minitela_tags.py set relogio "25/11 16:42"
```

## Sistema e navegação

| tag | id | tipo | onde |
|---|---|---|---|
| `pagina` | 2 | num | — (troca a página exibida) |
| `brilho` | 7 | num | — (0–100) |
| `tema_animacao` | 65 | num | — |
| `move_x` | 2001 | num | — |
| `move_y` | 2002 | num | — |
| `move_trigger` | 2000 | num | — |

## Topo de todas as telas

| tag | id | tipo | onde |
|---|---|---|---|
| `relogio` | 2006 | str | todas |
| `whatsapp_logo` | 2005 | num | todas |

## WhatsApp

| tag | id | tipo |
|---|---|---|
| `notif_de` | 1140 | str |
| `notif_texto` | 1141 | str |
| `msg_fundo1` | 2025 | num |
| `msg_fundo2` | 2026 | num |

## Notas

| tag | id | tipo |
|---|---|---|
| `nota` | 1090 | str |

## Monitor

| tag | id | tipo |
|---|---|---|
| `bateria` | 1082 | num |
| `bateria_tipo` | 1150 | num |
| `wifi_ssid` | 1083 | str |
| `bt_nome` | 1085 | str |

!!! note "Bateria é barra, não número"
    O widget do Monitor desenha pauzinhos (cada um vale ~20%): 42% aparece como dois.
    O estado de carga vai em `bateria_tipo` — 1 = carregando/cheia, 0 = descarregando,
    2 = sem leitura. Não existe tag de CPU neste tema.

## Clima — a tela mais generosa

Seis campos de texto: é onde dá para mostrar dados próprios com mais espaço.

| tag | id | tipo |
|---|---|---|
| `cidade` | 2027 | str |
| `temp_agora` | 2030 | str |
| `temp_prev1` | 2031 | str |
| `temp_prev2` | 2032 | str |
| `clima1_tipo` | 1110 | num |
| `clima2_tipo` | 1115 | num |
| `clima2_desc` | 1119 | str |
| `clima3_tipo` | 1120 | num |
| `clima3_desc` | 1124 | str |

## Como escrever

```bash
./minitela_tags.py set cidade "Linhares"
./minitela_tags.py set bateria 87
./minitela_tags.py notify "Fulano" "oi, tudo bem?"
./minitela_tags.py daemon            # relógio, bateria, CPU e wifi a cada 5 s
```

!!! note "O app oficial sobrescreve"
    Ele reescreve as tags a cada poucos segundos. Para as suas valerem, pare o app
    (`pkill -x minitela`); um daemon próprio precisa *substituir* o app, não conviver.

Formato dos frames e limites em [Protocolo AHMI](protocolo.md).
