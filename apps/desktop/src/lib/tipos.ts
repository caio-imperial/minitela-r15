/** Tipos compartilhados entre a página e os componentes. */

/** Como a imagem entra na textura (mesmos valores que o backend Rust aceita). */
export type Enquadramento = {
  ajuste: "cobrir" | "conter";
  /** 1 = sem zoom, 3 = três vezes mais perto */
  zoom: number;
  /** 0..1 — que ponto da imagem fica no quadro */
  px: number;
  py: number;
};

/** Um dos três slots de imagem do `.acf` (páginas 4/5/6). */
export type Slot = {
  indice: number;
  pagina: number;
  w: number;
  h: number;
  /** PNG do conteúdo atual, em data URL */
  previa: string;
};

/** Imagem escolhida para um slot, com o enquadramento dela. */
export type Edicao = Enquadramento & {
  /** caminho original — é o que vai para o ffmpeg */
  imagem: string;
  /** data URL reduzida, só para a interface */
  fonte: string;
  telaCheia: boolean;
};
