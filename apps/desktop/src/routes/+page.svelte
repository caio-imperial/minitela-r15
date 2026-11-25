<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { onMount } from "svelte";

  type Item = { nome: string; estado: string; detalhe: string };

  let itens: Item[] = $state([]);
  let carregando = $state(true);
  let erro = $state("");

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
    max-width: 760px;
    margin: 0 auto;
    padding: 28px 24px 20px;
    display: flex;
    flex-direction: column;
    min-height: 100vh;
    box-sizing: border-box;
  }

  header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 22px;
  }

  h1 {
    margin: 0;
    font-size: 26px;
    letter-spacing: -0.02em;
  }

  .sub {
    margin: 4px 0 0;
    color: #8b94a3;
    font-size: 13px;
  }

  button {
    background: #1d2430;
    color: #cfd6e2;
    border: 1px solid #2b3442;
    border-radius: 8px;
    padding: 8px 14px;
    font-size: 13px;
    cursor: pointer;
  }

  button:hover:not(:disabled) {
    background: #232c3a;
  }

  button:disabled {
    opacity: 0.6;
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
    padding: 11px 14px;
    border-bottom: 1px solid #1b2230;
    font-size: 14px;
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

  .erro {
    color: #ff7b72;
    font-family: ui-monospace, monospace;
    font-size: 13px;
  }

  footer {
    margin-top: auto;
    padding-top: 18px;
    display: flex;
    justify-content: space-between;
    color: #6b7482;
    font-size: 12px;
  }
</style>
