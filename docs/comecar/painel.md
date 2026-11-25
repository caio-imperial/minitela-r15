# Painel gráfico

`minitela_gui.py` é um painel em tkinter (só a stdlib) que dispensa o app oficial para
tudo: tela, brilho, notificações, modo automático e as imagens.

```bash
./minitela_gui.py
```

## Como ele funciona

O app oficial segura a porta serial, então o painel precisa **assumir o controle**:

1. **Assumir controle** — ele faz `pkill -x minitela`, espera e abre o `/dev/ttyACM*`;
2. daí em diante: trocar de tela, brilho, mandar notificação, ligar o modo automático
   (relógio, bateria, CPU e wifi a cada 5 s) e enviar as imagens;
3. **Devolver ao app oficial** — apaga o socket órfão em `/tmp/minitela_socket` e religa
   o app com `setsid` e `GDK_BACKEND=x11`.

!!! note "O botão de devolver tem dois contornos"
    O app deixa o socket `/tmp/minitela_socket` órfão, e detecta instância única com
    `pgrep -f /usr/share/minitela/minitela` — que casa com o **seu próprio comando de
    shell** se você digitar o caminho inteiro. O painel monta o caminho em pedaços
    (`"mini"+"tela"`) justamente por isso.

## Imagens pelo painel

A seção **Imagens da tela** usa o `minitela_patch.py`: escolha até três arquivos (JPG, PNG
ou GIF — animado funciona) e clique em **Enviar imagens**. O status embaixo mostra cada
etapa: patch, validação, limpeza de resíduo, gravação.

A caixa **"limpar resíduo da flash antes"** vem marcada de propósito: gravar um `.acf`
menor por cima de um maior deixa o excedente na flash, e o firmware lê esse lixo como
conteúdo (tela suja e, às vezes, travamento).

## Modo automático

Com o painel no controle, marque **"manter relógio, bateria, CPU e wifi atualizados"**.
Ele lê `/proc/stat`, `/sys/class/power_supply`, `iwgetid` e `/proc/net/wireless` — tudo
nativo, sem dependências.
