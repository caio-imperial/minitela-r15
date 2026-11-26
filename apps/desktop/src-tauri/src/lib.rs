//! Backend do app desktop da minitela (Tauri).
//!
//! Por enquanto o app só *diagnostica* o ambiente: o mesmo que o `minitela doctor`
//! faz em Python. O porte do protocolo e do codec vem depois, validado contra os
//! fixtures gerados pelo Python (ver apps/desktop/README.md).

pub mod acf;
mod commands;
pub mod device;
pub mod sysinfo;

use serde::Serialize;
use std::fs;
use std::path::Path;

#[derive(Serialize)]
pub struct Item {
    pub nome: String,
    pub estado: String,
    pub detalhe: String,
}

fn no_path(programa: &str) -> Option<String> {
    let path = std::env::var_os("PATH")?;
    for dir in std::env::split_paths(&path) {
        let p = dir.join(programa);
        if p.is_file() {
            return Some(p.display().to_string());
        }
    }
    None
}

fn item(nome: &str, ok: bool, detalhe: String) -> Item {
    Item {
        nome: nome.to_string(),
        estado: if ok { "ok".into() } else { "aviso".into() },
        detalhe,
    }
}

fn app_oficial_rodando() -> bool {
    let Ok(entradas) = fs::read_dir("/proc") else {
        return false;
    };
    for e in entradas.flatten() {
        if !e
            .file_name()
            .to_string_lossy()
            .chars()
            .all(|c| c.is_ascii_digit())
        {
            continue;
        }
        if let Ok(comm) = fs::read_to_string(e.path().join("comm"))
            && comm.trim() == "minitela"
        {
            return true;
        }
    }
    false
}

fn portas_acm() -> Vec<String> {
    let mut portas = Vec::new();
    if let Ok(entradas) = fs::read_dir("/dev") {
        for e in entradas.flatten() {
            let nome = e.file_name().to_string_lossy().to_string();
            if nome.starts_with("ttyACM") {
                portas.push(format!("/dev/{nome}"));
            }
        }
    }
    portas.sort();
    portas
}

#[tauri::command]
fn ambiente() -> Vec<Item> {
    let mut itens = Vec::new();

    for (nome, bin) in [
        ("python3", "python3"),
        ("ffmpeg", "ffmpeg"),
        ("wine", "wine"),
    ] {
        match no_path(bin) {
            Some(p) => itens.push(item(nome, true, p)),
            None => itens.push(item(
                nome,
                false,
                if nome == "wine" {
                    "ausente — só necessário para build/layout".into()
                } else {
                    "não encontrado no PATH".into()
                },
            )),
        }
    }

    let portas = portas_acm();
    itens.push(item(
        "tela",
        !portas.is_empty(),
        if portas.is_empty() {
            "nenhum /dev/ttyACM* (conectada?)".into()
        } else {
            portas.join(", ")
        },
    ));

    let rodando = app_oficial_rodando();
    itens.push(Item {
        nome: "app oficial".into(),
        estado: if rodando { "aviso".into() } else { "ok".into() },
        detalhe: if rodando {
            "rodando — segura a porta serial".into()
        } else {
            "parado".into()
        },
    });

    let acfs = Path::new("/usr/share/minitela/resources/ACF");
    itens.push(item(
        "temas de fábrica",
        acfs.is_dir(),
        acfs.display().to_string(),
    ));

    let template = home().join(".local/share/minitela-custom/out/minitela.acf");
    itens.push(item(
        "template 240×240",
        template.exists(),
        template.display().to_string(),
    ));

    itens
}

fn home() -> std::path::PathBuf {
    std::env::var_os("HOME")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|| std::path::PathBuf::from("/"))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            ambiente,
            commands::sugestao_base,
            commands::slots,
            commands::preview,
            commands::abrir_imagem,
            commands::diagnostico,
            commands::patch_imagens,
            commands::gravar,
            commands::controle_estado,
            commands::conectar,
            commands::desconectar,
            commands::devolver_ao_app,
            commands::pagina,
            commands::brilho,
            commands::parar_app,
            commands::tags_uma_vez,
            commands::tags_estado
        ])
        .run(tauri::generate_context!())
        .expect("erro ao iniciar o app");
}
