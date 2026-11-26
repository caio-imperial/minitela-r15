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
    paginas_visiveis: number;
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
  type Clima = { cidade: string; dias: { rotulo: string; faixa: string }[] };
  type Controle = {
    conectado: boolean;
    porta: string | null;
    paginas: number;
    app_oficial: boolean;
    /** "o seu", "outro", "sem customizacao", "o seu (restaurado)" */
    tema: string;
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
  let estadoTags = $state<string | null>(null);
  let clima: Clima | null = $state(null);
  let cidade = $state("");
  let buscandoClima = $state(false);
  /** páginas desativadas só neste app (não mexe no .acf nem no firmware) */
  let desativadas = $state<number[]>([]);

  let controle: Controle = $state({
    conectado: false,
    porta: null,
    paginas: 0,
    app_oficial: false,
    tema: "—",
  });
  let assumindo = $state(false);
  // 1-based, como o firmware conta: as três imagens são 5, 6 e 7
  let paginaAtual = $state(5);
  let brilhoAtual = $state(100);
  let brilhoTimer: ReturnType<typeof setTimeout> | undefined;

  const kb = (n: number) => `${Math.round(n / 1024)} KB`;
  const base = (p: string) => p.split("/").pop() ?? p;

  // `diag` recebe um valor só depois do primeiro `analisar()`: dentro de `$derived`
  // o TS estreita o tipo para `null`, por isso o total vem por função.
  function totalPaginas(d: Diagnostico | null, c: Controle) {
    return d?.paginas_visiveis || c.paginas || 0;
  }
  const paginasTotal = $derived(totalPaginas(diag, controle));
  const puladas = $derived(new Set(desativadas));
  const podeVoltar = $derived(controle.conectado && proxima(paginaAtual, -1) !== null);
  const podeAvancar = $derived(controle.conectado && proxima(paginaAtual, 1) !== null);

  const chaveDesativadas = () => `minitela.desativadas:${acf}`;

  function carregaDesativadas() {
    try {
      const bruto = localStorage.getItem(chaveDesativadas());
      desativadas = bruto ? JSON.parse(bruto) : [];
    } catch {
      desativadas = [];
    }
  }

  function alternarDesativada(n: number) {
    desativadas = desativadas.includes(n)
      ? desativadas.filter((x) => x !== n)
      : [...desativadas, n];
    try {
      localStorage.setItem(chaveDesativadas(), JSON.stringify(desativadas));
    } catch {
      /* sem localStorage: vale só nesta sessão */
    }
  }

  /** próxima página na direção pedida, pulando as desativadas */
  function proxima(n: number, dir: 1 | -1): number | null {
    let p = n + dir;
    while (p >= 1 && p <= paginasTotal) {
      if (!puladas.has(p)) return p;
      p += dir;
    }
    return null;
  }

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
      carregaDesativadas();
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
      await atualizarControle();
    } catch (e) {
      erro = String(e);
    }
  }

  async function atualizarControle() {
    try {
      controle = await invoke<Controle>("controle_estado");
    } catch {
      /* o estado é informativo; não vale derrubar a tela por isso */
    }
  }

  async function assumir() {
    erro = "";
    assumindo = true;
    try {
      controle = await invoke<Controle>("conectar", { paginas: paginasTotal || null });
      await atualizar();
    } catch (e) {
      erro = String(e);
      await atualizarControle();
    } finally {
      assumindo = false;
    }
  }

  async function devolver() {
    erro = "";
    try {
      controle = await invoke<Controle>("devolver_ao_app");
      await atualizar();
    } catch (e) {
      erro = String(e);
    }
  }

  async function buscarClima() {
    if (!cidade.trim()) return;
    buscandoClima = true;
    erro = "";
    try {
      clima = await invoke<Clima>("definir_cidade", { cidade });
      cidade = clima.cidade;
    } catch (e) {
      erro = String(e);
    } finally {
      buscandoClima = false;
    }
  }

  async function carregarClima() {
    try {
      const c = await invoke<Clima | null>("clima_configurado");
      if (c) {
        clima = c;
        cidade = c.cidade;
      }
    } catch {
      /* sem rede ou cidade nunca configurada: a seção fica vazia */
    }
  }

  async function irPara(n: number) {
    if (n < 1 || (paginasTotal > 0 && n > paginasTotal)) return;
    erro = "";
    try {
      await invoke("pagina", { n });
      paginaAtual = n;
    } catch (e) {
      erro = String(e);
      await atualizarControle();
    }
  }

  function mudarBrilho(v: number) {
    brilhoAtual = v;
    clearTimeout(brilhoTimer);
    brilhoTimer = setTimeout(async () => {
      try {
        await invoke("brilho", { n: v });
      } catch (e) {
        erro = String(e);
      }
    }, 150);
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
        paginaAtual = gerado.paginas[0];
        gravado += ` · exibindo a página ${gerado.paginas[0]}`;
      }
      await atualizarControle();
      await atualizar();
    } catch (e) {
      erro = String(e);
    } finally {
      gravando = false;
    }
  }

  async function carregar() {
    await atualizar();
    await atualizarControle();
    carregarClima();
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

  // a tecla "mini tela" do notebook troca de página no backend: ele precisa saber
  // quais páginas a interface desativou
  $effect(() => {
    invoke("desativadas", { paginas: desativadas }).catch(() => {});
  });

  // as tags são mandadas pelo backend a cada 15 s enquanto o app está no controle;
  // aqui só lemos a última linha para mostrar o que foi para a tela
  $effect(() => {
    let timer: ReturnType<typeof setInterval> | undefined;
    if (!controle.conectado) {
      estadoTags = null;
      return;
    }
    const ler = async () => {
      try {
        estadoTags = await invoke<string | null>("tags_estado");
      } catch {
        /* informativo */
      }
    };
    ler();
    timer = setInterval(ler, 5000);
    return () => clearInterval(timer);
  });
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
        <span>
          {diag.paginas_visiveis} páginas{diag.paginas !== diag.paginas_visiveis
            ? ` (${diag.paginas} no arquivo)`
            : ""}
        </span>
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
      <h2>Controle da tela</h2>
      <div class="acoes">
        {#if controle.conectado}
          <button onclick={devolver}>devolver ao app oficial</button>
        {:else}
          {#if controle.app_oficial}
            <button onclick={pararApp}>só parar o app oficial</button>
          {/if}
          <button onclick={assumir} disabled={assumindo}>
            {assumindo ? "assumindo…" : "assumir o controle"}
          </button>
        {/if}
      </div>
    </div>

    <div class="controle-linha">
      <span class="ponto" class:ligado={controle.conectado} aria-hidden="true"></span>
      <span class="estado">
        {controle.conectado ? "no controle" : "sem conexão"}
      </span>
      <span class="caminho">
        {controle.conectado
          ? controle.porta
          : controle.app_oficial
            ? "o app oficial segura a porta"
            : "a serial fica livre"}
      </span>
    </div>

    {#if !controle.conectado}
      <p class="dica">
        assumir o controle para o app oficial (se estiver aberto) e mantém a serial com este
        app — é o que permite trocar a página, o brilho e gravar.
      </p>
    {:else}
      <div class="paginas">
        <button
          onclick={() => {
            const p = proxima(paginaAtual, -1);
            if (p) irPara(p);
          }}
          disabled={!podeVoltar}>◀</button
        >
        <span>
          página {paginaAtual}{paginasTotal > 0 ? ` de ${paginasTotal}` : ""}
          {#if paginaAtual >= 5 && paginaAtual <= 7}
            <small>· slot {paginaAtual - 4}</small>
          {/if}
        </span>
        <button
          onclick={() => {
            const p = proxima(paginaAtual, 1);
            if (p) irPara(p);
          }}
          disabled={!podeAvancar}>▶</button
        >
        <select
          value={paginaAtual}
          onchange={(e) => irPara(Number(e.currentTarget.value))}
          title="ir direto para uma página"
        >
          {#each Array.from({ length: paginasTotal }, (_, i) => i + 1) as n (n)}
            {@const slot = slots.find((s) => s.pagina === n)}
            <option value={n} disabled={puladas.has(n)}>
              página {n}{slot ? ` · slot ${slot.indice + 1}` : ""}{puladas.has(n)
                ? " (desativada)"
                : ""}
            </option>
          {/each}
        </select>
      </div>

      <p class="dica">
        tema na tela: <strong>{controle.tema}</strong> · relógio, bateria e wifi:
        {estadoTags ?? "atualizando…"}
      </p>

      <div class="clima">
        <input
          type="text"
          placeholder="cidade do clima"
          bind:value={cidade}
          onkeydown={(e) => e.key === "Enter" && buscarClima()}
        />
        <button onclick={buscarClima} disabled={buscandoClima || !cidade.trim()}>
          {buscandoClima ? "buscando…" : "buscar clima"}
        </button>
        {#if clima}
          {#each clima.dias as d, i}
            <span class="dia">
              <small>{i === 0 ? "hoje" : d.rotulo}</small>
              {d.faixa}
            </span>
          {/each}
        {:else}
          <span class="dica">sem cidade configurada</span>
        {/if}
      </div>

      <label class="brilho">
        <span class="rotulo">brilho</span>
        <input
          type="range"
          min="0"
          max="100"
          value={brilhoAtual}
          oninput={(e) => mudarBrilho(Number(e.currentTarget.value))}
        />
        <code>{brilhoAtual}%</code>
      </label>
      {#if parou}<p class="dica">{parou}</p>{/if}
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
          {@const pulada = puladas.has(s.pagina)}
          <figure class="slot" class:ativo={s.indice === ativo} class:pulada>
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
              {#if pulada}<span class="selo">desativada</span>{/if}
            </button>
            <figcaption>
              <span class="nome">slot {s.indice + 1}</span>
              <small>{s.w}×{s.h}</small>
              <button
                class="pular"
                onclick={() => alternarDesativada(s.pagina)}
                title={pulada
                  ? "voltar a mostrar esta página na navegação"
                  : "pular esta página na navegação do app"}
              >
                {pulada ? "ativar" : "desativar"}
              </button>
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
      <button onclick={gravarNaTela} disabled={!gerado || gravando}>
        {gravando ? "gravando…" : "gravar na tela"}
      </button>
    </div>
    {#if !gerado}
      <p class="dica">gere o .acf acima para habilitar a gravação</p>
    {/if}
    {#if !controle.conectado}
      <p class="dica">a gravação assume o controle da tela automaticamente</p>
    {/if}
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

  .slot.pulada .painel img,
  .slot.pulada .painel .vazio {
    opacity: 0.35;
    filter: grayscale(0.7);
  }

  .selo {
    position: absolute;
    inset: auto 6px 6px 6px;
    text-align: center;
    font-size: 10.5px;
    color: #ff7b72;
    background: rgba(14, 17, 22, 0.8);
    border-radius: 5px;
    padding: 1px 4px;
  }

  .slot .painel {
    position: relative;
  }

  .pular {
    padding: 0 6px;
    font-size: 10.5px;
    line-height: 1.5;
    color: #8b94a3;
  }

  .pular:hover:not(:disabled) {
    color: #ff7b72;
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

  .controle-linha {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 13px;
  }

  .controle-linha .ponto {
    background: #6b7482;
    flex: none;
  }

  .controle-linha .ponto.ligado {
    background: #3ddc84;
  }

  .estado {
    color: #cdd4e0;
  }

  .paginas {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    font-size: 12.5px;
    color: #b9c2d0;
  }

  /* sem appearance: none o WebKitGTK desenha o select com o tema do GTK
     (fundo claro) e o texto claro do app some */
  .paginas select {
    appearance: none;
    -webkit-appearance: none;
    background-color: #1d2430;
    background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6'><path d='M0 0l5 6 5-6z' fill='%23cfd6e2'/></svg>");
    background-repeat: no-repeat;
    background-position: right 8px center;
    color: #cfd6e2;
    color-scheme: dark;
    border: 1px solid #2b3442;
    border-radius: 7px;
    padding: 4px 24px 4px 8px;
    font-size: 12px;
  }

  .paginas small {
    color: #6b7482;
  }

  .clima {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    font-size: 12.5px;
  }

  .clima input {
    background: #121722;
    border: 1px solid #2b3442;
    border-radius: 7px;
    color: #e6e9ef;
    padding: 5px 8px;
    font-size: 12.5px;
    width: 170px;
  }

  .clima .dia {
    color: #cdd4e0;
    border: 1px solid #1f2733;
    border-radius: 7px;
    padding: 2px 8px;
    display: inline-flex;
    gap: 6px;
    align-items: baseline;
  }

  .clima .dia small {
    color: #6b7482;
    text-transform: lowercase;
  }

  .brilho {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 12.5px;
  }

  .brilho .rotulo {
    color: #aab3c2;
    min-width: 96px;
  }

  .brilho input[type="range"] {
    flex: 1;
    max-width: 240px;
    accent-color: #3ddc84;
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
