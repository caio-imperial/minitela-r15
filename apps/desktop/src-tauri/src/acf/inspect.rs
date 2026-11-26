//! Leitura e validação do `.acf` com o mapa do firmware — porte de `acf_inspect.py`.
//!
//! O que o firmware valida (e o que este módulo confere):
//! 1. `StartOfConfigdata % 16384 == 0`
//! 2. `MagicNumber == 0x494d4841` em `ConfigInfo+32`
//! 3. `AHMIInfo.Version == 0x5a010a13` em `ConfigInfo+260`
//! 4. `CheckCode` de cada página == `0xA55A5AA5 ^ XOR(words do bloco)`

use std::fmt;

pub const MAGIC: u32 = 0x494D_4841;
pub const VERSION: u32 = 0x5A01_0A13;
pub const SEED: u32 = 0xA55A_5AA5;
pub const CONFIG_INFO: usize = 284;
pub const PAGE_CFG: usize = 56;
pub const TEXTURE: usize = 48;
pub const ALIGN: usize = 0x4000;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Erro {
    Curto(usize),
    Fora(&'static str),
}

impl fmt::Display for Erro {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Erro::Curto(n) => write!(f, "arquivo curto demais: {n} bytes"),
            Erro::Fora(campo) => write!(f, "campo {campo} aponta para fora do arquivo"),
        }
    }
}

fn u16le(b: &[u8], o: usize) -> Result<u16, Erro> {
    b.get(o..o + 2)
        .map(|s| u16::from_le_bytes([s[0], s[1]]))
        .ok_or(Erro::Curto(b.len()))
}

fn u32le(b: &[u8], o: usize) -> Result<u32, Erro> {
    b.get(o..o + 4)
        .map(|s| u32::from_le_bytes([s[0], s[1], s[2], s[3]]))
        .ok_or(Erro::Curto(b.len()))
}

pub fn xor_words(b: &[u8]) -> u32 {
    let (words, _) = b.as_chunks::<4>();
    words.iter().fold(0u32, |acc, c| {
        acc ^ u32::from_le_bytes([c[0], c[1], c[2], c[3]])
    })
}

pub fn checkcode(bloco: &[u8]) -> u32 {
    SEED ^ xor_words(bloco)
}

pub fn slice_esperado(w: u16, h: u16) -> u32 {
    w.div_ceil(4) as u32 * h.div_ceil(4) as u32 * 16
}

pub fn tipo_de_attr(attr: u32) -> u8 {
    (((attr >> 4) & 0xF) << 4) as u8
}

#[derive(Debug, Clone, Default)]
pub struct Textura {
    /// offset absoluto do registro no arquivo (para reescrever campos)
    pub off: usize,
    pub slice: u32,
    pub addr: u32,
    pub flags: u32,
    pub attr: u32,
    pub w: u16,
    pub h: u16,
}

impl Textura {
    pub fn tipo(&self) -> u8 {
        tipo_de_attr(self.attr)
    }
    pub fn esperado(&self) -> u32 {
        slice_esperado(self.w, self.h)
    }
}

#[derive(Debug, Clone, Default)]
pub struct Pagina {
    pub store: u32,
    pub size: u32,
    pub check: u32,
    pub ok: bool,
    pub ntex: u16,
    /// quantos widgets a página tem (0 = página vazia, fora da lista do aparelho)
    pub widgets: u16,
    pub gif: u16,
    pub texturas: Vec<Textura>,
    pub coerentes: usize,
}

#[derive(Debug, Clone, Default)]
pub struct Resumo {
    pub tamanho: usize,
    pub start: u32,
    pub total: u32,
    pub total_tex: u32,
    pub versao: u32,
    pub w: u16,
    pub h: u16,
    pub npages: u16,
    pub paginas: Vec<Pagina>,
    pub problemas: Vec<String>,
}

impl Resumo {
    /// Páginas que o aparelho de fato mostra (as vazias, sem widget e com uma
    /// textura só, ficam de fora — no tema de fábrica são 7 de 11).
    pub fn paginas_visiveis(&self) -> usize {
        self.paginas
            .iter()
            .filter(|p| p.widgets > 0 || p.texturas.len() > 1)
            .count()
    }
}

#[derive(Debug, Clone)]
pub struct Achado {
    pub nivel: u8, // 0 ok, 1 aviso, 2 erro
    pub mensagem: String,
    pub dica: String,
}

fn coerentes(data: &[u8], base: usize, ntex: usize) -> usize {
    let mut bons = 0;
    for t in 0..ntex {
        let p = base + t * TEXTURE;
        let (Ok(w), Ok(h), Ok(slice), Ok(addr), Ok(attr)) = (
            u16le(data, p + 16),
            u16le(data, p + 18),
            u32le(data, p),
            u32le(data, p + 4),
            u32le(data, p + 12),
        ) else {
            continue;
        };
        let w32 = w as u32;
        let h32 = h as u32;
        if !(1..=1024).contains(&w32) || !(1..=1024).contains(&h32) {
            continue;
        }
        let tipo = tipo_de_attr(attr);
        let esperado = slice_esperado(w, h);
        let ok = match tipo {
            0x30 => slice == 0,
            0x80 => true,
            0x00 | 0x10 => slice == esperado && (addr as usize) < data.len(),
            _ => true,
        };
        if ok {
            bons += 1;
        }
    }
    bons
}

fn acha_tabela(data: &[u8], bloco: usize, size: usize, ntex: usize) -> (Option<usize>, usize) {
    if ntex == 0 {
        return (None, 0);
    }
    let inicio = size.saturating_sub(ntex * TEXTURE);
    let mut melhor = (None, 0usize);
    let mut off = inicio as i64;
    while off >= 0 {
        let n = coerentes(data, bloco + off as usize, ntex);
        if n > melhor.1 {
            melhor = (Some(off as usize), n);
            if n == ntex {
                break;
            }
        }
        off -= 4;
    }
    melhor
}

pub fn parse(data: &[u8]) -> Result<Resumo, Erro> {
    if data.len() < ALIGN {
        return Err(Erro::Curto(data.len()));
    }
    let start = u32le(data, 0)?;
    if start as usize >= data.len() {
        return Err(Erro::Fora("StartOfConfigdata"));
    }
    let cfg = &data[start as usize..];

    let magic = u32le(cfg, 32)?;
    let total = u32le(cfg, 36)?;
    let total_tex = u32le(cfg, 40)?;
    let cfgstr = u16le(cfg, 72)?;
    let npages = u16le(cfg, 74)?;
    let versao = u32le(cfg, 260)?;
    let w = u16le(cfg, 264)?;
    let h = u16le(cfg, 266)?;

    let mut problemas = Vec::new();
    if start % ALIGN as u32 != 0 {
        problemas.push(format!(
            "StartOfConfigdata {start:#x} nao e multiplo de 16 KB"
        ));
    }
    if magic != MAGIC {
        problemas.push(format!("magic {magic:#x} != {MAGIC:#x}"));
    }
    if total as usize != data.len() - 8 {
        problemas.push(format!(
            "TotalSize {total} != tamanho-8 ({})",
            data.len() - 8
        ));
    }
    if versao != VERSION {
        problemas.push(format!(
            "AHMIInfo.Version {versao:#010x} != {VERSION:#010x}"
        ));
    }

    let base = CONFIG_INFO + cfgstr as usize;
    let mut paginas = Vec::with_capacity(npages as usize);
    for i in 0..npages as usize {
        let o = base + i * PAGE_CFG;
        let Ok(store) = u32le(cfg, o) else { break };
        let Ok(size) = u32le(cfg, o + 4) else { break };
        let Ok(check) = u32le(cfg, o + 8) else { break };
        let ntex = u16le(cfg, o + 14).unwrap_or(0);
        let widgets = u16le(cfg, o + 22).unwrap_or(0);
        let gif = u16le(cfg, o + 26).unwrap_or(0);

        let ini = start as usize + store as usize;
        let fim = ini.saturating_add(size as usize);
        let bloco = data.get(ini..fim).unwrap_or(&[]);
        let calc = if bloco.len() == size as usize {
            Some(checkcode(bloco))
        } else {
            None
        };
        let ok = calc == Some(check);
        if !ok {
            problemas.push(format!(
                "pagina {i}: CheckCode {check:#010x} != {}",
                calc.map(|c| format!("{c:#010x}"))
                    .unwrap_or_else(|| "bloco fora do arquivo".into())
            ));
        }

        let (off, bons) = acha_tabela(data, ini, size as usize, ntex as usize);
        let mut texturas = Vec::new();
        if let Some(off) = off {
            for t in 0..ntex as usize {
                let p = ini + off + t * TEXTURE;
                texturas.push(Textura {
                    off: p,
                    slice: u32le(data, p).unwrap_or(0),
                    addr: u32le(data, p + 4).unwrap_or(0),
                    flags: u32le(data, p + 8).unwrap_or(0),
                    attr: u32le(data, p + 12).unwrap_or(0),
                    w: u16le(data, p + 16).unwrap_or(0),
                    h: u16le(data, p + 18).unwrap_or(0),
                });
            }
        }
        if ntex > 0 && bons < ntex as usize {
            problemas.push(format!(
                "pagina {i}: {bons}/{ntex} texturas coerentes na tabela"
            ));
        }

        paginas.push(Pagina {
            store,
            size,
            check,
            ok,
            ntex,
            widgets,
            gif,
            texturas,
            coerentes: bons,
        });
    }

    Ok(Resumo {
        tamanho: data.len(),
        start,
        total,
        total_tex,
        versao,
        w,
        h,
        npages,
        paginas,
        problemas,
    })
}

/// Explica o que quebraria o firmware, com dica de causa.
pub fn diagnostico(data: &[u8]) -> Vec<Achado> {
    let resumo = match parse(data) {
        Ok(r) => r,
        Err(e) => {
            return vec![Achado {
                nivel: 2,
                mensagem: format!("nao consegui interpretar: {e}"),
                dica: "arquivo truncado ou nao e um .acf?".into(),
            }];
        }
    };
    let mut out = Vec::new();

    if !(data.len() - 8).is_multiple_of(ALIGN) {
        out.push(Achado {
            nivel: 2,
            mensagem: format!("tamanho {} nao segue 8 + k*16384", data.len()),
            dica: "arquivo truncado ou padding nao refeito apos edicao".into(),
        });
    }
    for p in &resumo.problemas {
        let (nivel, dica) = if p.contains("CheckCode") {
            (
                2,
                "o firmware entra no laco de AHMIInterface e nao termina: recalcule o \
                 CheckCode depois de qualquer edicao no bloco",
            )
        } else if p.contains("coerentes") {
            (
                1,
                "tabela de texturas fora do lugar (edicao sem ajustar offsets?)",
            )
        } else {
            (2, "header/config inconsistentes")
        };
        out.push(Achado {
            nivel,
            mensagem: p.clone(),
            dica: dica.into(),
        });
    }
    if out.is_empty() {
        out.push(Achado {
            nivel: 0,
            mensagem: "todas as invariantes que o firmware checa estao OK".into(),
            dica: String::new(),
        });
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn xor_e_checkcode() {
        assert_eq!(xor_words(&[0u8; 8]), 0);
        let b = [1u8, 0, 0, 0, 0, 0, 0, 0];
        assert_eq!(xor_words(&b), 1);
        assert_eq!(checkcode(&b), SEED ^ 1);
        assert_eq!(checkcode(&[0u8; 16]), SEED);
    }

    #[test]
    fn formula_da_fatia() {
        assert_eq!(slice_esperado(240, 240), 57600);
        assert_eq!(slice_esperado(192, 192), 36864);
        assert_eq!(slice_esperado(104, 26), 2912);
        assert_eq!(slice_esperado(4, 4), 16);
    }

    #[test]
    fn tipo_de_attr_usa_bits_7_a_4() {
        assert_eq!(tipo_de_attr(0x110), 0x10);
        assert_eq!(tipo_de_attr(0x130), 0x30);
        assert_eq!(tipo_de_attr(0x100), 0x00);
    }

    #[test]
    fn magic_do_config() {
        assert_eq!(MAGIC, 0x494d4841);
        assert_eq!(VERSION, 0x5a010a13);
    }

    /// Bate num `.acf` real quando `MINITELA_ACF` aponta para um.
    /// Rode com: MINITELA_ACF=/caminho/Texture.acf cargo test -- --ignored
    #[test]
    #[ignore]
    fn arquivo_real() {
        let caminho = std::env::var("MINITELA_ACF").expect("defina MINITELA_ACF");
        let dados = std::fs::read(&caminho).expect("ler");
        let resumo = parse(&dados).expect("parse");
        assert!(resumo.problemas.is_empty(), "{:?}", resumo.problemas);
        assert_eq!(resumo.w, 240);
        assert_eq!(resumo.h, 240);
        assert!(resumo.paginas.iter().all(|p| p.ok));
    }
}
