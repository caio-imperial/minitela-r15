#!/usr/bin/env python3
"""
minitela_gui.py — painel para controlar a Minitela sem o app oficial.

Troca de tela, brilho, notificações e um modo automático que mantém relógio, bateria,
CPU e wifi atualizados. Só tkinter (que vem com o Python), sem dependências.

O app oficial segura a porta serial, então o painel precisa assumir o controle: o botão
"Assumir controle" para o app, e "Devolver ao app oficial" religa. Nada aqui toca na
flash — é tudo tag, atualização instantânea e sem risco.

Uso:
    ./minitela_gui.py
"""

import importlib.util
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

HERE = os.path.dirname(os.path.abspath(__file__))


def _carrega(nome):
    spec = importlib.util.spec_from_file_location(nome, os.path.join(HERE, f"{nome}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mc = _carrega("minitela_ctl")
mt = _carrega("minitela_tags")

# A seção do Baiakidle saiu do painel: ela dependia de uma tela extra (página 8) que o
# firmware não renderiza. O exemplo continua no repo como CLI: exemplos/baiakidle.py
baiak = None

# As páginas do firmware são 1-based: a página 1 é a primeira do projeto (WhatsApp).
# O app oficial faz o mesmo — `curSystemPage = pageId - 1` no electron.js do MiniPanel.
TELAS = [
    ("WhatsApp", 1), ("Notas", 2), ("Monitor", 3), ("Clima", 4),
    ("GIF 1", 5), ("GIF 2", 6), ("GIF 3", 7),
]


class Painel:
    def __init__(self, root):
        self.root = root
        self.tags = None
        self.auto = False
        self.baiak_auto = False
        self.thread = None
        root.title("Minitela — painel")
        root.resizable(False, False)

        pad = {"padx": 10, "pady": 6}
        topo = ttk.Frame(root); topo.grid(row=0, column=0, sticky="ew", **pad)
        self.lbl_status = ttk.Label(topo, text="desconectado", foreground="#a00")
        self.lbl_status.grid(row=0, column=0, sticky="w")
        self.bt_controle = ttk.Button(topo, text="Assumir controle", command=self.assumir)
        self.bt_controle.grid(row=0, column=1, padx=(20, 0))

        telas = ttk.LabelFrame(root, text="Tela"); telas.grid(row=1, column=0, sticky="ew", **pad)
        self.bts = []
        for i, (nome, pag) in enumerate(TELAS):
            b = ttk.Button(telas, text=nome, width=11, state="disabled",
                           command=lambda p=pag, n=nome: self.mostrar(p, n))
            b.grid(row=i // 4, column=i % 4, padx=4, pady=4)
            self.bts.append(b)

        brilho = ttk.LabelFrame(root, text="Brilho"); brilho.grid(row=2, column=0, sticky="ew", **pad)
        self.var_brilho = tk.IntVar(value=100)
        self.sld = ttk.Scale(brilho, from_=0, to=100, variable=self.var_brilho,
                             length=330, command=self.brilho_mudou, state="disabled")
        self.sld.grid(row=0, column=0, padx=8, pady=6)
        self.lbl_brilho = ttk.Label(brilho, text="100%", width=5)
        self.lbl_brilho.grid(row=0, column=1)

        notif = ttk.LabelFrame(root, text="Mandar notificação"); notif.grid(row=3, column=0, sticky="ew", **pad)
        ttk.Label(notif, text="de:").grid(row=0, column=0, sticky="e", padx=(8, 4))
        self.e_de = ttk.Entry(notif, width=14); self.e_de.grid(row=0, column=1, pady=4)
        ttk.Label(notif, text="texto:").grid(row=0, column=2, sticky="e", padx=(8, 4))
        self.e_txt = ttk.Entry(notif, width=22); self.e_txt.grid(row=0, column=3, pady=4)
        self.bt_notif = ttk.Button(notif, text="Enviar", command=self.enviar_notif, state="disabled")
        self.bt_notif.grid(row=0, column=4, padx=8)

        auto = ttk.LabelFrame(root, text="Automático"); auto.grid(row=4, column=0, sticky="ew", **pad)
        self.var_auto = tk.BooleanVar(value=False)
        self.chk = ttk.Checkbutton(auto, text="manter relógio, bateria, CPU e wifi atualizados",
                                   variable=self.var_auto, command=self.toggle_auto, state="disabled")
        self.chk.grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.lbl_auto = ttk.Label(auto, text="", foreground="#555")
        self.lbl_auto.grid(row=1, column=0, sticky="w", padx=8, pady=(0, 6))

        img = ttk.LabelFrame(root, text="Imagens da tela  (grava na flash — leva ~20s)")
        img.grid(row=5, column=0, sticky="ew", **pad)
        self.imgs = [None, None, None]
        self.lbl_img = []
        for i in range(3):
            ttk.Label(img, text=f"{i+1}:").grid(row=i, column=0, sticky="e", padx=(8, 2), pady=2)
            lb = ttk.Label(img, text="(de fábrica)", width=30, foreground="#777")
            lb.grid(row=i, column=1, sticky="w")
            self.lbl_img.append(lb)
            ttk.Button(img, text="escolher…", width=10,
                       command=lambda k=i: self.escolher_img(k)).grid(row=i, column=2, padx=4)
            ttk.Button(img, text="limpar", width=7,
                       command=lambda k=i: self.limpar_img(k)).grid(row=i, column=3, padx=(0, 8))
        self.var_limpa = tk.BooleanVar(value=True)
        ttk.Checkbutton(img, text="limpar resíduo da flash antes (recomendado)",
                        variable=self.var_limpa).grid(row=3, column=0, columnspan=3,
                                                      sticky="w", padx=8, pady=(4, 0))
        self.bt_grava = ttk.Button(img, text="Enviar imagens", command=self.enviar_imgs,
                                   state="disabled")
        self.bt_grava.grid(row=3, column=3, padx=8, pady=(4, 6))
        self.lbl_img_st = ttk.Label(img, text="", foreground="#555")
        self.lbl_img_st.grid(row=4, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 6))

        if baiak:
            bk = ttk.LabelFrame(root, text="Baiakidle (aparece na tela Clima)")
            bk.grid(row=6, column=0, sticky="ew", **pad)
            ttk.Label(bk, text="personagem:").grid(row=0, column=0, sticky="e", padx=(8, 4))
            self.e_char = ttk.Entry(bk, width=18)
            self.e_char.insert(0, "haha lafon")
            self.e_char.grid(row=0, column=1, pady=4)
            self.bt_baiak = ttk.Button(bk, text="Mostrar", command=self.baiak_agora,
                                       state="disabled")
            self.bt_baiak.grid(row=0, column=2, padx=6)
            self.var_baiak = tk.BooleanVar(value=False)
            self.chk_baiak = ttk.Checkbutton(bk, text="a cada 60s", variable=self.var_baiak,
                                             command=self.toggle_baiak, state="disabled")
            self.chk_baiak.grid(row=0, column=3, padx=(4, 8))
            self.lbl_baiak = ttk.Label(bk, text="", foreground="#555")
            self.lbl_baiak.grid(row=1, column=0, columnspan=4, sticky="w", padx=8, pady=(0, 6))

        self.lbl_msg = ttk.Label(root, text="", foreground="#555")
        self.lbl_msg.grid(row=7, column=0, sticky="w", padx=12, pady=(0, 10))
        root.protocol("WM_DELETE_WINDOW", self.fechar)

    # ------------------------------------------------------------- controle

    def msg(self, texto, cor="#555"):
        self.lbl_msg.config(text=texto, foreground=cor)

    def habilita(self, ligado):
        estado = "normal" if ligado else "disabled"
        for b in self.bts:
            b.config(state=estado)
        self.sld.config(state=estado)
        self.bt_notif.config(state=estado)
        self.chk.config(state=estado)
        self.bt_grava.config(state=estado)
        if baiak:
            self.bt_baiak.config(state=estado)
            self.chk_baiak.config(state=estado)

    def assumir(self):
        if self.tags:
            return self.devolver()
        if mc.app_running():
            subprocess.run(["pkill", "-x", "minitela"])
            time.sleep(2)
        porta = mc.find_port()
        if not porta:
            messagebox.showerror("Minitela", "Nenhuma porta /dev/ttyACM* encontrada.\n"
                                             "A minitela está conectada?")
            return
        try:
            self.tags = mt.Tags(porta)
        except OSError as e:
            messagebox.showerror("Minitela", f"Não consegui abrir {porta}:\n{e}")
            return
        self.lbl_status.config(text=f"conectado em {porta}", foreground="#070")
        self.bt_controle.config(text="Devolver ao app oficial")
        self.habilita(True)
        self.msg("controle assumido — o app oficial está parado")

    def devolver(self):
        self.var_auto.set(False); self.auto = False; self.baiak_auto = False
        if self.tags:
            self.tags.close(); self.tags = None
        self.habilita(False)
        self.lbl_status.config(text="desconectado", foreground="#a00")
        self.bt_controle.config(text="Assumir controle")
        try:
            os.remove("/tmp/minitela_socket")
        except OSError:
            pass
        # o app detecta instância única com pgrep -f no caminho inteiro: montamos o caminho
        # em pedaços para o nosso próprio comando não ser confundido com uma instância
        caminho = os.path.join("/usr", "share", "mini" + "tela", "mini" + "tela")
        env = dict(os.environ, DISPLAY=os.environ.get("DISPLAY", ":0"), GDK_BACKEND="x11")
        subprocess.Popen(["setsid", caminho], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
        self.msg("app oficial religado")

    # --------------------------------------------------------------- ações

    def mostrar(self, pagina, nome):
        if not self.tags:
            return
        self.tags._envia(mt.frame_nums([(mt.TAGS["pagina"][0], pagina)]))
        self.msg(f"tela: {nome}")

    def brilho_mudou(self, _=None):
        v = int(float(self.var_brilho.get()))
        self.lbl_brilho.config(text=f"{v}%")
        if self.tags:
            self.tags._envia(mt.frame_nums([(mt.TAGS["brilho"][0], v)]))

    def enviar_notif(self):
        if not self.tags:
            return
        de = self.e_de.get().strip() or "Aviso"
        txt = self.e_txt.get().strip()
        if not txt:
            self.msg("escreva o texto da notificação", "#a00")
            return
        self.tags.set("notif_de", de)
        self.tags.set("notif_texto", txt)
        self.msg(f"notificação enviada: {de}")

    # --------------------------------------------------------------- imagens

    def escolher_img(self, k):
        caminho = filedialog.askopenfilename(
            title=f"Imagem {k+1}",
            filetypes=[("Imagens", "*.jpg *.jpeg *.png *.gif *.bmp *.webp"), ("Todos", "*.*")])
        if caminho:
            self.imgs[k] = caminho
            self.lbl_img[k].config(text=os.path.basename(caminho), foreground="#000")

    def limpar_img(self, k):
        self.imgs[k] = None
        self.lbl_img[k].config(text="(de fábrica)", foreground="#777")

    def enviar_imgs(self):
        if not any(self.imgs):
            self.lbl_img_st.config(text="escolha ao menos uma imagem")
            return
        if not messagebox.askyesno(
                "Gravar na minitela",
                "Isto regrava a textura na flash (~20s).\n\n"
                "Se o firmware não conseguir renderizar o resultado, a tela trava e é\n"
                "preciso reiniciar o notebook com o minitela_recover.py armado.\n\nContinuar?"):
            return
        self.bt_grava.config(state="disabled")
        threading.Thread(target=self._grava_imgs, daemon=True).start()

    def _grava_imgs(self):
        def st(txt):
            self.root.after(0, lambda: self.lbl_img_st.config(text=txt))
        try:
            # a porta precisa estar livre para gravar
            if self.tags:
                self.tags.close(); self.tags = None

            imgs = [c for c in self.imgs if c]
            out_dir = os.path.expanduser("~/.local/share/minitela-custom/out")
            template = os.path.join(out_dir, "minitela.acf")
            acf = None

            # Caminho sem wine: troca só as texturas de um .acf que já funciona.
            # Se o template não existir (ou não validar), cai para o compilador.
            if os.path.exists(template):
                st("trocando as imagens (sem wine)…")
                destino = os.path.join(out_dir, "minitela-patch.acf")
                r = subprocess.run(
                    [os.path.join(HERE, "minitela_patch.py"),
                     "--template", template, "--out", destino] + imgs,
                    capture_output=True, text=True, timeout=300)
                if "validação OK" in r.stdout:
                    acf = destino
                else:
                    print(r.stdout[-1500:], r.stderr[-800:])
                    st("o patch não validou — caindo para o compilador (wine)")

            if acf is None:
                st("compilando a textura (wine)…")
                r = subprocess.run(
                    [os.path.join(HERE, "minitela_build.py"), "build"] + imgs,
                    capture_output=True, text=True, timeout=600)
                if "pronto:" not in r.stdout:
                    st("falha ao compilar — veja o terminal")
                    print(r.stdout[-1500:], r.stderr[-500:])
                    return
                acf = template

            ctl = os.path.join(HERE, "minitela_ctl.py")
            subprocess.run(["pkill", "-x", "minitela"])
            time.sleep(2)
            if self.var_limpa.get():
                # gravar um .acf menor por cima de um maior deixa resíduo na flash, e o
                # firmware lê esse lixo como conteúdo (foi o que travou a tela nas nossas
                # tentativas). Gravar o maior de fábrica antes zera a região.
                st("limpando resíduo da flash (grava um .acf maior antes)…")
                subprocess.run([ctl, "--force", "send",
                                "/usr/share/minitela/resources/ACF/Texture16.acf", "-y"],
                               capture_output=True, timeout=600)
                time.sleep(8)
            st("gravando as imagens…")
            g = subprocess.run([ctl, "--force", "send", acf, "-y"],
                               capture_output=True, text=True, timeout=600)
            if "gravado com sucesso" in g.stdout:
                st("pronto — reabra o app e vá até a tela Imagens")
            else:
                st("a gravação não confirmou; verifique a minitela")
        except Exception as e:
            st(f"erro: {e}")
        finally:
            self.root.after(0, lambda: self.bt_grava.config(state="normal"))

    # ------------------------------------------------------------- baiakidle

    def baiak_agora(self):
        if not (self.tags and baiak):
            return
        nome = self.e_char.get().strip()
        if not nome:
            self.msg("escreva o nome do personagem", "#a00")
            return
        try:
            dados = baiak.campos(baiak.busca(nome))
            baiak.envia(self.tags, dados)
            self.lbl_baiak.config(text=" · ".join(dados.values()))
            self.mostrar(8, "Baiakidle")
        except Exception as e:
            self.lbl_baiak.config(text=f"falhou: {e}")

    def toggle_baiak(self):
        self.baiak_auto = self.var_baiak.get()
        if self.baiak_auto:
            threading.Thread(target=self._loop_baiak, daemon=True).start()

    def _loop_baiak(self):
        while self.baiak_auto and self.tags:
            self.root.after(0, self.baiak_agora)
            for _ in range(600):
                if not self.baiak_auto:
                    break
                time.sleep(0.1)

    # ------------------------------------------------------------ automático

    def toggle_auto(self):
        self.auto = self.var_auto.get()
        if self.auto and (not self.thread or not self.thread.is_alive()):
            self.thread = threading.Thread(target=self._loop_auto, daemon=True)
            self.thread.start()
        if not self.auto:
            self.lbl_auto.config(text="")

    def _loop_auto(self):
        mt.cpu_uso()
        while self.auto and self.tags:
            dados = {"relogio": time.strftime("%d/%m %H:%M")}
            pct, _ = mt.bateria()
            if pct is not None:
                dados["bateria"] = pct
            c = mt.cpu_uso()
            if c is not None:
                dados["cpu"] = c
            ssid, qual = mt.wifi()
            if ssid:
                dados["wifi_ssid"] = ssid; dados["wifi_status"] = 1
            if qual is not None:
                dados["wifi_sinal"] = qual
            try:
                self.tags.set_muitos(dados)
            except OSError:
                break
            resumo = " · ".join(f"{k}={v}" for k, v in dados.items())
            self.root.after(0, lambda r=resumo: self.lbl_auto.config(text=r))
            for _ in range(50):
                if not self.auto:
                    break
                time.sleep(0.1)

    def fechar(self):
        self.auto = False
        if self.tags:
            self.tags.close()
        self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except tk.TclError:
        pass
    Painel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
