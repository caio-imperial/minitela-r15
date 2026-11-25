//! Comandos expostos à interface.

use crate::acf::{codec, inspect, patch};
use base64::Engine;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::process::Command;

/// Páginas do `.acf` que guardam as três imagens ("Personalizar Imagens").
pub const PAGINAS_IMAGENS: [usize; 3] = [4, 5, 6];

/// Como a imagem entra na textura.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Ajuste {
    /// Preenche o quadro e corta o excesso (padrão do build).
    #[default]
    Cobrir,
    /// Cabe inteira, com barras pretas.
    Conter,
}

fn numero(v: f64, padrao: f64, lo: f64, hi: f64) -> f64 {
    if v.is_finite() { v.clamp(lo, hi) } else { padrao }
}

/// Filtro do ffmpeg que produz exatamente `w`×`h` RGB.
///
/// `cobrir` escala para cobrir a caixa ampliada por `zoom` e recorta em `w`×`h`,
/// com `px`/`py` (0..1) escolhendo o ponto do recorte. `conter` centraliza com barras.
pub fn filtro(w: usize, h: usize, ajuste: Ajuste, zoom: f64, px: f64, py: f64) -> String {
    let (w, h) = (w.max(4), h.max(4));
    match ajuste {
        Ajuste::Conter => format!(
            "scale={w}:{h}:force_original_aspect_ratio=decrease,\
             pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,format=rgb24"
        ),
        Ajuste::Cobrir => {
            let z = numero(zoom, 1.0, 1.0, 4.0);
            let px = numero(px, 0.5, 0.0, 1.0);
            let py = numero(py, 0.5, 0.0, 1.0);
            let zw = ((w as f64 * z).round() as usize).max(w);
            let zh = ((h as f64 * z).round() as usize).max(h);
            format!(
                "scale={zw}:{zh}:force_original_aspect_ratio=increase,\
                 crop={w}:{h}:(in_w-{w})*{px:.4}:(in_h-{h})*{py:.4},format=rgb24"
            )
        }
    }
}

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

/// Primeira textura de imagem do slot (0..2 => páginas 4/5/6).
fn acha_slot(resumo: &inspect::Resumo, slot: usize) -> Option<(usize, usize, inspect::Textura)> {
    let pagina = *PAGINAS_IMAGENS.get(slot)?;
    let p = resumo.paginas.get(pagina)?;
    for (ti, t) in p.texturas.iter().enumerate() {
        if matches!(t.tipo(), 0x00 | 0x10)
            && t.w > 4
            && t.h > 4
            && (t.addr as usize) < resumo.start as usize
        {
            return Some((pagina, ti, t.clone()));
        }
    }
    None
}

fn png_url(rgb: &[u8], w: usize, h: usize) -> Result<String, String> {
    let mut png_bytes = Vec::new();
    {
        let mut enc = png::Encoder::new(&mut png_bytes, w as u32, h as u32);
        enc.set_color(png::ColorType::Rgb);
        enc.set_depth(png::BitDepth::Eight);
        let mut writer = enc.write_header().map_err(texto)?;
        writer.write_image_data(rgb).map_err(texto)?;
    }
    let b64 = base64::engine::general_purpose::STANDARD.encode(&png_bytes);
    Ok(format!("data:image/png;base64,{b64}"))
}

fn texto_de_slot(rgb: &[u8], w: usize, h: usize) -> String {
    png_url(rgb, w, h).unwrap_or_default()
}

#[derive(Serialize)]
pub struct SlotView {
    pub indice: usize,
    pub pagina: usize,
    pub w: u16,
    pub h: u16,
    pub previa: String,
}

/// As três imagens do `.acf`, com miniatura em PNG para escolher qual trocar.
#[tauri::command]
pub fn slots(caminho: String) -> Result<Vec<SlotView>, String> {
    let dados = std::fs::read(&caminho).map_err(texto)?;
    let resumo = inspect::parse(&dados).map_err(texto)?;
    let mut itens = Vec::new();
    for indice in 0..PAGINAS_IMAGENS.len() {
        let Some((pagina, _, tex)) = acha_slot(&resumo, indice) else {
            continue;
        };
        let (w, h) = (tex.w as usize, tex.h as usize);
        let ini = tex.addr as usize;
        let fim = (ini + tex.slice as usize).min(dados.len());
        let previa = if fim > ini {
            texto_de_slot(&codec::decode_image(&dados[ini..fim], w, h), w, h)
        } else {
            String::new()
        };
        itens.push(SlotView {
            indice,
            pagina,
            w: tex.w,
            h: tex.h,
            previa,
        });
    }
    Ok(itens)
}

/// Prévia da textura de um slot como PNG em data URL.
///
/// Usa o decodificador de **uma partição** (o que geramos). Blocos oficiais de
/// duas/três partições aparecem com artefatos — o modo 1 ainda não está implementado.
#[tauri::command]
pub fn preview(caminho: String, slot: Option<usize>) -> Result<String, String> {
    let dados = std::fs::read(&caminho).map_err(texto)?;
    let resumo = inspect::parse(&dados).map_err(texto)?;
    let tex = acha_slot(&resumo, slot.unwrap_or(0))
        .map(|(_, _, t)| t)
        .ok_or("nao achei textura de imagem")?;

    let (w, h) = (tex.w as usize, tex.h as usize);
    let ini = tex.addr as usize;
    let fim = ini + tex.slice as usize;
    let rgb = codec::decode_image(&dados[ini..fim], w, h);
    png_url(&rgb, w, h)
}

/// Quadros RGB de uma imagem, no enquadramento pedido.
fn ffmpeg_rgb(imagem: &Path, w: usize, h: usize, filtro: &str) -> Result<Vec<Vec<u8>>, String> {
    let saida = Command::new("ffmpeg")
        .args(["-y", "-hide_banner", "-loglevel", "error", "-i"])
        .arg(imagem)
        .args(["-vf", filtro, "-f", "rawvideo", "-"])
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

/// Imagem do usuário como data URL (lado maior até 640 px) para o recorte interativo.
///
/// O recorte em si é feito no ffmpeg na hora de gerar; aqui só é preciso a imagem
/// para a interface mostrar o enquadramento em tempo real.
#[tauri::command]
pub fn abrir_imagem(imagem: String) -> Result<String, String> {
    let saida = Command::new("ffmpeg")
        .args(["-y", "-hide_banner", "-loglevel", "error", "-i"])
        .arg(&imagem)
        .args([
            "-vf",
            "scale=640:640:force_original_aspect_ratio=decrease",
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "-q:v",
            "4",
            "-",
        ])
        .output()
        .map_err(|e| format!("ffmpeg nao rodou: {e}"))?;
    if !saida.status.success() || saida.stdout.is_empty() {
        return Err(format!(
            "nao consegui abrir a imagem: {}",
            String::from_utf8_lossy(&saida.stderr)
                .chars()
                .take(300)
                .collect::<String>()
        ));
    }
    let b64 = base64::engine::general_purpose::STANDARD.encode(&saida.stdout);
    Ok(format!("data:image/jpeg;base64,{b64}"))
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
    /// página de cada slot editado (para exibir a imagem depois de gravar)
    pub paginas: Vec<usize>,
}

/// Uma imagem a colocar num slot.
#[derive(Debug, Clone, Deserialize)]
pub struct Pedaco {
    pub slot: usize,
    pub imagem: String,
    #[serde(default)]
    pub tela_cheia: bool,
    #[serde(default)]
    pub ajuste: Ajuste,
    #[serde(default = "meio")]
    pub zoom: f64,
    #[serde(default = "meio")]
    pub px: f64,
    #[serde(default = "meio")]
    pub py: f64,
}

fn meio() -> f64 {
    1.0
}

/// Troca uma ou mais imagens (slots 0..2) num `.acf` e grava o resultado no HOME.
#[tauri::command]
pub fn patch_imagens(caminho_acf: String, pedacos: Vec<Pedaco>) -> Result<PatchView, String> {
    if pedacos.is_empty() {
        return Err("nenhuma imagem escolhida".into());
    }
    let mut vistos = std::collections::BTreeSet::new();
    for p in &pedacos {
        if *PAGINAS_IMAGENS.get(p.slot).unwrap_or(&usize::MAX) == usize::MAX {
            return Err(format!("slot invalido: {}", p.slot + 1));
        }
        if !vistos.insert(p.slot) {
            return Err(format!("slot {} repetido", p.slot + 1));
        }
    }

    let data0 = std::fs::read(&caminho_acf).map_err(texto)?;
    let resumo0 = inspect::parse(&data0).map_err(texto)?;
    if !resumo0.problemas.is_empty() {
        return Err(format!(
            "o .acf de base nao passa na validacao: {}",
            resumo0.problemas[0]
        ));
    }

    let mut data = data0;
    let mut quadros_total = 0usize;
    let mut mudou = false;
    let mut tela = [resumo0.w, resumo0.h];
    let mut paginas = Vec::new();

    for p in &pedacos {
        // reparse a cada imagem: um GIF animado muda tamanho e endereços
        let resumo = inspect::parse(&data).map_err(texto)?;
        if !resumo.problemas.is_empty() {
            return Err(format!(
                "estado intermediario invalido: {}",
                resumo.problemas[0]
            ));
        }
        let (pagina, tex_idx, tex) =
            acha_slot(&resumo, p.slot).ok_or_else(|| format!("slot {} sem imagem", p.slot + 1))?;
        let (w, h) = if p.tela_cheia {
            (resumo.w as usize, resumo.h as usize)
        } else {
            (tex.w as usize, tex.h as usize)
        };
        if w < 4 || h < 4 {
            return Err(format!("slot {}: tamanho {w}x{h} invalido", p.slot + 1));
        }
        let vf = filtro(w, h, p.ajuste, p.zoom, p.px, p.py);
        let quadros = ffmpeg_rgb(Path::new(&p.imagem), w, h, &vf)?;
        if quadros.len() > 96 {
            return Err(format!(
                "{} quadros; o limite do trailer aqui e 96",
                quadros.len()
            ));
        }
        let quads: Vec<Vec<u8>> = quadros
            .iter()
            .map(|q| codec::encode_image(q, w, h))
            .collect();

        let mudou_este = (w as u16, h as u16) != (tex.w, tex.h);
        data = if quads.len() == 1 && !mudou_este {
            patch::patch_estatico(&data, &tex, &quadros[0], w, h)
        } else {
            patch::monta(&data, &resumo, pagina, tex_idx, &quads).map_err(texto)?
        };
        quadros_total += quads.len();
        mudou |= mudou_este;
        tela = [w as u16, h as u16];
        paginas.push(pagina);
    }

    let resumo2 = inspect::parse(&data).map_err(|e| format!("resultado invalido: {e}"))?;
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
    std::fs::write(&saida, &data).map_err(texto)?;

    Ok(PatchView {
        saida: saida.display().to_string(),
        tamanho: data.len(),
        quadros: quadros_total,
        tela,
        mudou_tamanho: mudou,
        problemas: resumo2.problemas,
        paginas,
    })
}

/// Atalho de uma imagem só no slot 1, usado pelos testes.
#[cfg(test)]
pub fn patch_imagem(
    caminho_acf: String,
    imagem: String,
    tela_cheia: bool,
) -> Result<PatchView, String> {
    patch_imagens(
        caminho_acf,
        vec![Pedaco {
            slot: 0,
            imagem,
            tela_cheia,
            ajuste: Ajuste::Cobrir,
            zoom: 1.0,
            px: 0.5,
            py: 0.5,
        }],
    )
}

#[cfg(test)]
mod tests {
    use crate::acf::inspect;
    /// Prévia do tema de fábrica (pula se o pacote não estiver instalado).
    #[test]
    fn preview_do_tema_de_fabrica() {
        let caminho = "/usr/share/minitela/resources/ACF/Texture.acf";
        if !std::path::Path::new(caminho).exists() {
            return;
        }
        let url = super::preview(caminho.to_string(), None).expect("preview");
        assert!(url.starts_with("data:image/png;base64,"));
        assert!(url.len() > 1000, "png vazio?");
    }

    #[test]
    fn filtro_cobrir_amplia_e_recorta() {
        let vf = super::filtro(240, 240, super::Ajuste::Cobrir, 1.0, 0.5, 0.5);
        assert!(vf.contains("force_original_aspect_ratio=increase"), "{vf}");
        assert!(vf.contains("crop=240:240"), "{vf}");
        assert!(vf.contains("(in_w-240)*0.5000"), "{vf}");

        // zoom fora da faixa e NaN não geram expressão inválida
        let vf = super::filtro(240, 240, super::Ajuste::Cobrir, 9.0, f64::NAN, 2.0);
        assert!(vf.contains("scale=960:960"), "{vf}");
        assert!(vf.contains("*0.5000"), "{vf}");
        assert!(vf.contains("*1.0000"), "{vf}");
    }

    #[test]
    fn filtro_conter_centraliza_com_barras() {
        let vf = super::filtro(192, 192, super::Ajuste::Conter, 3.0, 0.0, 0.0);
        assert!(vf.contains("force_original_aspect_ratio=decrease"), "{vf}");
        assert!(vf.contains("pad=192:192"), "{vf}");
        assert!(!vf.contains("crop="), "conter nao recorta: {vf}");
    }

    /// Slot no tamanho original: caminho rápido (sobrescreve no lugar), arquivo do
    /// mesmo tamanho e a página do slot continua válida.
    #[test]
    fn patch_no_tamanho_do_slot_nao_muda_o_arquivo() {
        let (Some(base), true) = (tema_de_fabrica(), tem_ffmpeg()) else {
            return;
        };
        let img = imagem_teste("slot-192.png", 50, 50);
        let antes = std::fs::read(&base).expect("base");
        let v = super::patch_imagens(
            base.clone(),
            vec![super::Pedaco {
                slot: 1,
                imagem: img.display().to_string(),
                tela_cheia: false,
                ajuste: super::Ajuste::Cobrir,
                zoom: 1.0,
                px: 0.5,
                py: 0.5,
            }],
        )
        .expect("gerar");
        assert_eq!(v.paginas, vec![5]);
        assert!(!v.mudou_tamanho);
        assert_eq!(v.tela, [192, 192]);
        assert!(v.problemas.is_empty());
        let depois = std::fs::read(&v.saida).expect("saida");
        assert_eq!(antes.len(), depois.len(), "caminho rápido nao remonta");
    }

    #[test]
    fn abrir_imagem_devolve_data_url_pequena() {
        if !tem_ffmpeg() {
            return;
        }
        let img = imagem_teste("abrir.png", 1200, 800);
        let url = super::abrir_imagem(img.display().to_string()).expect("abrir");
        assert!(url.starts_with("data:image/jpeg;base64,"));
        assert!(url.len() < 200_000, "previa grande demais: {} B", url.len());
    }

    fn tema_de_fabrica() -> Option<String> {
        let caminho = "/usr/share/minitela/resources/ACF/Texture.acf";
        std::path::Path::new(caminho)
            .exists()
            .then(|| caminho.to_string())
    }

    fn tem_ffmpeg() -> bool {
        std::process::Command::new("ffmpeg")
            .arg("-version")
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status()
            .is_ok_and(|s| s.success())
    }

    /// Imagem RGB sintética (o teste não depende de arquivo do usuário).
    fn imagem_teste(nome: &str, w: u32, h: u32) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join("minitela-teste");
        std::fs::create_dir_all(&dir).expect("tmp");
        let caminho = dir.join(nome);
        let mut png_bytes = Vec::new();
        {
            let mut enc = png::Encoder::new(&mut png_bytes, w, h);
            enc.set_color(png::ColorType::Rgb);
            enc.set_depth(png::BitDepth::Eight);
            let mut writer = enc.write_header().expect("header");
            let mut rgb = Vec::with_capacity((w * h * 3) as usize);
            for y in 0..h {
                for x in 0..w {
                    rgb.extend_from_slice(&[(x * 3) as u8, (y * 3) as u8, ((x + y) * 2) as u8]);
                }
            }
            writer.write_image_data(&rgb).expect("pixels");
        }
        std::fs::write(&caminho, png_bytes).expect("gravar png");
        caminho
    }

    #[test]
    fn slots_do_tema_de_fabrica_sao_tres() {
        let Some(base) = tema_de_fabrica() else {
            return;
        };
        let lista = super::slots(base).expect("slots");
        assert_eq!(lista.len(), 3, "o tema de fabrica tem 3 imagens");
        assert_eq!(
            lista.iter().map(|s| s.pagina).collect::<Vec<_>>(),
            vec![4, 5, 6]
        );
        assert!(lista.iter().all(|s| s.previa.starts_with("data:image/png")));
        assert_ne!(lista[0].previa, lista[1].previa, "miniaturas distintas");
    }

    /// Dois slots no mesmo .acf: o terceiro tem de sair intacto e a página a exibir
    /// tem de ser a do primeiro slot editado.
    #[test]
    fn patch_de_dois_slots_preserva_o_terceiro() {
        let (Some(base), true) = (tema_de_fabrica(), tem_ffmpeg()) else {
            return;
        };
        let img = imagem_teste("dois-slots.png", 80, 60);
        let pedaco = |slot: usize| super::Pedaco {
            slot,
            imagem: img.display().to_string(),
            tela_cheia: true,
            ajuste: super::Ajuste::Cobrir,
            zoom: 1.0,
            px: 0.5,
            py: 0.5,
        };
        let v = super::patch_imagens(base.clone(), vec![pedaco(0), pedaco(2)]).expect("gerar");
        assert_eq!(v.paginas, vec![4, 6]);
        assert_eq!(v.quadros, 2);
        assert_eq!(v.tela, [240, 240]);
        assert!(v.mudou_tamanho, "192 -> 240");
        assert!(v.problemas.is_empty());

        let antes = std::fs::read(&base).expect("base");
        let depois = std::fs::read(&v.saida).expect("saida");
        let r_antes = inspect::parse(&antes).expect("parse base");
        let r_depois = inspect::parse(&depois).expect("parse saida");
        let textura = |r: &inspect::Resumo, slot: usize| {
            let (_, _, t) = super::acha_slot(r, slot).expect("slot");
            let ini = t.addr as usize;
            (t.w, t.h, ini, t.slice as usize)
        };
        for slot in [0usize, 2] {
            let (w, h, ini, n) = textura(&r_depois, slot);
            assert_eq!((w, h), (240, 240), "slot {slot} em tela cheia");
            assert!(ini + n <= depois.len());
        }
        // o slot do meio ficou como estava no tema
        let (_, _, ini_a, n_a) = textura(&r_antes, 1);
        let (wa, ha, ini_d, n_d) = textura(&r_depois, 1);
        assert_eq!((wa, ha), (192, 192));
        assert_eq!(n_a, n_d, "fatia do slot do meio nao muda");
        assert_eq!(
            &antes[ini_a..ini_a + n_a],
            &depois[ini_d..ini_d + n_d],
            "o slot 2 (nao editado) tem de ficar intacto"
        );
    }

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
