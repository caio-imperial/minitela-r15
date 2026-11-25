<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { open } from "@tauri-apps/plugin-dialog";
  import { onMount } from "svelte";

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
  };

  let itens: Item[] = $state([]);
  let carregando = $state(true);
  let erro = $state("");

  let acf = $state("");
  let diag: Diagnostico | null = $state(null);
  let imagem = $state("");
  let telaCheia = $state(true);
  let gerando = $state(false);
  let gerado: Patch | null = $state(null);
  let gravando = $state(false);
  let gravado = $state("");
  let parou = $state("");

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
      await analisar();
    }
  }

  async function analisar() {
    erro = "";
    gerado = null;
    try {
      diag = await invoke<Diagnostico>("diagnostico", { caminho: acf });
    } catch (e) {
      diag = null;
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
    if (typeof p === "string") imagem = p;
  }

  async function gerar() {
    if (!acf || !imagem) return;
    gerando = true;
    erro = "";
    gerado = null;
    try {
      gerado = await invoke<Patch>("patch_imagem", {
        caminhoAcf: acf,
        imagem,
        telaCheia,
      });
    } catch (e) {
      erro = String(e);
    } finally {
      gerando = false;
    }
  }

  async function pararApp() {
    erro = "";
    try {
      const r = await invoke<boolean>("parar_app");
      parou = r ? "app oficial fechado" : "o app oficial já estava parado";
      await atualizar();
    } catch (e) {
      erro = String(e);
    }
  }

  async function gravarNaTela() {
    const alvo = gerado?.saida ?? acf;
    if (!alvo) return;
    gravando = true;
    erro = "";
    gravado = "";
    try {
      const r = await invoke<{ porta: string; tamanho: number; bytes: number }>("gravar", {
        caminho: alvo,
        pagina: 5,
      });
      gravado = `gravado em ${r.porta} (${Math.round(r.bytes / 100) / 10}s)`;
    } catch (e) {
      erro = String(e);
    } finally {
      gravando = false;
    }
  }

  const kb = (n: number) => `${Math.round(n / 1024)} KB`;
  const base = (p: string) => p.split("/").pop() ?? p;

  onMount(atualizar);
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
      <h2>Trocar imagem</h2>
      <div class="acoes">
        <button onclick={escolherImagem}>imagem…</button>
        <button onclick={gerar} disabled={!acf || !imagem || gerando}>
          {gerando ? "gerando…" : "gerar .acf"}
        </button>
      </div>
    </div>
    {#if imagem}
      <p class="caminho">{base(imagem)}</p>
    {/if}
    <label class="check">
      <input type="checkbox" bind:checked={telaCheia} />
      tela cheia (240×240; sem isso usa o tamanho do slot)
    </label>
    {#if gerado}
      <div class="resumo bom">
        <span>{base(gerado.saida)}</span>
        <span>{kb(gerado.tamanho)}</span>
        <span>{gerado.tela[0]}×{gerado.tela[1]}</span>
        <span>{gerado.quadros} quadro(s)</span>
        {#if gerado.mudou_tamanho}<strong>tamanho ajustado</strong>{/if}
      </div>
      <p class="dica">validado antes de escrever.</p>
    {/if}

    <div class="acoes">
      <button onclick={pararApp}>parar app oficial</button>
      <button onclick={gravarNaTela} disabled={(!gerado && !acf) || gravando}>
        {gravando ? "gravando…" : "gravar na tela"}
      </button>
    </div>
    {#if parou}<p class="dica">{parou}</p>{/if}
    {#if gravado}<p class="dica">{gravado}</p>{/if}
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
