//! Codec STC do GC9002 — porte do `acf_codec.py`.
//!
//! Bloco de 16 bytes = 128 bits, LSB-first a partir do bit 1:
//!
//! ```text
//! bit  0        modo (0 = uma partição; os outros 4 sub-formatos ainda não)
//! bits 1-8      R0      bits  9-16  R1
//! bits 17-24    G0      bits 25-32  G1
//! bits 33-40    B0      bits 41-48  B1
//! bits 49-56    A0      bits 57-64  A1
//! bits 65-124   16 pesos de 4 bits (pixel i em 65+4i, raster no bloco 4x4)
//! bits 125-128  peso do último pixel (só 3 bits cabem)
//! ```

pub const BLOCK_BYTES: usize = 16;
pub const BLOCK_PX: usize = 16;
pub const BLOCK_BITS: usize = 128;
pub const BASE_BIT: usize = 1;

fn rd(buf: &[u8], base: usize, n: usize) -> u32 {
    let mut v = 0u32;
    for k in 0..n {
        let b = base + k;
        let bit = (buf[b >> 3] >> (b & 7)) & 1;
        v |= (bit as u32) << k;
    }
    v
}

fn wr(buf: &mut [u8], base: usize, n: usize, value: u32) {
    for k in 0..n {
        let b = base + k;
        let mask = 1u8 << (b & 7);
        if (value >> k) & 1 == 1 {
            buf[b >> 3] |= mask;
        } else {
            buf[b >> 3] &= !mask;
        }
    }
}

pub fn block_base(index: usize) -> usize {
    BASE_BIT + index * BLOCK_BITS
}

/// Interpolação do firmware (`interpolate()` em stc.cpp): `true_w = w + w/8`,
/// divisão inteira com truncamento para zero, saturada em 0..255.
pub fn interp(a0: u8, a1: u8, w: u8) -> u8 {
    let wi = w as i32;
    let true_w = wi + wi / 8;
    let num = (a1 as i32 - a0 as i32) * true_w;
    let t = if num >= 0 { num >> 4 } else { -((-num) >> 4) };
    (a0 as i32 + t).clamp(0, 255) as u8
}

pub fn decode_block_at(buf: &[u8], base: usize) -> [[u8; 4]; BLOCK_PX] {
    let mut e0 = [0u8; 4];
    let mut e1 = [0u8; 4];
    for c in 0..4 {
        e0[c] = rd(buf, base + c * 16, 8) as u8;
        e1[c] = rd(buf, base + c * 16 + 8, 8) as u8;
    }
    let mut px = [[0u8; 4]; BLOCK_PX];
    for (p, item) in px.iter_mut().enumerate() {
        let w = rd(buf, base + 64 + 4 * p, 4) as u8;
        for c in 0..4 {
            item[c] = interp(e0[c], e1[c], w);
        }
    }
    px
}

fn erro(c0: &[u8; 4], c1: &[u8; 4], pesos: &[u8; BLOCK_PX], px: &[[u8; 4]; BLOCK_PX]) -> i64 {
    let mut total = 0i64;
    for p in 0..BLOCK_PX {
        for c in 0..4 {
            let d = interp(c0[c], c1[c], pesos[p]) as i64 - px[p][c] as i64;
            total += d * d;
        }
    }
    total
}

pub fn encode_block_at(buf: &mut [u8], base: usize, px: &[[u8; 4]; BLOCK_PX]) {
    let mut amp = [0i32; 4];
    for (c, a) in amp.iter_mut().enumerate() {
        let max = px.iter().map(|p| p[c] as i32).max().unwrap_or(0);
        let min = px.iter().map(|p| p[c] as i32).min().unwrap_or(0);
        *a = max - min;
    }
    // empate no eixo dominante: Python fica com o primeiro (R, depois G, B, A)
    let mut eixo = 0usize;
    for c in 1..4 {
        if amp[c] > amp[eixo] {
            eixo = c;
        }
    }

    let (mut c0, mut c1, mut pesos);
    if amp[eixo] == 0 {
        c0 = px[0];
        c1 = px[0];
        pesos = [0u8; BLOCK_PX];
    } else {
        c0 = *px.iter().min_by_key(|q| q[eixo]).expect("bloco tem pixels");
        c1 = *px.iter().max_by_key(|q| q[eixo]).expect("bloco tem pixels");
        pesos = [0u8; BLOCK_PX];
        for (p, q) in px.iter().enumerate() {
            let mut melhor = (i64::MAX, 0u8);
            for w in 0..16u8 {
                let mut e = 0i64;
                for c in 0..4 {
                    let d = interp(c0[c], c1[c], w) as i64 - q[c] as i64;
                    e += d * d;
                }
                if e < melhor.0 {
                    melhor = (e, w);
                }
            }
            pesos[p] = melhor.1;
        }
    }

    // O último peso só cabe em 3 bits (0..7). Se passar, invertemos os endpoints —
    // é o que o compilador do ODM faz — e ficamos com a orientação de menor erro.
    let invertidos = {
        let mut inv = [0u8; BLOCK_PX];
        for (i, w) in pesos.iter().enumerate() {
            inv[i] = 15 - w;
        }
        inv
    };
    let a_valido = pesos[BLOCK_PX - 1] <= 7;
    let b_valido = invertidos[BLOCK_PX - 1] <= 7;
    if a_valido && b_valido {
        if erro(&c1, &c0, &invertidos, px) < erro(&c0, &c1, &pesos, px) {
            (c0, c1, pesos) = (c1, c0, invertidos);
        }
    } else if b_valido {
        (c0, c1, pesos) = (c1, c0, invertidos);
    }

    for c in 0..4 {
        wr(buf, base + c * 16, 8, c0[c] as u32);
        wr(buf, base + c * 16 + 8, 8, c1[c] as u32);
    }
    for (p, w) in pesos.iter().enumerate() {
        let nbits = if p < BLOCK_PX - 1 { 4 } else { 3 };
        let mascara = (1u32 << nbits) - 1;
        wr(buf, base + 64 + 4 * p, nbits, *w as u32 & mascara);
    }
}

pub fn decode_image(tex: &[u8], w: usize, h: usize) -> Vec<u8> {
    let mut buf = tex.to_vec();
    buf.push(0); // folga: o último bit do último bloco cai fora
    let bw = w / 4;
    let mut out = vec![0u8; w * h * 3];
    for bi in 0..(w / 4) * (h / 4) {
        let px = decode_block_at(&buf, block_base(bi));
        let (bx, by) = (bi % bw, bi / bw);
        for (p, cor) in px.iter().enumerate() {
            let x = bx * 4 + p % 4;
            let y = by * 4 + p / 4;
            let o = (y * w + x) * 3;
            out[o] = cor[0];
            out[o + 1] = cor[1];
            out[o + 2] = cor[2];
        }
    }
    out
}

pub fn encode_image(rgb: &[u8], w: usize, h: usize) -> Vec<u8> {
    let nblocos = (w / 4) * (h / 4);
    let mut buf = vec![0u8; nblocos * BLOCK_BYTES + 1];
    let bw = w / 4;
    for bi in 0..nblocos {
        let (bx, by) = (bi % bw, bi / bw);
        let mut px = [[0u8; 4]; BLOCK_PX];
        for (p, item) in px.iter_mut().enumerate() {
            let x = bx * 4 + p % 4;
            let y = by * 4 + p / 4;
            let o = (y * w + x) * 3;
            *item = [rgb[o], rgb[o + 1], rgb[o + 2], 255];
        }
        encode_block_at(&mut buf, block_base(bi), &px);
    }
    buf.truncate(nblocos * BLOCK_BYTES);
    buf
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    fn vetores() -> Value {
        let caminho = concat!(env!("CARGO_MANIFEST_DIR"), "/../tests/fixtures/codec.json");
        let texto = std::fs::read_to_string(caminho)
            .unwrap_or_else(|e| panic!("nao consegui ler {caminho}: {e}"));
        serde_json::from_str(&texto).expect("codec.json invalido")
    }

    #[test]
    fn vetores_dourados_batem_com_o_python() {
        let doc = vetores();
        let casos = doc["casos"].as_object().expect("casos");
        assert!(!casos.is_empty());
        for (nome, caso) in casos {
            let px_json = caso["pixels"].as_array().expect("pixels");
            assert_eq!(px_json.len(), 16, "{nome}: 16 pixels");
            let mut px = [[0u8; 4]; BLOCK_PX];
            for (i, p) in px_json.iter().enumerate() {
                for c in 0..4 {
                    px[i][c] = p[c].as_u64().expect("canal") as u8;
                }
            }
            let mut rgb = Vec::with_capacity(4 * 4 * 3);
            for p in &px {
                rgb.extend_from_slice(&p[..3]);
            }

            let bloco = encode_image(&rgb, 4, 4);
            let esperado = caso["bloco_hex"].as_str().expect("bloco_hex");
            assert_eq!(
                bloco.iter().map(|b| format!("{b:02x}")).collect::<String>(),
                esperado,
                "{nome}: bytes codificados divergem"
            );

            let mut com_folga = bloco.clone();
            com_folga.push(0);
            let volta = decode_block_at(&com_folga, block_base(0));
            let esperado_dec = caso["decodificado"].as_array().expect("decodificado");
            for (i, p) in esperado_dec.iter().enumerate() {
                for c in 0..4 {
                    assert_eq!(
                        volta[i][c],
                        p[c].as_u64().expect("canal") as u8,
                        "{nome}: pixel {i} canal {c}"
                    );
                }
            }
        }
    }

    #[test]
    fn ida_e_volta_do_gradiente() {
        let (w, h) = (8usize, 8usize);
        let mut rgb = Vec::with_capacity(w * h * 3);
        let total = (w * h - 1).max(1) as u32;
        for y in 0..h {
            for x in 0..w {
                let v = ((y * w + x) as u32 * 255 / total) as u8;
                rgb.extend_from_slice(&[v, v, v]);
            }
        }
        let tex = encode_image(&rgb, w, h);
        assert_eq!(tex.len(), (w / 4) * (h / 4) * BLOCK_BYTES);
        let volta = decode_image(&tex, w, h);
        let erro_max = rgb
            .iter()
            .zip(volta.iter())
            .map(|(a, b)| a.abs_diff(*b))
            .max()
            .unwrap_or(0);
        assert!(erro_max <= 4, "erro maximo {erro_max}");
    }

    #[test]
    fn bloco_comeca_em_modo_zero() {
        let rgb = vec![0u8; 4 * 4 * 3];
        let tex = encode_image(&rgb, 4, 4);
        // o bit de modo do bloco 0 fica no bit 0 do arquivo
        assert_eq!(tex[0] & 1, 0, "primeiro bloco deve ser uma particao");
    }
}
