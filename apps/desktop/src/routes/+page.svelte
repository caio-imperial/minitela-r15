<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { open } from "@tauri-apps/plugin-dialog";
  import { onMount } from "svelte";
  import Recorte from "$lib/Recorte.svelte";
  import type { Edicao, Enquadramento, Slot } from "$lib/tipos";

  type Item = { nome: string; estado: string; detalhe: string };
  type Achado = { nivel: number; mensagem: string; dica: string };
  type Diagnostico = {
    caminho: string;
    tamanho: number;
    start: number;
    tela: [number, number];
    paginas: number;
    texturas: number;
    ok: boolean;
    achados: Achado[];
  };
  type Patch = {
    saida: string;
    tamanho: number;
    quadros: number;
    tela: [number, number];
    mudou_tamanho: boolean;
    problemas: string[];
    paginas: number[];
  };

  let itens: Item[] = $state([]);
  let carregando = $state(true);
  let erro = $state("");

  let acf = $state("");
  let diag: Diagnostico | null = $state(null);
  let slots: Slot[] = $state([]);
  let edicoes = $state<Record<number, Edicao>>({});
  let ativo = $state(0);
  let gerando = $state(false);
  let gerado: Patch | null = $state(null);
  let previasNovas = $state<Record<number, string>>({});
  let gravando = $state(false);
  let gravado = $state("");
  let parou = $state("");
  let tags = $state("");
  let daemon = $state(false);

  const kb = (n: number) => `${Math.round(n / 1024)} KB`;
  const base = (p: string) => p.split("/").pop() ?? p;

  const edicaoAtiva = $derived(edicoes[ativo] as Edicao | undefined);
  const slotAtivo = $derived(slots.find((s) => s.indice === ativo));
  const alvoAtivo = $derived(
    (edicaoAtiva?.telaCheia === false && slotAtivo
      ? [slotAtivo.w, slotAtivo.h]
      : [240, 240]) as [number, number],
  );
  const quantos = $derived(Object.keys(edicoes).length);
  const podeGerar = $derived(quantos > 0 && acf.length > 0);

  async function atualizar() {
    carregando = true;
    erro = "";
    try {
      itens = await invoke<Item[]>("ambiente");
    } catch (e) {
      erro = String(e);
    } finally {
      carregando = false;
    }
  }

  async function escolherAcf() {
    const p = await open({
      multiple: false,
      filters: [{ name: "Textura da minitela", extensions: ["acf"] }],
    });
    if (typeof p === "string") {
      acf = p;
      edicoes = {};
      previasNovas = {};
      gerado = null;
      await analisar();
    }
  }

  async function analisar() {
    erro = "";
    gerado = null;
    previasNovas = {};
    try {
      diag = await invoke<Diagnostico>("diagnostico", { caminho: acf });
      slots = await invoke<Slot[]>("slots", { caminho: acf });
      if (slots.length && !slots.some((s) => s.indice === ativo)) {
        ativo = slots[0].indice;
      }
    } catch (e) {
      diag = null;
      slots = [];
      erro = String(e);
    }
  }

  async function escolherImagem() {
    const p = await open({
      multiple: false,
      filters: [
        { name: "Imagens", extensions: ["jpg", "jpeg", "png", "gif", "bmp", "webp"] },
      ],
    });
    if (typeof p !== "string") return;
    erro = "";
    try {
      const fonte = await invoke<string>("abrir_imagem", { imagem: p });
      edicoes[ativo] = {
        imagem: p,
        fonte,
        telaCheia: true,
        ajuste: "cobrir",
        zoom: 1,
        px: 0.5,
        py: 0.5,
      };
      gerado = null;
    } catch (e) {
      erro = String(e);
    }
  }

  function mudarEnquadramento(novo: Enquadramento) {
    const atual = edicoes[ativo];
    if (atual) edicoes[ativo] = { ...atual, ...novo };
  }

  function mudarEdicao(patch: Partial<Edicao>) {
    const atual = edicoes[ativo];
    if (atual) edicoes[ativo] = { ...atual, ...patch };
  }

  function removerSlot(indice: number) {
    delete edicoes[indice];
    delete previasNovas[indice];
    gerado = null;
  }

  async function gerar() {
    if (!podeGerar) return;
    gerando = true;
    erro = "";
    gerado = null;
    try {
      const pedacos = Object.entries(edicoes).map(([k, e]) => ({
        slot: Number(k),
        imagem: e.imagem,
        telaCheia: e.telaCheia,
        ajuste: e.ajuste,
        zoom: e.zoom,
        px: e.px,
        py: e.py,
      }));
      const novo = await invoke<Patch>("patch_imagens", { caminhoAcf: acf, pedacos });
      const novas: Record<number, string> = {};
      for (const chave of Object.keys(edicoes)) {
        try {
          novas[Number(chave)] = await invoke<string>("preview", {
            caminho: novo.saida,
            slot: Number(chave),
          });
        } catch {
          /* a prévia pode falhar em textura oficial antiga; o patch já validou */
        }
      }
      previasNovas = novas;
      gerado = novo;
    } catch (e) {
      erro = String(e);
    } finally {
      gerando = false;
    }
  }

  async function pararApp() {
    erro = "";
    try {
      parou = await invoke<string>("parar_app");
      await atualizar();
    } catch (e) {
      erro = String(e);
    }
  }

  async function gravarNaTela() {
    const alvo = gerado?.saida ?? "";
    if (!alvo) return;
    gravando = true;
    erro = "";
    gravado = "";
    try {
      const r = await invoke<{ porta: string; tamanho: number; bytes: number }>("gravar", {
        caminho: alvo,
        pagina: gerado?.paginas[0] ?? null,
      });
      const segundos = Math.round(r.bytes / 100) / 10;
      gravado = `gravado em ${r.porta} (${segundos}s)`;
      if (gerado?.paginas.length) {
        gravado += ` · exibindo a página ${gerado.paginas[0]}`;
      }
    } catch (e) {
      erro = String(e);
    } finally {
      gravando = false;
    }
  }

  async function mandarTags() {
    erro = "";
    try {
      const t = await invoke<{
        relogio: string;
        bateria: number | null;
        cpu: number | null;
        wifi: string | null;
        enviadas: number;
      }>("tags_uma_vez");
      tags =
        `${t.relogio} · bateria ${t.bateria ?? "?"}% · cpu ${t.cpu ?? "?"}%` +
        (t.wifi ? ` · ${t.wifi}` : "") +
        ` · ${t.enviadas} tags`;
      await atualizar();
    } catch (e) {
      erro = String(e);
    }
  }

  async function alternarDaemon() {
    erro = "";
    try {
      daemon = await invoke<boolean>("tags_daemon", { ligar: !daemon });
    } catch (e) {
      erro = String(e);
    }
  }

  async function carregar() {
    await atualizar();
    try {
      const b = await invoke<string | null>("sugestao_base");
      if (b) {
        acf = b;
        await analisar();
      }
    } catch (e) {
      erro = String(e);
    }
  }

  onMount(carregar);
</script>

<main>
  <header>
    <div>
      <h1>Minitela</h1>
      <p class="sub">tela secundária GC9002 · Positivo Vision R15M</p>
    </div>
    <button onclick={atualizar} disabled={carregando}>
      {carregando ? "checando…" : "checar de novo"}
    </button>
  </header>

  {#if erro}
    <p class="erro">{erro}</p>
  {/if}

  <ul class="lista">
    {#each itens as item (item.nome)}
      <li class:aviso={item.estado !== "ok"}>
        <span class="ponto" aria-hidden="true"></span>
        <span class="nome">{item.nome}</span>
        <span class="detalhe">{item.detalhe}</span>
      </li>
    {/each}
  </ul>

  <section>
    <div class="topo">
      <h2>Arquivo <code>.acf</code></h2>
      <div class="acoes">
        <button onclick={escolherAcf}>escolher…</button>
        <button onclick={analisar} disabled={!acf}>analisar</button>
      </div>
    </div>
    {#if acf}
      <p class="caminho">{acf}</p>
    {/if}
    {#if diag}
      <div class="resumo" class:ruim={!diag.ok}>
        <span>{kb(diag.tamanho)}</span>
        <span>{diag.tela[0]}×{diag.tela[1]}</span>
        <span>{diag.paginas} páginas</span>
        <span>{diag.texturas} texturas</span>
        <strong>{diag.ok ? "válido" : "com problema"}</strong>
      </div>
      {#each diag.achados as a}
        <div class="achado" class:erro-a={a.nivel === 2} class:aviso-a={a.nivel === 1}>
          <span class="marca">{a.nivel === 0 ? "ok" : a.nivel === 1 ? "aviso" : "erro"}</span>
          <span>{a.mensagem}</span>
          {#if a.dica}<small>{a.dica}</small>{/if}
        </div>
      {/each}
    {/if}
  </section>

  <section>
    <div class="topo">
      <h2>Trocar imagens</h2>
      <div class="acoes">
        <button onclick={escolherImagem} disabled={!slots.length}>
          imagem para o slot {ativo + 1}…
        </button>
        <button onclick={gerar} disabled={!podeGerar || gerando}>
          {gerando ? "gerando…" : `gerar .acf${quantos > 1 ? ` (${quantos})` : ""}`}
        </button>
      </div>
    </div>

    {#if !acf}
      <p class="dica">escolha um .acf acima para listar os três slots</p>
    {:else if !slots.length}
      <p class="dica">não achei imagens (páginas 4/5/6) neste .acf</p>
    {:else}
      <div class="slots">
        {#each slots as s (s.indice)}
          {@const mini = previasNovas[s.indice] ?? s.previa}
          <figure class="slot" class:ativo={s.indice === ativo}>
            <button
              class="painel"
              onclick={() => (ativo = s.indice)}
              aria-pressed={s.indice === ativo}
              title="editar o slot {s.indice + 1}"
            >
              {#if mini}
                <img src={mini} alt="conteúdo do slot {s.indice + 1}" />
              {:else}
                <span class="vazio">—</span>
              {/if}
            </button>
            <figcaption>
              <span class="nome">slot {s.indice + 1}</span>
              <small>{s.w}×{s.h}</small>
              {#if edicoes[s.indice]}
                <span class="marca-nova">nova</span>
                <button
                  class="remover"
                  onclick={() => removerSlot(s.indice)}
                  title="desfazer esta troca"
                >
                  ×
                </button>
              {/if}
            </figcaption>
          </figure>
        {/each}
      </div>
    {/if}

    {#if edicaoAtiva}
      <Recorte
        fonte={edicaoAtiva.fonte}
        alvo={alvoAtivo}
        estado={edicaoAtiva}
        onmudar={mudarEnquadramento}
      />
      <label class="check">
        <input
          type="checkbox"
          checked={edicaoAtiva.telaCheia}
          onchange={(e) => mudarEdicao({ telaCheia: e.currentTarget.checked })}
        />
        tela cheia (240×240) — desligado mantém o tamanho original do slot
      </label>
      <p class="caminho">imagem: {base(edicaoAtiva.imagem)}</p>
    {:else if slots.length}
      <p class="dica">escolha uma imagem para o slot {ativo + 1}</p>
    {/if}

    {#if gerado}
      <div class="resumo bom">
        <span>{base(gerado.saida)}</span>
        <span>{kb(gerado.tamanho)}</span>
        <span>{gerado.tela[0]}×{gerado.tela[1]}</span>
        <span>{gerado.quadros} quadro(s)</span>
        {#if gerado.mudou_tamanho}<strong>tamanho ajustado</strong>{/if}
      </div>
      <p class="dica">
        validado antes de escrever · página{gerado.paginas.length > 1 ? "s" : ""}
        {gerado.paginas.join(", ")}
      </p>
    {/if}

    <div class="acoes">
      <button onclick={pararApp}>parar app oficial</button>
      <button onclick={gravarNaTela} disabled={!gerado || gravando}>
        {gravando ? "gravando…" : "gravar na tela"}
      </button>
    </div>
    {#if !gerado}
      <p class="dica">gere o .acf acima para habilitar a gravação</p>
    {/if}
    {#if parou}<p class="dica">{parou}</p>{/if}
    {#if gravado}<p class="dica">{gravado}</p>{/if}

    <div class="acoes">
      <button onclick={mandarTags}>mandar tags</button>
      <button onclick={alternarDaemon} class:ativo={daemon}>
        {daemon ? "parar daemon (5 s)" : "daemon (5 s)"}
      </button>
    </div>
    {#if tags}<p class="dica">{tags}</p>{/if}
  </section>

  <footer>
    <span>backend em Rust · interface em Svelte</span>
    <span class="versao">0.1.0</span>
  </footer>
</main>

<style>
  :global(body) {
    margin: 0;
    background: #0e1116;
    color: #e6e9ef;
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  }

  main {
    max-width: 860px;
    margin: 0 auto;
    padding: 26px 24px 18px;
    display: flex;
    flex-direction: column;
    min-height: 100vh;
    box-sizing: border-box;
    gap: 18px;
  }

  header,
  .topo {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
  }

  h1 {
    margin: 0;
    font-size: 26px;
    letter-spacing: -0.02em;
  }

  h2 {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
    color: #cdd4e0;
  }

  .sub {
    margin: 4px 0 0;
    color: #8b94a3;
    font-size: 13px;
  }

  .acoes {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }

  button {
    background: #1d2430;
    color: #cfd6e2;
    border: 1px solid #2b3442;
    border-radius: 8px;
    padding: 7px 13px;
    font-size: 13px;
    cursor: pointer;
  }

  button:hover:not(:disabled) {
    background: #232c3a;
  }

  button.ativo {
    border-color: #3ddc84;
    color: #3ddc84;
  }

  button:disabled {
    opacity: 0.55;
    cursor: default;
  }

  .lista {
    list-style: none;
    margin: 0;
    padding: 0;
    border: 1px solid #1f2733;
    border-radius: 10px;
    overflow: hidden;
    background: #121722;
  }

  li {
    display: grid;
    grid-template-columns: 10px 150px 1fr;
    gap: 12px;
    align-items: center;
    padding: 10px 14px;
    border-bottom: 1px solid #1b2230;
    font-size: 13.5px;
  }

  li:last-child {
    border-bottom: none;
  }

  .ponto {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #3ddc84;
  }

  li.aviso .ponto {
    background: #f5b73d;
  }

  .nome {
    color: #aab3c2;
  }

  .detalhe {
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 12.5px;
    color: #d5dbe6;
    overflow-wrap: anywhere;
  }

  section {
    border: 1px solid #1f2733;
    border-radius: 10px;
    padding: 14px;
    background: #121722;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .caminho {
    margin: 0;
    font-family: ui-monospace, monospace;
    font-size: 12px;
    color: #8b94a3;
    overflow-wrap: anywhere;
  }

  .resumo {
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
    font-size: 12.5px;
    color: #b9c2d0;
    align-items: baseline;
  }

  .resumo strong {
    color: #3ddc84;
  }

  .resumo.ruim strong {
    color: #ff7b72;
  }

  .resumo.bom strong {
    color: #3ddc84;
  }

  .slots {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
  }

  .slot {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
  }

  .slot .painel {
    padding: 0;
    aspect-ratio: 1;
    overflow: hidden;
    border-radius: 9px;
    border: 1px solid #2b3442;
    background: #000;
    display: grid;
    place-items: center;
  }

  .slot.ativo .painel {
    border-color: #3ddc84;
    box-shadow: 0 0 0 1px #3ddc84 inset;
  }

  .slot img {
    width: 100%;
    height: 100%;
    object-fit: contain;
    image-rendering: pixelated;
  }

  .vazio {
    color: #53607a;
    font-size: 18px;
  }

  .slot figcaption {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: #aab3c2;
    min-width: 0;
  }

  .slot small {
    color: #6b7482;
    font-family: ui-monospace, monospace;
  }

  .marca-nova {
    color: #3ddc84;
    border: 1px solid #2b5c43;
    border-radius: 5px;
    padding: 0 4px;
    font-size: 10.5px;
  }

  .remover {
    margin-left: auto;
    padding: 0 6px;
    line-height: 1.4;
    font-size: 12px;
    color: #8b94a3;
  }

  .achado {
    display: grid;
    grid-template-columns: 52px 1fr;
    gap: 10px;
    font-size: 12.5px;
    padding: 6px 0;
    border-top: 1px solid #1b2230;
  }

  .achado small {
    grid-column: 2;
    color: #8b94a3;
  }

  .marca {
    font-family: ui-monospace, monospace;
    font-size: 11px;
    text-transform: uppercase;
    color: #3ddc84;
  }

  .erro-a .marca {
    color: #ff7b72;
  }

  .aviso-a .marca {
    color: #f5b73d;
  }

  .check {
    display: flex;
    gap: 8px;
    align-items: center;
    font-size: 12.5px;
    color: #aab3c2;
  }

  .erro {
    color: #ff7b72;
    font-family: ui-monospace, monospace;
    font-size: 12.5px;
    margin: 0;
    white-space: pre-wrap;
  }

  .dica {
    margin: 0;
    font-size: 12px;
    color: #8b94a3;
  }

  code {
    background: #1b2230;
    border-radius: 4px;
    padding: 1px 5px;
    font-size: 11.5px;
  }

  footer {
    margin-top: auto;
    padding-top: 10px;
    display: flex;
    justify-content: space-between;
    color: #6b7482;
    font-size: 12px;
  }
</style>
