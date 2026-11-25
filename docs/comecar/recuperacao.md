# Recuperar a tela

Gravar um `.acf` que o firmware não consegue renderizar trava o render: a tela congela e
o dispositivo para de responder — o app oficial também deixa de abrir, porque bloqueia
esperando resposta.

**É recuperável.** Só a região de textura é escrita; bootloader e calibração não são
tocados.

## O sintoma

- a tela mostra uma página estática ou uma tela de "Information";
- `./minitela_ctl.py info` responde com `status 0x10` e `fileId` zerado;
- o app oficial não abre.

## O primeiro socorro: reboot

Na maioria dos casos um **reboot de verdade** devolve a tela. Não é `authorized 0/1` no
sysfs — o módulo continua alimentado; tem que ser corte real de energia.

Se a tela voltar, siga a vida normalmente. O `status 0x10` com `fileId` zerado é o estado
normal depois do boot, até o app começar a conversar.

## Se voltar travada: regravar

Com o dispositivo respondendo (mesmo que mal), regrave um `.acf` de fábrica:

```bash
pkill -x minitela
./minitela_ctl.py --force send /usr/share/minitela/resources/ACF/Texture.acf -y
```

`--force` serve para tentar mesmo com o app rodando. Se der `EIO`, a porta provavelmente
morreu porque o USB renumerou — espere e use a porta nova (`ls /dev/ttyACM*`).

## Recuperação automática no login

Quando a tela trava no boot e não dá tempo de rodar na mão, arme um `.desktop` em
`~/.config/autostart/`:

```ini
[Desktop Entry]
Type=Application
Name=Recupera minitela
Exec=/bin/bash -c "sleep 3; /caminho/minitela_recover.py --timeout 900 > /tmp/minitela-recover.log 2>&1"
```

Reinicie o notebook. O script fica tentando até conseguir e grava o tema de fábrica assim
que o dispositivo responder na janela do boot. O log fica em `/tmp/minitela-recover.log`.

## Cuidado que evita o problema

- deixar **"limpar resíduo da flash antes"** marcado no painel;
- preferir `minitela_patch.py` (não mexe na configuração) a recompilar;
- antes de qualquer gravação, ter à mão o `.acf` de fábrica — ele está no pacote, em
  `/usr/share/minitela/resources/ACF/`.

!!! danger "O que não fazer"
    Não gravar nas regiões `bootloader`, `cpu1`, `calibration`, `hwconfig` ou `product`
    pelo protocolo. O `minitela_ctl.py` recusa essas regiões por padrão, e não há backup
    delas no pacote — especialmente a calibração, que é por unidade.
