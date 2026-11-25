<script lang="ts">
  import type { Enquadramento } from "./tipos";

  let {
    fonte,
    alvo,
    estado,
    onmudar,
  }: {
    fonte: string;
    alvo: [number, number];
    estado: Enquadramento;
    onmudar: (novo: Enquadramento) => void;
  } = $props();

  let arrastando = $state(false);
  let ultimo = { x: 0, y: 0 };

  const limita = (v: number) => Math.min(1, Math.max(0, v));

  // Arrastar dobra o recorte: uma largura do quadro percorre toda a faixa.
  // O CSS usa object-position/transform-origin — a mesma geometria que o ffmpeg
  // aplica na hora de gerar (escala para cobrir, recorta em w×h).
  function pega(e: PointerEvent) {
    if (estado.ajuste !== "cobrir") return;
    arrastando = true;
    ultimo = { x: e.clientX, y: e.clientY };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }

  function move(e: PointerEvent) {
    if (!arrastando) return;
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const dx = (e.clientX - ultimo.x) / (r.width || 1);
    const dy = (e.clientY - ultimo.y) / (r.height || 1);
    ultimo = { x: e.clientX, y: e.clientY };
    onmudar({
      ...estado,
      px: limita(estado.px - dx),
      py: limita(estado.py - dy),
    });
  }

  function solta(e: PointerEvent) {
    if (!arrastando) return;
    arrastando = false;
    (e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId);
  }

  const cobrir = $derived(estado.ajuste === "cobrir");
  const origem = $derived(`${estado.px * 100}% ${estado.py * 100}%`);
</script>

<div class="editor">
  <div
    class="moldura"
    class:arrastando
    role="img"
    aria-label="recorte da imagem"
    onpointerdown={pega}
    onpointermove={move}
    onpointerup={solta}
    onpointercancel={solta}
  >
    <img
      src={fonte}
      alt=""
      draggable="false"
      style:object-fit={cobrir ? "cover" : "contain"}
      style:object-position={origem}
      style:transform={cobrir ? `scale(${estado.zoom})` : "none"}
      style:transform-origin={origem}
    />
    <span class="alvo">{alvo[0]}×{alvo[1]}</span>
  </div>

  <div class="controles">
    <div class="linha">
      <span class="rotulo">enquadramento</span>
      <div class="seg">
        <button
          class:on={cobrir}
          onclick={() => onmudar({ ...estado, ajuste: "cobrir" })}>cobrir</button
        >
        <button
          class:on={!cobrir}
          onclick={() => onmudar({ ...estado, ajuste: "conter" })}>conter</button
        >
      </div>
    </div>

    <label class="linha">
      <span class="rotulo">zoom</span>
      <input
        type="range"
        min="1"
        max="3"
        step="0.05"
        value={estado.zoom}
        disabled={!cobrir}
        oninput={(e) => onmudar({ ...estado, zoom: Number(e.currentTarget.value) })}
      />
      <code>{estado.zoom.toFixed(2)}×</code>
    </label>

    <div class="linha">
      <span class="dica">
        {cobrir
          ? "arraste sobre a imagem para escolher o recorte"
          : "a imagem inteira, com barras pretas"}
      </span>
      <button
        class="reset"
        onclick={() => onmudar({ ajuste: estado.ajuste, zoom: 1, px: 0.5, py: 0.5 })}
        disabled={cobrir && estado.zoom === 1 && estado.px === 0.5 && estado.py === 0.5}
      >
        centralizar
      </button>
    </div>
  </div>
</div>

<style>
  .editor {
    display: grid;
    grid-template-columns: 200px 1fr;
    gap: 14px;
    align-items: start;
  }

  .moldura {
    position: relative;
    width: 200px;
    aspect-ratio: 1;
    overflow: hidden;
    border-radius: 10px;
    border: 1px solid #2b3442;
    background: #000;
    cursor: grab;
    touch-action: none;
  }

  .moldura.arrastando {
    cursor: grabbing;
  }

  .moldura img {
    width: 100%;
    height: 100%;
    display: block;
    user-select: none;
  }

  .alvo {
    position: absolute;
    right: 6px;
    bottom: 6px;
    font-family: ui-monospace, monospace;
    font-size: 10.5px;
    color: #cfd6e2;
    background: rgba(14, 17, 22, 0.72);
    border-radius: 5px;
    padding: 1px 5px;
  }

  .controles {
    display: flex;
    flex-direction: column;
    gap: 8px;
    min-width: 0;
  }

  .linha {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 12.5px;
  }

  .rotulo {
    color: #aab3c2;
    min-width: 96px;
  }

  .seg {
    display: flex;
    gap: 4px;
  }

  .seg button {
    background: #1d2430;
    color: #aab3c2;
    border: 1px solid #2b3442;
    border-radius: 7px;
    padding: 4px 10px;
    font-size: 12px;
    cursor: pointer;
  }

  .seg button.on {
    border-color: #3ddc84;
    color: #3ddc84;
  }

  input[type="range"] {
    flex: 1;
    min-width: 60px;
    accent-color: #3ddc84;
  }

  input[type="range"]:disabled {
    opacity: 0.45;
  }

  code {
    background: #1b2230;
    border-radius: 4px;
    padding: 1px 5px;
    font-size: 11.5px;
    min-width: 46px;
    text-align: center;
  }

  .dica {
    color: #8b94a3;
    font-size: 12px;
    flex: 1;
  }

  .reset {
    background: #1d2430;
    color: #cfd6e2;
    border: 1px solid #2b3442;
    border-radius: 7px;
    padding: 4px 10px;
    font-size: 12px;
    cursor: pointer;
  }

  .reset:disabled {
    opacity: 0.45;
    cursor: default;
  }
</style>
