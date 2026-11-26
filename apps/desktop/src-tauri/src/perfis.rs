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

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Perfil {
    pub id: String,
    pub nome: String,
    pub pagina: u32,
    /// `None` = perfil de fábrica (usa o tema instalado)
    pub arquivo: Option<String>,
    pub atualizado: Option<String>,
}

fn home() -> Option<PathBuf> {
    std::env::var_os("HOME").map(PathBuf::from)
}

pub fn dir_perfis() -> Option<PathBuf> {
    Some(home()?.join(".local/share/minitela-custom/perfis"))
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
    let p = Perfil {
        id,
        nome: nome.to_string(),
        pagina: 5,
        arquivo: None,
        atualizado: None,
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
        });
    p.arquivo = Some(caminho.display().to_string());
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
