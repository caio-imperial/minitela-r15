# Enviar uma imagem

Três imagens podem ocupar a tela **Imagens** do app (as setas `<` `>` navegam entre elas).
O caminho abaixo **não usa wine**: parte de um `.acf` que o firmware já aceita e troca só
os bytes das texturas.

## Primeiro: tenha um template

O template é um `.acf` válido, gerado uma vez (por firmware/screen). Normalmente já existe:

```
~/.local/share/minitela-custom/out/minitela.acf
```

Se não existir, gere com o compilador (só nesta etapa o wine entra):

```bash
./minitela_build.py setup
./minitela_build.py build ~/alguma_foto.jpg
```

## Sem template nenhum (nem wine, nunca)

O próprio tema de fábrica serve de base. Ele tem os três slots em **192×192** (o
template compilado por nós usa 240×240):

```bash
./minitela_patch.py --template /usr/share/minitela/resources/ACF/Texture.acf \
                    --out ~/minha.acf ~/foto.jpg --send
```

Só o `Texture.acf` (o tema padrão) funciona como base — os `Texture1..21.acf` não têm as
três texturas de imagem nas páginas 4/5/6.

### Tela cheia sem wine

O slot do tema de fábrica é 192×192. Para usar 240×240 (a resolução da tela) sem
recompilar, peça `--tela-cheia`: ele muda o tamanho da textura, atualiza o registro e
reloca o resto do arquivo — o mesmo mecanismo do GIF.

```bash
./minitela_patch.py --template /usr/share/minitela/resources/ACF/Texture.acf \
                    --out ~/minha.acf --tela-cheia ~/foto.jpg --send
```

As três juntas dão um arquivo de 901.128 B — exatamente o tamanho do template que o
compilador gera com imagens 240×240.

## Trocar as imagens

```bash
# 1 imagem (os outros slots ficam como no template)
./minitela_patch.py --template ~/.local/share/minitela-custom/out/minitela.acf \
                    --out ~/minha.acf ~/foto.jpg

# 3 imagens
./minitela_patch.py --out ~/minha.acf ~/a.jpg ~/b.png ~/c.gif

# e gravar
./minitela_patch.py --out ~/minha.acf ~/a.jpg --send
```

O que ele faz, em ordem:

1. recorta no centro e escala para o tamanho da textura (240×240 no template compilado);
2. converte para o **formato de bloco do chip** (STC, blocos 4×4 de 16 B);
3. escreve nos offsets da tabela de texturas;
4. valida com o `acf_inspect.py` — magic, versão e o `CheckCode` de **todas** as páginas;
5. só então grava.

Se a validação falhar, ele não grava nada.

## Depois de gravar

Abra o app pelo **botão dedicado do teclado** e vá até a tela **Imagens**. Se ela não
aparecer ao passar pelo botão, pode estar desabilitada — ligue "Imagens" na lista de
telas, ou:

```bash
gsettings set org.policorp.minitela saved-screens "[true,true,true,true,true,true,true]"
```

## Conferir sem gravar

```bash
./acf_inspect.py --textures ~/minha.acf | head -20   # lista as texturas
./acf_inspect.py --diagnostico ~/minha.acf           # explica o que quebrou, se quebrou
```

Você vê as páginas, o número de texturas e, com `--textures`, cada textura com tipo,
dimensão e endereço.

## Voltar ao original

```bash
pkill -x minitela
./minitela_ctl.py send /usr/share/minitela/resources/ACF/Texture.acf -y
```

!!! tip "Por que isso é seguro"
    As texturas ficam **antes** da configuração do arquivo (que começa em
    `StartOfConfigdata`), e o firmware só valida o checksum de cada bloco de página.
    Trocar textura não invalida nada; o resto do `.acf` continua byte a byte idêntico.
    Detalhe em [`RE-acf.md`](../RE-acf.md#fato-10-imagem-trocada-sem-o-compilador-testado-no-hardware).
