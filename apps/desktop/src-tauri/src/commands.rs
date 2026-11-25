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

/// Base sugerida para o patch: o tema de fábrica, ou o template compilado.
#[tauri::command]
pub fn sugestao_base() -> Option<String> {
    let fabrica = "/usr/share/minitela/resources/ACF/Texture.acf";
    if Path::new(fabrica).exists() {
        return Some(fabrica.to_string());
    }
    let template = std::env::var_os("HOME")
        .map(PathBuf::from)?
        .join(".local/share/minitela-custom/out/minitela.acf");
    template.exists().then(|| template.display().to_string())
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

static DAEMON: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
static COLETOR: std::sync::OnceLock<crate::sysinfo::Coletor> = std::sync::OnceLock::new();

fn coletor() -> &'static crate::sysinfo::Coletor {
    COLETOR.get_or_init(crate::sysinfo::Coletor::default)
}

#[derive(Serialize)]
pub struct TagsView {
    pub relogio: String,
    pub bateria: Option<u32>,
    pub carregando: Option<u8>,
    pub cpu: Option<u8>,
    pub wifi: Option<String>,
    pub sinal: Option<u8>,
    pub enviadas: usize,
}

/// Lê o sistema e manda um round de tags (precisa da porta livre).
#[tauri::command]
pub fn tags_uma_vez() -> Result<TagsView, String> {
    let caminho = crate::device::encontra_porta().ok_or("nenhum /dev/ttyACM*")?;
    let mut p = crate::device::Porta::abre(caminho).map_err(texto)?;

    let relogio = crate::sysinfo::relogio();
    let (bat, estado) = match crate::sysinfo::bateria() {
        Some((pct, e)) => (Some(pct), Some(e)),
        None => (None, None),
    };
    let cpu = crate::sysinfo::cpu(coletor());
    let (ssid, sinal) = crate::sysinfo::wifi();

    let mut enviadas = 0usize;
    p.set_texto(crate::sysinfo::TAG_RELOGIO, &relogio)
        .map_err(texto)?;
    enviadas += 1;
    if let Some(pct) = bat {
        p.set_registradores(&[(crate::sysinfo::TAG_BATERIA, pct)])
            .map_err(texto)?;
        enviadas += 1;
    }
    if let Some(c) = cpu {
        p.set_registradores(&[(crate::sysinfo::TAG_CPU, c as u32)])
            .map_err(texto)?;
        enviadas += 1;
    }
    if let Some(nome) = &ssid {
        p.set_texto(crate::sysinfo::TAG_WIFI_SSID, nome)
            .map_err(texto)?;
        enviadas += 1;
    }
    if let Some(q) = sinal {
        p.set_registradores(&[(crate::sysinfo::TAG_WIFI_SINAL, q as u32)])
            .map_err(texto)?;
        enviadas += 1;
    }

    Ok(TagsView {
        relogio,
        bateria: bat,
        carregando: estado,
        cpu,
        wifi: ssid,
        sinal,
        enviadas,
    })
}

/// Liga/desliga o daemon (5 s). Ele segura a porta enquanto roda.
#[tauri::command]
pub fn tags_daemon(ligar: bool) -> Result<bool, String> {
    use std::sync::atomic::Ordering;
    if !ligar {
        DAEMON.store(false, Ordering::SeqCst);
        return Ok(false);
    }
    if DAEMON.swap(true, Ordering::SeqCst) {
        return Ok(true); // já rodando
    }
    std::thread::spawn(|| {
        while DAEMON.load(Ordering::SeqCst) {
            let _ = tags_uma_vez();
            for _ in 0..50 {
                if !DAEMON.load(Ordering::SeqCst) {
                    return;
                }
                std::thread::sleep(std::time::Duration::from_millis(100));
            }
        }
    });
    Ok(true)
}

#[tauri::command]
pub fn parar_app() -> Result<bool, String> {
    if !crate::device::app_oficial_rodando() {
        return Ok(false);
    }
    let status = Command::new("pkill")
        .args(["-x", "minitela"])
        .status()
        .map_err(texto)?;
    std::thread::sleep(std::time::Duration::from_secs(2));
    Ok(status.success())
}

#[derive(Serialize)]
pub struct GravacaoView {
    pub porta: String,
    pub tamanho: usize,
    pub bytes: u64,
}

#[tauri::command]
pub async fn gravar(caminho: String, pagina: Option<u32>) -> Result<GravacaoView, String> {
    let dados = std::fs::read(&caminho).map_err(texto)?;
    if crate::device::app_oficial_rodando() {
        return Err("o app oficial esta rodando e segura a porta: feche com 'parar app'".into());
    }
    let porta =
        crate::device::encontra_porta().ok_or("nenhum /dev/ttyACM*: a tela esta conectada?")?;
    let inicio = std::time::Instant::now();
    let caminho_porta = porta.clone();
    let tamanho = dados.len();
    let dados_movidos = dados.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let mut p = crate::device::Porta::abre(caminho_porta.clone()).map_err(texto)?;
        p.envia_textura(&dados_movidos, |_| {}).map_err(texto)?;
        if let Some(n) = pagina {
            std::thread::sleep(std::time::Duration::from_secs(4));
            // o firmware reenumera o USB ao fim; reabre antes de trocar a página
            for _ in 0..20 {
                if let Some(novo) = crate::device::encontra_porta()
                    && let Ok(mut p2) = crate::device::Porta::abre(novo)
                    && p2.pagina(n).is_ok()
                {
                    return Ok::<usize, String>(1);
                }
                std::thread::sleep(std::time::Duration::from_millis(500));
            }
            return Ok::<usize, String>(0);
        }
        Ok::<usize, String>(0)
    })
    .await
    .map_err(texto)??;
    Ok(GravacaoView {
        porta: porta.display().to_string(),
        tamanho,
        bytes: inicio.elapsed().as_millis() as u64,
    })
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

    // A base costuma ser /usr/share/minitela/... (do root): o resultado vai para o
    // diretorio do usuario, nunca ao lado da base.
    let dir = std::env::var_os("HOME")
        .map(PathBuf::from)
        .ok_or("HOME nao definido")?
        .join(".local/share/minitela-custom/out");
    std::fs::create_dir_all(&dir).map_err(texto)?;
    let saida = dir.join(format!(
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

#[cfg(test)]
mod tests {
    /// Gera um .acf a partir do tema de fábrica, sem tocar no device.
    /// Rode com: MINITELA_IMAGEM=<arquivo> cargo test --lib -- --ignored gera_acf
    #[test]
    #[ignore]
    fn gera_acf() {
        let imagem = std::env::var("MINITELA_IMAGEM").expect("defina MINITELA_IMAGEM");
        let base = "/usr/share/minitela/resources/ACF/Texture.acf".to_string();
        let v = super::patch_imagem(base, imagem, true).expect("gerar");
        eprintln!(
            "{} | {} B | {} quadro(s) | {:?}",
            v.saida, v.tamanho, v.quadros, v.tela
        );
        assert!(std::path::Path::new(&v.saida).exists());
        assert!(
            v.saida.starts_with("/home/"),
            "saida deve ser gravavel pelo usuario"
        );
        assert!(v.problemas.is_empty());
    }

    /// Manda um round de tags no hardware. Rode com:
    ///   cargo test --lib -- --ignored manda_tags --nocapture
    #[test]
    #[ignore]
    fn manda_tags() {
        assert!(
            !crate::device::app_oficial_rodando(),
            "pare o app oficial antes"
        );
        let v = super::tags_uma_vez().expect("mandar tags");
        assert!(v.enviadas >= 1);
        eprintln!(
            "{} | bateria {:?} | cpu {:?} | wifi {:?} | {} tags",
            v.relogio, v.bateria, v.cpu, v.wifi, v.enviadas
        );
    }
}
