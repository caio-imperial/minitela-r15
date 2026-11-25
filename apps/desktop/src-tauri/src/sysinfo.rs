//! Dados do sistema para as tags — porte de `minitela_tags.py`.
//!
//! Lê só o que o Linux expõe em `/sys` e `/proc`; sem dependências de sistema.

use std::sync::Mutex;
use std::time::Instant;

pub const TAG_CPU: u16 = 1080;
pub const TAG_BATERIA: u16 = 1082;
pub const TAG_WIFI_SSID: u16 = 1083;
pub const TAG_WIFI_SINAL: u16 = 1084;
pub const TAG_BATERIA_TIPO: u16 = 1150;
pub const TAG_RELOGIO: u16 = 2006;

/// Amostra de CPU entre duas leituras de `/proc/stat`.
#[derive(Default)]
pub struct Coletor {
    anterior: Mutex<Option<(Instant, u64, u64)>>, // (quando, total, ocioso)
}

fn le_u64(caminho: &std::path::Path) -> Option<u64> {
    std::fs::read_to_string(caminho).ok()?.trim().parse().ok()
}

/// (capacidade %, se está carregando (1) / descarregando (0) / desconhecido (2))
pub fn bateria() -> Option<(u32, u8)> {
    let base = std::path::Path::new("/sys/class/power_supply");
    for e in std::fs::read_dir(base).ok()?.flatten() {
        let dir = e.path();
        let tipo = std::fs::read_to_string(dir.join("type")).ok()?;
        if tipo.trim() != "Battery" {
            continue;
        }
        let capacidade = le_u64(&dir.join("capacity"))? as u32;
        let estado = std::fs::read_to_string(dir.join("status"))
            .map(|s| match s.trim() {
                "Charging" | "Full" => 1u8,
                "Discharging" => 0,
                _ => 2,
            })
            .unwrap_or(2);
        return Some((capacidade, estado));
    }
    None
}

/// Percentual de CPU desde a última chamada (a primeira devolve `None`).
pub fn cpu(col: &Coletor) -> Option<u8> {
    let texto = std::fs::read_to_string("/proc/stat").ok()?;
    let linha = texto.lines().find(|l| l.starts_with("cpu "))?;
    let campos: Vec<u64> = linha
        .split_whitespace()
        .skip(1)
        .filter_map(|c| c.parse().ok())
        .collect();
    if campos.len() < 4 {
        return None;
    }
    let ocioso = campos[3] + campos.get(4).copied().unwrap_or(0);
    let total: u64 = campos.iter().sum();
    let agora = Instant::now();

    let mut guarda = col.anterior.lock().ok()?;
    let resultado = guarda.map(|(_, t0, o0)| {
        let dt = total.saturating_sub(t0);
        let di = ocioso.saturating_sub(o0);
        (dt.saturating_sub(di))
            .saturating_mul(100)
            .checked_div(dt)
            .unwrap_or(0) as u8
    });
    *guarda = Some((agora, total, ocioso));
    resultado
}

/// SSID (`iwgetid`) e sinal (link quality do `/proc/net/wireless`).
pub fn wifi() -> (Option<String>, Option<u8>) {
    let ssid = std::process::Command::new("iwgetid")
        .arg("-r")
        .output()
        .ok()
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
        .filter(|s| !s.is_empty());

    let sinal = std::fs::read_to_string("/proc/net/wireless")
        .ok()
        .and_then(|t| {
            t.lines()
                .nth(2)
                .and_then(|l| l.split(':').nth(1))
                .and_then(|resto| {
                    resto.split_whitespace().nth(1).and_then(|q| {
                        let q: f32 = q.trim_end_matches('.').parse().ok()?;
                        Some((q.clamp(0.0, 100.0)) as u8)
                    })
                })
        });
    (ssid, sinal)
}

pub fn relogio() -> String {
    chrono::Local::now().format("%d/%m %H:%M").to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn relogio_tem_formato_curto() {
        let r = relogio();
        assert_eq!(r.len(), 11, "{r}");
        assert_eq!(&r[2..3], "/");
        assert_eq!(&r[5..6], " ");
        assert_eq!(&r[8..9], ":");
    }

    #[test]
    fn bateria_plausivel_ou_ausente() {
        if let Some((pct, estado)) = bateria() {
            assert!(pct <= 100);
            assert!(estado <= 2);
        }
    }

    #[test]
    fn cpu_precisa_de_duas_amostras() {
        let col = Coletor::default();
        assert!(cpu(&col).is_none(), "primeira amostra nao tem delta");
    }
}
