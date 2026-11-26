//! Dados do sistema para as tags — porte de `minitela_tags.py`.
//!
//! Lê só o que o Linux expõe em `/sys` e `/proc`; sem dependências de sistema.

use std::sync::Mutex;
use std::time::Instant;

// Só registradores que existem no tagList deste projeto (`docs/referencia/tags.md`).
// NÃO invente ids "vizinhos" (1080, 1081, 1084): o firmware não tem destino para eles
// e já travou a tela mandando 1081. Ids de texto também ficam de fora daqui.
// evidência dos frames do app oficial (capturados):
//   1082 -> texto "100%"   |  1083 -> texto "1310-5G"  |  1085 -> texto "Desconectado"
//   2006 -> texto "25/11 22:14"  |  7 -> número (brilho)
// 1150 (bateria_tipo) o app oficial NAO manda.
pub const TAG_BATERIA: u16 = 1082;
/// nível da barra do ícone: 0..3 desenha 1..4 pauzinhos (medido na tela)
pub const TAG_BATERIA_NIVEL: u16 = 1150;
pub const TAG_WIFI_SSID: u16 = 1083;
pub const TAG_BT_NOME: u16 = 1085;
pub const TAG_RELOGIO: u16 = 2006;
// clima (tela do Clima) — frames capturados do app oficial
pub const TAG_CIDADE: u16 = 2027;
pub const TAG_DIA1: u16 = 2030;
pub const TAG_DIA2: u16 = 2031;
pub const TAG_DIA3: u16 = 2032;
pub const TAG_ROTULO2: u16 = 1119;
pub const TAG_ROTULO3: u16 = 1124;

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

/// Nome do aparelho Bluetooth conectado, se houver (`bluetoothctl`).
pub fn bluetooth() -> Option<String> {
    let saida = std::process::Command::new("bluetoothctl")
        .args(["devices", "Connected"])
        .output()
        .ok()?;
    let texto = String::from_utf8_lossy(&saida.stdout);
    for linha in texto.lines() {
        // "Device AA:BB:CC:DD:EE:FF Nome do aparelho"
        let mut partes = linha.trim().splitn(3, ' ');
        if partes.next() != Some("Device") {
            continue;
        }
        partes.next()?; // endereço
        if let Some(nome) = partes.next()
            && !nome.trim().is_empty()
        {
            return Some(nome.trim().to_string());
        }
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
/// SSID da rede conectada.
///
/// `iwgetid` não vem instalado por padrão; o NetworkManager (`nmcli`) vem. A saída
/// do nmcli com `-t` é `ATIVO:SSID` no idioma do sistema (`sim:`/`yes:`).
pub fn wifi() -> Option<String> {
    let saida = std::process::Command::new("nmcli")
        .args(["-t", "-f", "ACTIVE,SSID", "dev", "wifi"])
        .output()
        .ok()?;
    for linha in String::from_utf8_lossy(&saida.stdout).lines() {
        let mut partes = linha.splitn(2, ':');
        let ativo = partes.next().unwrap_or("").trim();
        let ssid = partes.next().unwrap_or("").trim();
        if !ssid.is_empty() && (ativo == "yes" || ativo == "sim") {
            return Some(ssid.to_string());
        }
    }
    // reserva: se o nmcli não existir, tenta o iwgetid
    let saida = std::process::Command::new("iwgetid")
        .arg("-r")
        .output()
        .ok()?;
    let ssid = String::from_utf8_lossy(&saida.stdout).trim().to_string();
    (!ssid.is_empty()).then_some(ssid)
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
