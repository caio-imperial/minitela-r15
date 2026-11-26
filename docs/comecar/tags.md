# Tags em tempo real

Isto **não mexe na flash**: são variáveis que o firmware já sabe desenhar. Manda o valor
e a tela atualiza na hora. Risco zero — dá para testar à vontade.

```bash
./minitela_tags.py list                    # o mapa das tags (id + tela)
./minitela_tags.py set relogio "25/11 16:42"
./minitela_tags.py set bateria 87
./minitela_tags.py set cidade "Linhares"
./minitela_tags.py notify "Fulano" "oi, tudo bem?"
./minitela_tags.py daemon                  # relógio, bateria, CPU e wifi a cada 5 s
```

## Onde cada tag aparece

O mapa real vem do `tagList` do projeto: cada tag tem um id (o registrador no firmware) e
a tela onde é desenhada. Algumas não têm tela (`pagina`, `brilho`, controles).

| tela | tags de texto disponíveis |
|---|---|
| todas | `relogio` |
| WhatsApp | `notif_de`, `notif_texto` |
| Notas | `nota` |
| Monitor | `bateria` (texto `"100%"`), `bateria_tipo` (nível da barra), `wifi_ssid`, `bt_nome` |
| **Clima** | `cidade`, `temp_agora`, `temp_prev1`, `temp_prev2` — **seis campos**, a mais generosa |

Rode `./minitela_tags.py list` para a lista completa com ids.

## Dois detalhes que só aparecem na tela

- **bateria**: o texto (`1082`) é **string** — `"100%"`; mandar número apaga a
  porcentagem. A **barra** é outro registrador (`bateria_tipo`, 1150) e desenha
  `nível + 1` pauzinhos (`0 → 1`, `3 → 4`).
- **ícones do clima** (`clima1_tipo`/`2`/`3`): `0` sol, `1` sol entre nuvens, `2` nuvem,
  `3` chuva, `4` lua, `5` lua entre nuvens, `6` nuvem com neve. Não existem 7 nem 8, e
  não há ícone de trovoada.

Nunca mande número num registrador de texto (nem o contrário): o firmware não confere
tipo nem faixa e a tela pode ficar muda — já aconteceu duas vezes aqui.

## O app oficial briga com você

O app da Policorp reescreve todas as tags a cada poucos segundos com os dados dele — as
suas somem quase na hora. Para valer, **pare o app**:

```bash
pkill -x minitela
```

Um daemon próprio precisa *substituir* o app, não conviver com ele.

## Formato dos frames

```
texto:  AH | ctrl | 0090 | 0xD0 | regId(2,BE) | tamanho(2,BE) | UTF-8 | crc | MI
número: AH | ctrl | 0090 | 0x8N | [regId(2,BE) valor(4,BE)] × (N+1) | crc | MI
```

Limite de 16 tags por frame. O CRC existe no frame mas o firmware **ignora** — o app
oficial manda `0x0000` sempre.

## Plugar uma API sua

[`exemplos/baiakidle.py`](https://github.com/caio-imperial/minitela-r15/blob/main/exemplos/baiakidle.py)
é um exemplo completo: busca dados numa API pública, formata em linhas curtas e escreve
nas tags da tela Clima. Serve de molde para clima, ações, placar, o que você quiser.
