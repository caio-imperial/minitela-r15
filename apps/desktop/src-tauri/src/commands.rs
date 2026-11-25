//! Comandos expostos à interface.

use crate::acf::{codec, inspect, patch};
use serde::Serialize;
use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Serialize)]
pub struct AchadoView {
    pub nivel: u8,
    pub mensagem: String,
    pub dica: String,
}

#[derive(Serialize)]
pub struct DiagnosticoView {
    pub caminho: String,
    pub tamanho: usize,
    pub start: u32,
    pub tela: [u16; 2],
    pub paginas: usize,
    pub texturas: usize,
    pub ok: bool,
    pub achados: Vec<AchadoView>,
}

fn texto(e: impl std::fmt::Display) -> String {
    e.to_string()
}

#[tauri::command]
pub fn diagnostico(caminho: String) -> Result<DiagnosticoView, String> {
    let dados = std::fs::read(&caminho).map_err(texto)?;
    let resumo = inspect::parse(&dados).map_err(texto)?;
    let achados = inspect::diagnostico(&dados)
        .into_iter()
        .map(|a| AchadoView {
            nivel: a.nivel,
            mensagem: a.mensagem,
            dica: a.dica,
        })
        .collect();
    Ok(DiagnosticoView {
        caminho,
        tamanho: resumo.tamanho,
        start: resumo.start,
        tela: [resumo.w, resumo.h],
        paginas: resumo.paginas.len(),
        texturas: resumo.paginas.iter().map(|p| p.texturas.len()).sum(),
        ok: resumo.problemas.is_empty(),
        achados,
    })
}

/// Primeira textura de imagem (páginas 4/5/6, tipo STC) com o índice da página.
fn acha_slot(resumo: &inspect::Resumo) -> Option<(usize, usize, inspect::Textura)> {
    for pi in [4usize, 5, 6] {
        let Some(p) = resumo.paginas.get(pi) else {
            continue;
        };
        for (ti, t) in p.texturas.iter().enumerate() {
            if matches!(t.tipo(), 0x00 | 0x10)
                && t.w > 0
                && (t.addr as usize) < resumo.start as usize
            {
                return Some((pi, ti, t.clone()));
            }
        }
    }
    None
}

/// Quadros RGB de uma imagem, no enquadramento do build (ffmpeg).
fn quadros_rgb(imagem: &Path, w: usize, h: usize) -> Result<Vec<Vec<u8>>, String> {
    let vf =
        format!("scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},format=rgb24");
    let saida = Command::new("ffmpeg")
        .args(["-y", "-hide_banner", "-loglevel", "error", "-i"])
        .arg(imagem)
        .args(["-vf", &vf, "-f", "rawvideo", "-"])
        .output()
        .map_err(|e| format!("ffmpeg nao rodou: {e}"))?;
    if !saida.status.success() {
        return Err(format!(
            "ffmpeg falhou: {}",
            String::from_utf8_lossy(&saida.stderr)
                .chars()
                .take(400)
                .collect::<String>()
        ));
    }
    let tam = w * h * 3;
    if tam == 0 || saida.stdout.len() % tam != 0 || saida.stdout.is_empty() {
        return Err(format!(
            "ffmpeg devolveu {} bytes, esperado multiplo de {tam}",
            saida.stdout.len()
        ));
    }
    Ok(saida.stdout.chunks(tam).map(|c| c.to_vec()).collect())
}

#[derive(Serialize)]
pub struct PatchView {
    pub saida: String,
    pub tamanho: usize,
    pub quadros: usize,
    pub tela: [u16; 2],
    pub mudou_tamanho: bool,
    pub problemas: Vec<String>,
}

#[tauri::command]
pub fn patch_imagem(
    caminho_acf: String,
    imagem: String,
    tela_cheia: bool,
) -> Result<PatchView, String> {
    let dados = std::fs::read(&caminho_acf).map_err(texto)?;
    let resumo = inspect::parse(&dados).map_err(texto)?;
    if !resumo.problemas.is_empty() {
        return Err(format!(
            "o .acf de base nao passa na validacao: {}",
            resumo.problemas[0]
        ));
    }
    let (pagina, tex_idx, tex) =
        acha_slot(&resumo).ok_or("nao achei as texturas de imagem (paginas 4/5/6)")?;

    let (w, h) = if tela_cheia {
        (resumo.w as usize, resumo.h as usize)
    } else {
        (tex.w as usize, tex.h as usize)
    };
    let quadros = quadros_rgb(Path::new(&imagem), w, h)?;
    let quads: Vec<Vec<u8>> = quadros
        .iter()
        .map(|q| codec::encode_image(q, w, h))
        .collect();

    let mudou = (w as u16, h as u16) != (tex.w, tex.h);
    let novo = if quads.len() == 1 && !mudou {
        patch::patch_estatico(&dados, &tex, &quadros[0], w, h)
    } else {
        patch::monta(&dados, &resumo, pagina, tex_idx, &quads).map_err(texto)?
    };

    let (resumo2, problemas2) = match inspect::parse(&novo) {
        Ok(r) => (r, Vec::new()),
        Err(e) => return Err(format!("resultado invalido: {e}")),
    };
    if !resumo2.problemas.is_empty() {
        return Err(format!("resultado nao valida: {}", resumo2.problemas[0]));
    }

    let saida = PathBuf::from(&caminho_acf).with_file_name(format!(
        "{}-patch.acf",
        Path::new(&caminho_acf)
            .file_stem()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_else(|| "novo".into())
    ));
    std::fs::write(&saida, &novo).map_err(texto)?;

    Ok(PatchView {
        saida: saida.display().to_string(),
        tamanho: novo.len(),
        quadros: quads.len(),
        tela: [w as u16, h as u16],
        mudou_tamanho: mudou,
        problemas: problemas2,
    })
}
