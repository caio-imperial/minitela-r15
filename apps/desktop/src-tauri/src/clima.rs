//! Clima pela Open-Meteo (sem chave) — geocodifica a cidade e pega 3 dias.
//!
//! As tags que o app oficial usa (capturadas dos frames dele):
//!
//! ```text
//! cidade   2027  texto  "Linhares"
//! dia 1    2030  texto  "20°/30°"   (mín/máx de hoje)
//! dia 2    2031  texto  "20°/28°"
//! dia 3    2032  texto  "19°/30°"
//! rótulo 2 1119  texto  "TER 25"
//! rótulo 3 1124  texto  "QUA 26"
//! ```
//!
//! O rótulo do primeiro dia não é enviado: a página já traz "HOJE" fixo.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Dia {
    /// "TER 25" — usado só do segundo dia em diante
    pub rotulo: String,
    /// "20°/30°" (mín/máx)
    pub faixa: String,
    /// ícone do tema (medido na tela): 0 sol, 1 sol entre nuvens, 2 nuvem,
    /// 3 chuva, 4 lua, 5 lua entre nuvens, 6 nuvem com neve
    pub icone: u8,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Clima {
    pub cidade: String,
    pub dias: Vec<Dia>,
}

#[derive(Deserialize)]
struct Geo {
    results: Option<Vec<GeoItem>>,
}

#[derive(Deserialize)]
struct GeoItem {
    name: String,
    latitude: f64,
    longitude: f64,
}

#[derive(Deserialize)]
struct Previsao {
    daily: Diario,
}

#[derive(Deserialize)]
struct Diario {
    time: Vec<String>,
    temperature_2m_min: Vec<f64>,
    temperature_2m_max: Vec<f64>,
    weather_code: Vec<u16>,
}

fn baixa(url: &str) -> Result<String, String> {
    let resp = ureq::get(url)
        .timeout(std::time::Duration::from_secs(10))
        .call()
        .map_err(|e| format!("sem resposta de {url}: {e}"))?;
    resp.into_string()
        .map_err(|e| format!("resposta ilegivel: {e}"))
}

/// Dia da semana em português, três letras, como o tema desenha ("TER").
fn semana(data: &str) -> String {
    use chrono::{Datelike, NaiveDate};
    let Ok(d) = NaiveDate::parse_from_str(data, "%Y-%m-%d") else {
        return String::new();
    };
    let nome = match d.weekday() {
        chrono::Weekday::Mon => "SEG",
        chrono::Weekday::Tue => "TER",
        chrono::Weekday::Wed => "QUA",
        chrono::Weekday::Thu => "QUI",
        chrono::Weekday::Fri => "SEX",
        chrono::Weekday::Sat => "SAB",
        chrono::Weekday::Sun => "DOM",
    };
    format!("{nome} {}", d.day())
}

fn grau(v: f64) -> String {
    format!("{}°", v.round() as i32)
}

/// Geocodifica a cidade e monta os três dias.
pub fn busca(cidade: &str) -> Result<Clima, String> {
    let nome = cidade.trim();
    if nome.is_empty() {
        return Err("cidade vazia".into());
    }
    let geo_url = format!(
        "https://geocoding-api.open-meteo.com/v1/search?name={}&count=1&language=pt&format=json",
        url_escape(nome)
    );
    let geo: Geo = serde_json::from_str(&baixa(&geo_url)?)
        .map_err(|e| format!("geocodificacao invalida: {e}"))?;
    let lugar = geo
        .results
        .and_then(|mut r| r.drain(..).next())
        .ok_or_else(|| format!("nao achei a cidade \"{nome}\""))?;

    let prev_url = format!(
        "https://api.open-meteo.com/v1/forecast?latitude={}&longitude={}\
         &daily=temperature_2m_min,temperature_2m_max,weather_code\
         &timezone=auto&forecast_days=3",
        lugar.latitude, lugar.longitude
    );
    let prev: Previsao =
        serde_json::from_str(&baixa(&prev_url)?).map_err(|e| format!("previsao invalida: {e}"))?;

    let d = prev.daily;
    let n = d
        .time
        .len()
        .min(d.temperature_2m_min.len())
        .min(d.temperature_2m_max.len());
    if n == 0 {
        return Err("a previsao veio vazia".into());
    }
    let dias = (0..n)
        .map(|i| Dia {
            rotulo: semana(&d.time[i]),
            faixa: format!(
                "{}/{}",
                grau(d.temperature_2m_min[i]),
                grau(d.temperature_2m_max[i])
            ),
            icone: icone(d.weather_code.get(i).copied().unwrap_or(2)),
        })
        .collect();

    Ok(Clima {
        cidade: lugar.name,
        dias,
    })
}

/// Código WMO do Open-Meteo -> ícone do tema.
///
/// Ícones medidos na tela: 0 sol, 1 sol entre nuvens, 2 nuvem, 3 chuva, 4 lua,
/// 5 lua entre nuvens, 6 nuvem com neve. Não existe ícone de trovoada: cai na chuva.
pub fn icone(codigo: u16) -> u8 {
    match codigo {
        0 => 0,
        1 | 2 => 1,
        3 | 45 | 48 => 2,
        71 | 73 | 75 | 77 | 85 | 86 => 6,
        // 51..67 chuva/garoa, 80..82 pancadas, 95..99 trovoada
        _ => 3,
    }
}

fn url_escape(texto: &str) -> String {
    texto
        .bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                (b as char).to_string()
            }
            _ => format!("%{b:02X}"),
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn escapa_acento_e_espaco() {
        assert_eq!(url_escape("São Paulo"), "S%C3%A3o%20Paulo");
    }

    #[test]
    fn rotulo_do_dia_tem_semana_e_numero() {
        // 2026-11-25 e uma quarta-feira
        assert_eq!(semana("2026-11-25"), "QUA 25");
    }

    /// Rede de verdade: `cargo test --lib -- --ignored busca_de_verdade --nocapture`
    #[test]
    #[ignore]
    fn busca_de_verdade() {
        let c = busca("Linhares").expect("buscar");
        eprintln!("{}: {:?}", c.cidade, c.dias);
        assert!(!c.dias.is_empty());
    }

    #[test]
    fn codigos_do_tempo_viram_icones_do_tema() {
        assert_eq!(icone(0), 0, "limpo = sol");
        assert_eq!(icone(2), 1, "parcialmente nublado = sol entre nuvens");
        assert_eq!(icone(3), 2, "encoberto = nuvem");
        assert_eq!(icone(61), 3, "chuva");
        assert_eq!(icone(80), 3, "pancadas de chuva");
        assert_eq!(icone(95), 3, "trovoada cai na chuva");
        assert_eq!(icone(71), 6, "neve");
        assert_eq!(icone(86), 6, "pancadas de neve");
    }

    #[test]
    fn faixa_usa_min_barra_max() {
        assert_eq!(format!("{}/{}", grau(19.6), grau(30.4)), "20°/30°");
    }
}
