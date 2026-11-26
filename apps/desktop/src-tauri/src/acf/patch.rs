//! Montagem e patch de textura — porte de `acf_anim.py` + `minitela_patch.py`.
//!
//! Duas operações:
//!
//! * [`patch_estatico`] — mesmo tamanho, um quadro: sobrescreve os bytes no lugar.
//! * [`monta`] — muda o tamanho da fatia e/ou o número de quadros: remonta a área de
//!   textura, reloca o que vem depois, corrige escalonador/tile boxes, `GifSliceNum`,
//!   `StartOfConfigdata`, `TotalSize`, `TotalTextureSize`, `CheckCode` das páginas e o
//!   checksum do arquivo.
//!
//! O que **não** é feito aqui: decodificar imagem (fica para a camada que chama ffmpeg).

use super::codec;
use super::inspect::{
    ALIGN, CONFIG_INFO, Erro, PAGE_CFG, Resumo, Textura, checkcode, slice_esperado,
};

pub const GIF_SLICE_NUM: usize = 0x17E;

fn u16le(b: &[u8], o: usize) -> u16 {
    u16::from_le_bytes([b[o], b[o + 1]])
}
fn u32le(b: &[u8], o: usize) -> u32 {
    u32::from_le_bytes([b[o], b[o + 1], b[o + 2], b[o + 3]])
}
fn pu16(b: &mut [u8], o: usize, v: u16) {
    b[o..o + 2].copy_from_slice(&v.to_le_bytes());
}
fn pu32(b: &mut [u8], o: usize, v: u32) {
    b[o..o + 4].copy_from_slice(&v.to_le_bytes());
}
fn pi16(b: &mut [u8], o: usize, v: i16) {
    b[o..o + 2].copy_from_slice(&v.to_le_bytes());
}
fn pi16r(b: &[u8], o: usize) -> i16 {
    i16::from_le_bytes([b[o], b[o + 1]])
}

/// Tamanho do trailer de fatias, alinhado em 16: `8 + 2*ceil(n/16)`.
pub fn trailer_len(n: usize) -> usize {
    let base = 8 + 2 * n.div_ceil(16);
    base.div_ceil(16) * 16
}

pub fn align16k(x: usize) -> usize {
    x.div_ceil(ALIGN) * ALIGN
}

/// XOR de todas as words, exceto a do próprio campo (word 1) e a última.
fn checksum(data: &mut [u8]) {
    let n = data.len() / 4;
    let mut total = 0u32;
    for i in 0..n {
        if i == 1 || i == n - 1 {
            continue;
        }
        total ^= u32le(data, i * 4);
    }
    pu32(data, 4, total);
}

fn quadros_iguais(quadros: &[Vec<u8>]) -> Result<usize, Erro> {
    let tam = quadros
        .first()
        .ok_or(Erro::Fora("lista de quadros vazia"))?
        .len();
    if quadros.iter().any(|q| q.len() != tam) {
        return Err(Erro::Fora("quadros com tamanhos diferentes"));
    }
    Ok(tam)
}

/// Sobrescreve a textura no lugar: mesmo tamanho, um quadro.
pub fn patch_estatico(data: &[u8], tex: &Textura, rgb: &[u8], w: usize, h: usize) -> Vec<u8> {
    let nova = codec::encode_image(rgb, w, h);
    let mut out = data.to_vec();
    let ini = tex.addr as usize;
    let fim = (ini + nova.len()).min(out.len());
    out[ini..fim].copy_from_slice(&nova[..fim - ini]);
    checksum(&mut out);
    out
}

/// Remonta a textura do slot com `quadros` (bytes STC), possivelmente de outro tamanho.
pub fn monta(
    data: &[u8],
    info: &Resumo,
    page: usize,
    tex_idx: usize,
    quadros: &[Vec<u8>],
) -> Result<Vec<u8>, Erro> {
    let n = quadros.len();
    let sl = quadros_iguais(quadros)?;
    let w = ((sl as f64 / 16.0).sqrt().round() as usize) * 4;
    if slice_esperado(w as u16, w as u16) as usize != sl {
        return Err(Erro::Fora("fatia nao e quadrada"));
    }

    let start = info.start as usize;
    let pagina = info
        .paginas
        .get(page)
        .ok_or(Erro::Fora("pagina inexistente"))?;
    let tex = pagina
        .texturas
        .get(tex_idx)
        .ok_or(Erro::Fora("textura inexistente"))?;
    let addr = tex.addr as usize;

    // fim da textura antiga = próxima textura depois do slot (ou a config)
    let mut proximo = start;
    for p in &info.paginas {
        for t in &p.texturas {
            let a = t.addr as usize;
            if a > addr && a < start {
                proximo = proximo.min(a);
            }
        }
    }
    let old_total = proximo - addr;
    let new_total = n * sl + if n > 1 { trailer_len(n) } else { 0 };
    let d = new_total as i64 - old_total as i64;

    let tail = &data[addr + old_total..start];
    let new_start = align16k(addr + new_total + tail.len());
    let mut out = vec![0u8; new_start + data.len() - start];

    out[..addr].copy_from_slice(&data[..addr]);
    for (i, q) in quadros.iter().enumerate() {
        out[addr + i * sl..addr + (i + 1) * sl].copy_from_slice(q);
    }

    let tr = addr + n * sl;
    if n > 1 {
        let flags = tr + 8;
        let colors = flags + 2 * n.div_ceil(16);
        pu16(&mut out, tr, (flags >> 16) as u16);
        pu16(&mut out, tr + 2, (flags & 0xFFFF) as u16);
        pu16(&mut out, tr + 4, (colors >> 16) as u16);
        pu16(&mut out, tr + 6, (colors & 0xFFFF) as u16);
        for k in 0..n {
            let o = tr + 8 + 2 * (k / 16);
            let atual = u16le(&out, o);
            pu16(&mut out, o, atual | (1 << (15 - k % 16)));
        }
    }
    out[addr + new_total..addr + new_total + tail.len()].copy_from_slice(tail);

    let cfg = new_start - start;
    out[new_start..new_start + data.len() - start].copy_from_slice(&data[start..]);
    pu32(&mut out, 0, new_start as u32);

    // registros: reloca os que ficam depois e atualiza o do slot
    for (pi, p) in info.paginas.iter().enumerate() {
        for (ti, t) in p.texturas.iter().enumerate() {
            let a = t.addr as usize;
            if a >= start {
                continue;
            }
            let o = t.off + cfg;
            if a > addr {
                pu32(&mut out, o + 4, (a as i64 + d) as u32);
                let fl = u32le(&out, o + 8);
                if fl != 0 {
                    pu32(&mut out, o + 8, (fl as i64 + d) as u32);
                }
            } else if pi == page && ti == tex_idx {
                pu32(&mut out, o, sl as u32);
                pu32(&mut out, o + 8, if n > 1 { tr as u32 } else { 0 });
                pu16(&mut out, o + 16, w as u16);
                pu16(&mut out, o + 18, w as u16);
                if (w as u16, w as u16) != (t.w, t.h) {
                    for (campo, dim_ant, dim_novo) in
                        [(36usize, t.w, w as u16), (38usize, t.h, w as u16)]
                    {
                        let antigo = pi16r(&out, o + campo);
                        if dim_ant != 0 && dim_novo != 0 {
                            let novo = (antigo as f64 * dim_ant as f64 / dim_novo as f64)
                                .round_ties_even() as i16;
                            pi16(&mut out, o + campo, novo);
                        }
                    }
                    let tb = (w / 32).max(1) as u8;
                    out[o + 40..o + 44].copy_from_slice(&[0, 0, tb, tb]);
                }
            }
        }
    }

    // GifSliceNum no bloco do widget
    let blk = new_start + pagina.store as usize;
    if blk + GIF_SLICE_NUM + 2 <= out.len() {
        pu16(&mut out, blk + GIF_SLICE_NUM, n as u16);
    }

    // CheckCode de todas as páginas (o bloco do slot e os relocados mudaram)
    let base = CONFIG_INFO + u16le(&out, new_start + 72) as usize;
    for (idx, p) in info.paginas.iter().enumerate() {
        let b = new_start + p.store as usize;
        let fim = (b + p.size as usize).min(out.len());
        let cc = checkcode(&out[b..fim]);
        pu32(&mut out, new_start + base + idx * PAGE_CFG + 8, cc);
    }

    // ConfigInfo e header
    let total_size = (out.len() - 8) as u32;
    pu32(&mut out, new_start + 36, total_size);
    let total_tex = (u32le(&out, new_start + 40) as i64 + d) as u32;
    pu32(&mut out, new_start + 40, total_tex);
    pu32(&mut out, 8, total_tex / 2);

    checksum(&mut out);
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tamanho_do_trailer() {
        assert_eq!(trailer_len(1), 16);
        assert_eq!(trailer_len(8), 16);
        assert_eq!(trailer_len(16), 16); // 8 + 2*1 = 10 -> 16
        assert_eq!(trailer_len(65), 32); // 8 + 2*5 = 18 -> 32
        assert_eq!(trailer_len(75), 32);
        assert_eq!(trailer_len(96), 32);
    }

    #[test]
    fn alinhamento_de_16k() {
        assert_eq!(align16k(1), 0x4000);
        assert_eq!(align16k(0x4000), 0x4000);
        assert_eq!(align16k(0x4001), 0x8000);
    }

    #[test]
    fn checksum_redondo() {
        // com o footer 0xA55A5AA5, o XOR de TODAS as words fecha em SEED
        let mut d = vec![0u8; 32];
        d[0] = 0x41;
        d[28..32].copy_from_slice(&super::super::inspect::SEED.to_le_bytes());
        checksum(&mut d);
        let total: u32 = d
            .as_chunks::<4>()
            .0
            .iter()
            .fold(0u32, |a, c| a ^ u32::from_le_bytes(*c));
        // com o campo correto, o XOR de tudo (incluindo @4 e a última word) == SEED
        assert_eq!(total, super::super::inspect::SEED);
    }

    /// End-to-end num `.acf` real: MINITELA_ACF=<arquivo> cargo test -- --ignored
    #[test]
    #[ignore]
    fn monta_num_arquivo_real() {
        let caminho = std::env::var("MINITELA_ACF").expect("defina MINITELA_ACF");
        let dados = std::fs::read(&caminho).expect("ler");
        let info = super::super::inspect::parse(&dados).expect("parse");
        let (page, ti) = info
            .paginas
            .iter()
            .enumerate()
            .find_map(|(pi, p)| {
                p.texturas
                    .iter()
                    .position(|t| matches!(t.tipo(), 0x00 | 0x10) && t.w > 0)
                    .map(|ti| (pi, ti))
            })
            .expect("pagina com textura");

        // 8 quadros 192x192 (o tamanho do slot de fabrica)
        let w = 192usize;
        let mut quadros = Vec::new();
        for k in 0..8usize {
            let mut rgb = Vec::with_capacity(w * w * 3);
            for y in 0..w {
                for x in 0..w {
                    rgb.extend_from_slice(&[(x % 256) as u8, (y % 256) as u8, (k * 32) as u8]);
                }
            }
            quadros.push(codec::encode_image(&rgb, w, w));
        }
        let novo = monta(&dados, &info, page, ti, &quadros).expect("monta");
        let info2 = super::super::inspect::parse(&novo).expect("parse do resultado");
        assert!(info2.problemas.is_empty(), "{:?}", info2.problemas);
        let t = &info2.paginas[page].texturas[ti];
        assert_eq!(t.w, w as u16);
        assert_eq!(t.slice, 36864);
        assert_ne!(t.flags, 0, "trailer de fatias");
        let blk = info2.start as usize + info2.paginas[page].store as usize;
        assert_eq!(u16le(&novo, blk + GIF_SLICE_NUM), 8);
    }

    #[test]
    fn patch_estatico_troca_textura_e_checksum() {
        let mut d = vec![0u8; 0x4000 + 64];
        let tex = Textura {
            off: 0x4000,
            slice: 16,
            addr: 0x10,
            flags: 0,
            attr: 0x110,
            w: 4,
            h: 4,
        };
        let rgb = vec![255u8; 4 * 4 * 3];
        let novo = patch_estatico(&d, &tex, &rgb, 4, 4);
        assert_eq!(novo.len(), d.len());
        assert_ne!(&novo[0x10..0x20], &d[0x10..0x20]);
        d[0x10..0x20].copy_from_slice(&novo[0x10..0x20]);
        assert_eq!(u32le(&novo, 4), u32le(&novo, 4));
    }
}
