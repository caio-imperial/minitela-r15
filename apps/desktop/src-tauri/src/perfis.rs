//! Perfis da minitela: cada perfil é um "save" — o `.acf` que vai para a tela mais a
//! página em que ele é exibido.
//!
//! O perfil **de fábrica** não tem arquivo próprio: aponta para o `Texture.acf` instalado
//! pela Positivo. Ao gerar uma customização com o perfil de fábrica ativo, o app cria um
//! perfil novo (`meu tema`) para não sobrescrever o padrão.

use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

pub const ID_FABRICA: &str = "fabrica";
pub const TEMA_DE_FABRICA: &str = "/usr/share/minitela/resources/ACF/Texture.acf";

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SlotDoPerfil {
    pub indice: usize,
    pub pagina: u32,
    pub largura: u16,
    pub altura: u16,
    pub quadros: usize,
    /// cópia do arquivo que o usuário escolheu (caminho relativo ao perfil)
    pub origem: Option<String>,
    /// PNG decodificado do `tema.acf` (caminho relativo ao perfil)
    pub thumb: Option<String>,
    pub ajuste: String,
    pub zoom: f64,
    pub px: f64,
    pub py: f64,
    pub tela_cheia: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Perfil {
    pub id: String,
    pub nome: String,
    pub pagina: u32,
    /// `None` = perfil de fábrica (usa o tema instalado)
    pub arquivo: Option<String>,
    pub atualizado: Option<String>,
    #[serde(default)]
    pub criado: Option<String>,
    #[serde(default)]
    pub base: Option<String>,
    #[serde(default)]
    pub thumb: Option<String>,
    #[serde(default)]
    pub slots: Vec<SlotDoPerfil>,
}

fn home() -> Option<PathBuf> {
    std::env::var_os("HOME").map(PathBuf::from)
}

/// Raiz nova: `~/.local/share/minitela/perfis` (a antiga `minitela-custom` é do ODM).
pub fn dir_perfis() -> Option<PathBuf> {
    let novo = home()?.join(".local/share/minitela/perfis");
    migra_se_preciso(&novo);
    Some(novo)
}

/// Move os perfis da árvore antiga na primeira vez que rodar.
fn migra_se_preciso(novo: &Path) {
    if novo.exists() {
        return;
    }
    let Some(antigo) = home().map(|h| h.join(".local/share/minitela-custom/perfis")) else {
        return;
    };
    if !antigo.exists() {
        return;
    }
    let _ = std::fs::create_dir_all(novo);
    if let Ok(entradas) = std::fs::read_dir(&antigo) {
        for e in entradas.flatten() {
            let destino = novo.join(e.file_name());
            if !destino.exists() {
                let _ = std::fs::rename(e.path(), destino);
            }
        }
    }
    let _ = std::fs::remove_dir(&antigo);
}

pub fn dir_perfil(id: &str) -> Option<PathBuf> {
    Some(dir_perfis()?.join(id))
}

/// Copia o arquivo escolhido para `originais/` e devolve o caminho relativo.
pub fn copia_original(id: &str, slot: usize, origem: &Path) -> Result<String, String> {
    let dir = dir_perfil(id).ok_or("HOME nao definido")?.join("originais");
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let ext = origem
        .extension()
        .map(|e| e.to_string_lossy().to_lowercase())
        .unwrap_or_else(|| "bin".into());
    let nome = format!("slot-{}.{}", slot + 1, ext);
    let destino = dir.join(&nome);
    std::fs::copy(origem, &destino).map_err(|e| e.to_string())?;
    Ok(format!("originais/{nome}"))
}

/// Grava um PNG de miniatura (tamanho nativo) e devolve o caminho relativo.
pub fn grava_thumb(id: &str, nome: &str, w: u16, h: u16, rgb: &[u8]) -> Result<String, String> {
    let dir = dir_perfil(id).ok_or("HOME nao definido")?.join("thumbs");
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let mut bytes = Vec::new();
    {
        let mut enc = png::Encoder::new(&mut bytes, w as u32, h as u32);
        enc.set_color(png::ColorType::Rgb);
        enc.set_depth(png::BitDepth::Eight);
        enc.write_header()
            .map_err(|e| e.to_string())?
            .write_image_data(rgb)
            .map_err(|e| e.to_string())?;
    }
    let arquivo = format!("{nome}.png");
    std::fs::write(dir.join(&arquivo), bytes).map_err(|e| e.to_string())?;
    Ok(format!("thumbs/{arquivo}"))
}

/// Caminho absoluto de um arquivo relativo do perfil (para servir à interface).
pub fn caminho_absoluto(id: &str, relativo: &str) -> Option<PathBuf> {
    let p = dir_perfil(id)?.join(relativo);
    p.exists().then_some(p)
}

/// Atualiza os slots informados **sem apagar** os que não vieram nesta gravação
/// (um patch de um slot só não pode esquecer os outros).
pub fn define_slots(id: &str, novos: Vec<SlotDoPerfil>) -> Result<(), String> {
    let mut p = lista()
        .into_iter()
        .find(|p| p.id == id)
        .ok_or(format!("perfil {id} nao existe"))?;
    for novo in novos {
        match p.slots.iter_mut().find(|s| s.indice == novo.indice) {
            Some(atual) => *atual = novo,
            None => p.slots.push(novo),
        }
    }
    p.slots.sort_by_key(|s| s.indice);
    p.thumb = p.slots.first().and_then(|s| s.thumb.clone());
    if p.base.is_none() {
        p.base = Some(TEMA_DE_FABRICA.into());
    }
    if p.criado.is_none() {
        p.criado = Some(chrono::Local::now().format("%Y-%m-%dT%H:%M:%S").to_string());
    }
    p.atualizado = Some(chrono::Local::now().format("%d/%m %H:%M").to_string());
    salva(&p)
}

fn arquivo_ativo() -> Option<PathBuf> {
    Some(home()?.join(".config/minitela/perfil-ativo.txt"))
}

/// Id a partir do nome: minúsculas, sem acento problemático, `-` no lugar de espaço.
fn slug(nome: &str) -> String {
    let mut s = String::new();
    for c in nome.trim().chars() {
        if c.is_ascii_alphanumeric() {
            s.push(c.to_ascii_lowercase());
        } else if !s.ends_with('-') {
            s.push('-');
        }
    }
    let s = s.trim_matches('-').to_string();
    if s.is_empty() { "perfil".into() } else { s }
}

pub fn de_fabrica() -> Perfil {
    Perfil {
        id: ID_FABRICA.into(),
        nome: "de fábrica".into(),
        pagina: 1,
        arquivo: None,
        atualizado: None,
        criado: None,
        base: Some(TEMA_DE_FABRICA.into()),
        thumb: None,
        slots: Vec::new(),
    }
}

/// Caminho do `.acf` de um perfil (o de fábrica aponta para o tema instalado).
pub fn caminho_tema(id: &str) -> Option<PathBuf> {
    if id == ID_FABRICA {
        let p = PathBuf::from(TEMA_DE_FABRICA);
        return p.exists().then_some(p);
    }
    let p = dir_perfis()?.join(id).join("tema.acf");
    p.exists().then_some(p)
}

/// Lista os perfis do disco (o de fábrica vem sempre primeiro).
pub fn lista() -> Vec<Perfil> {
    let mut perfis = vec![de_fabrica()];
    let Some(dir) = dir_perfis() else {
        return perfis;
    };
    let Ok(entradas) = std::fs::read_dir(dir) else {
        return perfis;
    };
    for e in entradas.flatten() {
        let caminho = e.path().join("perfil.json");
        let Ok(texto) = std::fs::read_to_string(&caminho) else {
            continue;
        };
        if let Ok(p) = serde_json::from_str::<Perfil>(&texto) {
            perfis.push(p);
        }
    }
    perfis.sort_by_key(|p| p.nome.to_lowercase());
    perfis
}

pub fn ativo_id() -> String {
    std::fs::read_to_string(arquivo_ativo().unwrap_or_default())
        .ok()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| ID_FABRICA.into())
}

pub fn define_ativo(id: &str) -> Result<(), String> {
    let arq = arquivo_ativo().ok_or("HOME nao definido")?;
    if let Some(dir) = arq.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    std::fs::write(&arq, id).map_err(|e| e.to_string())
}

pub fn ativo() -> Perfil {
    let id = ativo_id();
    lista()
        .into_iter()
        .find(|p| p.id == id)
        .unwrap_or_else(de_fabrica)
}

fn salva(p: &Perfil) -> Result<(), String> {
    let dir = dir_perfis().ok_or("HOME nao definido")?.join(&p.id);
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let texto = serde_json::to_string_pretty(p).map_err(|e| e.to_string())?;
    std::fs::write(dir.join("perfil.json"), texto).map_err(|e| e.to_string())
}

/// Cria (ou reaproveita) um perfil novo, sem tema ainda.
pub fn cria(nome: &str) -> Result<Perfil, String> {
    let nome = nome.trim();
    if nome.is_empty() {
        return Err("o perfil precisa de um nome".into());
    }
    let id = slug(nome);
    if let Some(p) = lista().into_iter().find(|p| p.id == id) {
        return Ok(p);
    }
    let agora = chrono::Local::now().format("%Y-%m-%dT%H:%M:%S").to_string();
    let p = Perfil {
        id,
        nome: nome.to_string(),
        pagina: 5,
        arquivo: None,
        atualizado: None,
        criado: Some(agora),
        base: Some(TEMA_DE_FABRICA.into()),
        thumb: None,
        slots: Vec::new(),
    };
    salva(&p)?;
    Ok(p)
}

/// Registra que o perfil recebeu um `.acf` novo (o "save").
pub fn grava_tema(id: &str, dados: &[u8], pagina: u32) -> Result<PathBuf, String> {
    if id == ID_FABRICA {
        return Err("o perfil de fábrica não é gravável".into());
    }
    let dir = dir_perfis().ok_or("HOME nao definido")?.join(id);
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let caminho = dir.join("tema.acf");
    std::fs::write(&caminho, dados).map_err(|e| e.to_string())?;
    let mut p = lista()
        .into_iter()
        .find(|p| p.id == id)
        .unwrap_or_else(|| Perfil {
            id: id.to_string(),
            nome: id.to_string(),
            pagina,
            arquivo: None,
            atualizado: None,
            criado: Some(chrono::Local::now().format("%Y-%m-%dT%H:%M:%S").to_string()),
            base: Some(TEMA_DE_FABRICA.into()),
            thumb: None,
            slots: Vec::new(),
        });
    p.arquivo = Some("tema.acf".into());
    p.pagina = pagina;
    p.atualizado = Some(chrono::Local::now().format("%d/%m %H:%M").to_string());
    salva(&p)?;
    Ok(caminho)
}

pub fn apaga(id: &str) -> Result<(), String> {
    if id == ID_FABRICA {
        return Err("o perfil de fábrica não pode ser apagado".into());
    }
    if let Some(dir) = dir_perfis() {
        let alvo = dir.join(id);
        if alvo.exists() {
            std::fs::remove_dir_all(&alvo).map_err(|e| e.to_string())?;
        }
    }
    if ativo_id() == id {
        define_ativo(ID_FABRICA)?;
    }
    Ok(())
}

/// Nome do arquivo para um perfil (usado pela interface).
pub fn existe(id: &str) -> bool {
    id == ID_FABRICA || Path::new(&dir_perfis().unwrap_or_default().join(id)).exists()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn slug_simples() {
        assert_eq!(slug("Meu Tema"), "meu-tema");
        assert_eq!(slug("  Corsa 2026! "), "corsa-2026");
        assert_eq!(slug("###"), "perfil");
    }

    #[test]
    fn fabrica_tem_tema_instalado() {
        let p = de_fabrica();
        assert_eq!(p.id, ID_FABRICA);
        if Path::new(TEMA_DE_FABRICA).exists() {
            assert!(caminho_tema(ID_FABRICA).is_some());
        }
    }

    #[test]
    fn fabrica_nao_aceita_gravacao() {
        assert!(grava_tema(ID_FABRICA, b"x", 1).is_err());
        assert!(apaga(ID_FABRICA).is_err());
    }
}
