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

/// Endereço absoluto do bit `n` **do bloco**: `block_base(i)` aponta o bit 1, então
/// o bit 0 (flag de partição) fica em `base - 1`.
fn bit_do_bloco(base: usize, n: usize) -> usize {
    base - 1 + n
}

/// Lê `n` bits (até 128) a partir do bit `base`.
fn rd128(buf: &[u8], base: usize, n: usize) -> u128 {
    let mut v = 0u128;
    for k in 0..n {
        let b = base + k;
        let bit = (buf[b >> 3] >> (b & 7)) & 1;
        v |= (bit as u128) << k;
    }
    v
}

/// Expande o peso de 2 bits do formato para a escala de 4 bits do interpolador.
fn peso16(w: u8) -> u8 {
    match w & 3 {
        0 => 0,
        1 => 4,
        2 => 11,
        _ => 15,
    }
}

fn hash52(mut p: u32) -> u32 {
    p ^= p >> 15;
    p = p.wrapping_sub(p << 17);
    p = p.wrapping_add(p << 7);
    p = p.wrapping_add(p << 4);
    p ^= p >> 5;
    p = p.wrapping_add(p << 16);
    p ^= p >> 7;
    p ^= p >> 3;
    p ^= p << 6;
    p ^= p >> 17;
    p
}

/// `select_partition()` de `hash52.cpp:146`: decide de qual partição o pixel é.
fn particao(seed: i32, x: i32, y: i32, z: i32, n_part: i32, bloco_pequeno: bool) -> i32 {
    let (mut x, mut y, mut z) = (x, y, z);
    if bloco_pequeno {
        x <<= 1;
        y <<= 1;
        z <<= 1;
    }
    let seed = seed + (n_part - 1) * 1024;
    let rnum = hash52(seed as u32);
    let campo = |sh: u32| ((rnum >> sh) & 0xF) as i32;
    let mut s = [
        campo(0),
        campo(4),
        campo(8),
        campo(12),
        campo(16),
        campo(20),
        campo(24),
        campo(28),
        campo(18),
        campo(22),
        campo(26),
        ((rnum.rotate_left(2)) & 0xF) as i32,
    ];
    for v in s.iter_mut() {
        *v *= *v;
    }
    let (sh1, sh2) = if seed & 1 != 0 {
        (
            if seed & 2 != 0 { 4 } else { 5 },
            if n_part == 3 { 6 } else { 5 },
        )
    } else {
        (
            if n_part == 3 { 6 } else { 5 },
            if seed & 2 != 0 { 4 } else { 5 },
        )
    };
    let sh3 = if seed & 0x10 != 0 { sh1 } else { sh2 };
    for (v, h) in s
        .iter_mut()
        .zip([sh1, sh2, sh1, sh2, sh1, sh2, sh1, sh2, sh3, sh3, sh3, sh3])
    {
        *v >>= h;
    }
    let mut a = s[0] * x + s[1] * y + s[10] * z + ((rnum >> 14) as i32);
    let mut b = s[2] * x + s[3] * y + s[11] * z + ((rnum >> 10) as i32);
    let mut c = s[4] * x + s[5] * y + s[8] * z + ((rnum >> 6) as i32);
    let mut d = s[6] * x + s[7] * y + s[9] * z + ((rnum >> 2) as i32);
    a &= 0x3F;
    b &= 0x3F;
    c &= 0x3F;
    d &= 0x3F;
    if n_part < 4 {
        d = 0;
    }
    if n_part < 3 {
        c = 0;
    }
    if a >= b && a >= c && a >= d {
        0
    } else if b >= c && b >= d {
        1
    } else if c >= d {
        2
    } else {
        3
    }
}

fn interp4(a: [u8; 4], b: [u8; 4], w: u8) -> [u8; 4] {
    let mut o = [0u8; 4];
    for c in 0..4 {
        o[c] = interp(a[c], b[c], w);
    }
    o
}

/// Modo `0` — uma partição (`stc_rgba_one_partition_dec`, `stc.cpp:629`).
fn decode_uma_particao(buf: &[u8], base: usize) -> [[u8; 4]; BLOCK_PX] {
    let mut e0 = [0u8; 4];
    let mut e1 = [0u8; 4];
    for c in 0..4 {
        e0[c] = rd(buf, base + c * 16, 8) as u8;
        e1[c] = rd(buf, base + c * 16 + 8, 8) as u8;
    }
    let mut px = [[0u8; 4]; BLOCK_PX];
    for (p, item) in px.iter_mut().enumerate() {
        let w = rd(buf, base + 64 + 4 * p, 4) as u8;
        *item = interp4(e0, e1, w);
    }
    px
}

/// Modo `01` — duas partições (`stc_rgba_two_partition_dec`, `stc.cpp:64`).
fn decode_duas_particoes(buf: &[u8], base: usize) -> [[u8; 4]; BLOCK_PX] {
    let seed = (rd128(buf, bit_do_bloco(base, 86), 10) % 1024) as i32;
    let cor = |v: u128| {
        let v = v as u8;
        v * 4 + v / 16
    };
    let alfa = |v: u128| {
        let v = v as u8;
        v * 32 + v * 4 + v / 2
    };
    // partição 0: primeiro e segundo extremos
    let p0a = [
        cor(rd128(buf, bit_do_bloco(base, 2), 6)),
        cor(rd128(buf, bit_do_bloco(base, 14), 6)),
        cor(rd128(buf, bit_do_bloco(base, 26), 6)),
        alfa(rd128(buf, bit_do_bloco(base, 38), 3)),
    ];
    let p0b = [
        cor(rd128(buf, bit_do_bloco(base, 8), 6)),
        cor(rd128(buf, bit_do_bloco(base, 20), 6)),
        cor(rd128(buf, bit_do_bloco(base, 32), 6)),
        alfa(rd128(buf, bit_do_bloco(base, 41), 3)),
    ];
    // partição 1
    let p1a = [
        cor(rd128(buf, bit_do_bloco(base, 44), 6)),
        cor(rd128(buf, bit_do_bloco(base, 56), 6)),
        cor(rd128(buf, bit_do_bloco(base, 68), 6)),
        alfa(rd128(buf, bit_do_bloco(base, 80), 3)),
    ];
    let p1b = [
        cor(rd128(buf, bit_do_bloco(base, 50), 6)),
        cor(rd128(buf, bit_do_bloco(base, 62), 6)),
        cor(rd128(buf, bit_do_bloco(base, 74), 6)),
        alfa(rd128(buf, bit_do_bloco(base, 83), 3)),
    ];

    let mut px = [[0u8; 4]; BLOCK_PX];
    for (i, item) in px.iter_mut().enumerate() {
        let (x, y) = ((i % 4) as i32, (i / 4) as i32);
        let w = peso16(rd128(buf, bit_do_bloco(base, 96 + 2 * i), 2) as u8);
        let (a, b) = if particao(seed, x, y, 0, 2, true) == 0 {
            (p0a, p0b)
        } else {
            (p1a, p1b)
        };
        *item = interp4(a, b, w);
    }
    px
}

/// Modo `0111` — uma partição, dois planos
/// (`stc_rgba_one_partition_two_plane_dec`, `stc.cpp:660`).
fn decode_uma_particao_dois_planos(buf: &[u8], base: usize) -> [[u8; 4]; BLOCK_PX] {
    let mut c0 = [0u8; 4];
    let mut c1 = [0u8; 4];
    for (canal, desloca) in [(0usize, 6usize), (1, 22), (2, 38)] {
        c0[canal] = rd128(buf, bit_do_bloco(base, desloca), 8) as u8;
        c1[canal] = rd128(buf, bit_do_bloco(base, desloca + 8), 8) as u8;
    }
    let a0 = (rd128(buf, bit_do_bloco(base, 54), 6) as u32) * 4;
    let a1 = (rd128(buf, bit_do_bloco(base, 60), 6) as u32) * 4;
    c0[3] = (a0 + a0 / 64) as u8;
    c1[3] = (a1 + a1 / 64) as u8;
    let tipo = rd128(buf, bit_do_bloco(base, 4), 2) as u8;

    let mut px = [[0u8; 4]; BLOCK_PX];
    for (i, item) in px.iter_mut().enumerate() {
        let mut w = rd128(buf, bit_do_bloco(base, 66 + 4 * i), 4) as u8;
        if i == BLOCK_PX - 1 {
            w = w / 2 * 4 + (w % 2);
        }
        let w0 = peso16(w % 4);
        let w1 = peso16(w / 4);
        let pesos = [
            if tipo == 3 { w0 } else { w1 },
            if tipo == 2 { w0 } else { w1 },
            if tipo == 1 { w0 } else { w1 },
            if tipo == 0 { w0 } else { w1 },
        ];
        for c in 0..4 {
            item[c] = interp(c0[c], c1[c], pesos[c]);
        }
    }
    px
}

/// Decodifica um bloco escolhendo o sub-formato pelos bits baixos
/// (`stc_rgba_dec`, `stc.cpp:706`).
pub fn decode_block_at(buf: &[u8], base: usize) -> [[u8; 4]; BLOCK_PX] {
    let modo = rd128(buf, bit_do_bloco(base, 0), 4) as u8;
    if modo & 1 == 0 {
        decode_uma_particao(buf, base)
    } else if modo & 3 == 1 {
        decode_duas_particoes(buf, base)
    } else if modo & 7 == 3 {
        // duas partições / dois planos: ainda não portado
        decode_uma_particao(buf, base)
    } else if modo & 0xf == 7 {
        decode_uma_particao_dois_planos(buf, base)
    } else {
        // três partições: ainda não portado
        decode_uma_particao(buf, base)
    }
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

    /// Fixtures geradas pelo `stc.cpp` do fabricante (`tests/gerar_fixtures_stc.py`).
    /// É o teste que vale: o decodificador do SDK é o oráculo.
    #[test]
    fn decodificador_bate_com_o_simulador_do_sdk() {
        let caminho = concat!(env!("CARGO_MANIFEST_DIR"), "/../tests/fixtures/stc.json");
        let texto = std::fs::read_to_string(caminho).expect("ler stc.json");
        let doc: Value = serde_json::from_str(&texto).expect("stc.json invalido");
        let casos = doc["casos"].as_array().expect("casos");
        assert!(!casos.is_empty());
        let mut modos = std::collections::BTreeSet::new();
        for caso in casos {
            let modo = caso["modo"].as_str().expect("modo").to_string();
            modos.insert(modo.clone());
            let hex = caso["bloco_hex"].as_str().expect("bloco_hex");
            let bloco: Vec<u8> = (0..hex.len() / 2)
                .map(|i| u8::from_str_radix(&hex[i * 2..i * 2 + 2], 16).expect("hex"))
                .collect();
            let mut buf = bloco.clone();
            buf.push(0);
            let px = decode_block_at(&buf, block_base(0));
            for (i, esperado) in caso["pixels"]
                .as_array()
                .expect("pixels")
                .iter()
                .enumerate()
            {
                for c in 0..3 {
                    assert_eq!(
                        px[i][c] as u64,
                        esperado[c].as_u64().expect("canal"),
                        "modo {modo}, bloco {hex}, pixel {i}, canal {c}"
                    );
                }
            }
        }
        assert!(modos.len() >= 3, "esperava os tres modos, veio {modos:?}");
    }

    /// Salva a decodificacao de uma pagina em PNG para conferir no olho.
    ///   cargo test --lib -- --ignored salva_previa --nocapture
    #[test]
    #[ignore]
    fn salva_previa() {
        let caminho = "/usr/share/minitela/resources/ACF/Texture.acf";
        let dados = std::fs::read(caminho).expect("acf");
        let r = crate::acf::inspect::parse(&dados).expect("parse");
        let pg: usize = std::env::var("MINITELA_PAGINA")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(3);
        let tex = r.paginas[pg]
            .texturas
            .iter()
            .find(|t| t.w >= 100 && (t.addr as usize) < r.start as usize)
            .expect("textura grande");
        let (w, h) = (tex.w as usize, tex.h as usize);
        let rgb = decode_image(&dados[tex.addr as usize..][..tex.slice as usize], w, h);
        let saida = format!("/tmp/opencode/previa-pagina{pg}.png");
        let mut bytes = Vec::new();
        {
            let mut enc = png::Encoder::new(&mut bytes, w as u32, h as u32);
            enc.set_color(png::ColorType::Rgb);
            enc.set_depth(png::BitDepth::Eight);
            enc.write_header()
                .expect("header")
                .write_image_data(&rgb)
                .expect("pixels");
        }
        std::fs::write(&saida, bytes).expect("gravar");
        eprintln!("{saida} ({w}x{h})");
    }

    #[test]
    fn bloco_comeca_em_modo_zero() {
        let rgb = vec![0u8; 4 * 4 * 3];
        let tex = encode_image(&rgb, 4, 4);
        // o bit de modo do bloco 0 fica no bit 0 do arquivo
        assert_eq!(tex[0] & 1, 0, "primeiro bloco deve ser uma particao");
    }
}
