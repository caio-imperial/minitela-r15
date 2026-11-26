//! Protocolo AHMI sobre a porta serial — porte de `minitela_ctl.py`.
//!
//! Frame: `AH | CTRL(2) | CMD(2) | conteúdo | CRC(2) | MI`, com `CTRL` = tamanho do
//! que vem depois dele até o CRC. O app oficial nunca liga o CRC; o firmware o ignora.

use md5::{Digest, Md5};
use nix::poll::{PollFd, PollFlags, PollTimeout, poll};
use nix::sys::termios::{
    BaudRate, SetArg, cfmakeraw, cfsetispeed, cfsetospeed, tcgetattr, tcsetattr,
};
use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::os::fd::AsFd;
use std::path::PathBuf;
use std::time::{Duration, Instant};

pub const START: &[u8; 2] = b"AH";
pub const END: &[u8; 2] = b"MI";
pub const TEXTURE_ADDR: u32 = 0x0810_0000;
pub const TAG_PAGE: u16 = 2;
pub const TAG_BACKLIGHT: u16 = 7;

/// Registradores que este projeto realmente tem (`docs/referencia/tags.md`).
/// Escrever num id fora desta lista já deixou a tela muda: o firmware não tem
/// destino para ele. Antes de acrescentar um id aqui, ele precisa existir no
/// `tagList` do tema (não invente vizinhos do tipo 1080/1081/1084).
pub const REGISTRADORES: [u16; 26] = [
    2, 7, 65, 1082, 1083, 1085, 1090, 1110, 1115, 1119, 1120, 1124, 1140, 1141, 1150, 2000, 2001,
    2002, 2005, 2006, 2025, 2026, 2027, 2030, 2031, 2032,
];

fn confere(reg: u16) -> Result<(), Erro> {
    if REGISTRADORES.contains(&reg) {
        Ok(())
    } else {
        Err(Erro::Recusado(format!(
            "registrador {reg} nao existe neste tema (ver docs/referencia/tags.md)"
        )))
    }
}
pub const MAX_FILE: usize = 6436 * 1024;

pub const HANDSHAKE: u16 = 0x0080;
pub const HANDSHAKE_RESP: u16 = 0x00C0;
pub const GET_STATUS: u16 = 0x0085;
pub const GET_STATUS_RESP: u16 = 0x00C5;
pub const SWITCH_STATE: u16 = 0x0071;
pub const SWITCH_STATE_RESP: u16 = 0x00B1;
pub const REQUEST_DOWNLOAD: u16 = 0x0081;
pub const REQUEST_DOWNLOAD_RESP: u16 = 0x00C1;
pub const DOWNLOAD_DATA: u16 = 0x0082;
pub const DOWNLOAD_DATA_RESP: u16 = 0x00C2;
pub const DOWNLOAD_COMPLETE: u16 = 0x008F;
pub const DOWNLOAD_COMPLETE_RESP: u16 = 0x00CF;
pub const SET_REGISTER: u16 = 0x0090;
pub const SET_REGISTER_RESP: u16 = 0x00D0;

#[derive(Debug)]
pub enum Erro {
    Io(String),
    SemResposta(u16),
    Recusado(String),
    Nada,
}

impl std::fmt::Display for Erro {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Erro::Io(e) => write!(f, "porta serial: {e}"),
            Erro::SemResposta(c) => write!(f, "sem resposta ao comando {c:#06x}"),
            Erro::Recusado(e) => write!(f, "recusado: {e}"),
            Erro::Nada => write!(f, "nada a fazer"),
        }
    }
}

pub fn build_frame(cmd: u16, content: &[u8]) -> Vec<u8> {
    let len = 2 + content.len();
    let mut f = Vec::with_capacity(len + 8);
    f.extend_from_slice(START);
    f.extend_from_slice(&(len as u16).to_be_bytes());
    f.extend_from_slice(&cmd.to_be_bytes());
    f.extend_from_slice(content);
    f.extend_from_slice(&[0, 0]); // CRC desligado
    f.extend_from_slice(END);
    f
}

/// Extrai frames completos de `buf`, consumindo-os.
pub fn parse_frames(buf: &mut Vec<u8>) -> Vec<(u16, Vec<u8>)> {
    let mut out = Vec::new();
    loop {
        let Some(i) = buf.windows(2).position(|w| w == START) else {
            buf.clear();
            break;
        };
        if i > 0 {
            buf.drain(..i);
        }
        if buf.len() < 8 {
            break;
        }
        let data_len = (u16::from_be_bytes([buf[2], buf[3]]) & 0x7FFF) as usize;
        let total = data_len + 8;
        if buf.len() < total {
            break;
        }
        if &buf[total - 2..total] != END {
            buf.drain(..2);
            continue;
        }
        let cmd = u16::from_be_bytes([buf[4], buf[5]]);
        let payload = buf[6..6 + data_len - 2].to_vec();
        out.push((cmd, payload));
        buf.drain(..total);
    }
    out
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Status {
    pub status: u8,
    pub offset: u32,
}

pub fn parse_status(payload: &[u8]) -> Option<Status> {
    if payload.len() < 21 {
        return None;
    }
    Some(Status {
        status: payload[0],
        offset: u32::from_be_bytes([payload[17], payload[18], payload[19], payload[20]]),
    })
}

pub struct Porta {
    file: File,
    pub caminho: PathBuf,
    /// frames recebidos que chegaram junto com outro e ainda não foram consumidos
    buf: Vec<u8>,
}

impl Porta {
    pub fn abre(caminho: PathBuf) -> Result<Self, Erro> {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(&caminho)
            .map_err(|e| Erro::Io(format!("{}: {e}", caminho.display())))?;
        let mut t = tcgetattr(&file).map_err(|e| Erro::Io(e.to_string()))?;
        cfmakeraw(&mut t);
        cfsetispeed(&mut t, BaudRate::B115200).map_err(|e| Erro::Io(e.to_string()))?;
        cfsetospeed(&mut t, BaudRate::B115200).map_err(|e| Erro::Io(e.to_string()))?;
        tcsetattr(&file, SetArg::TCSANOW, &t).map_err(|e| Erro::Io(e.to_string()))?;
        Ok(Self {
            file,
            caminho,
            buf: Vec::new(),
        })
    }

    fn escreve(&mut self, dados: &[u8]) -> Result<(), Erro> {
        self.file
            .write_all(dados)
            .map_err(|e| Erro::Io(e.to_string()))
    }

    /// Lê até `dur`, mas devolve assim que tiver um frame completo.
    ///
    /// O que sobra no buffer **fica** para a próxima chamada: o firmware manda dois
    /// `C1` seguidos no erase (0xFFFFFFFF e depois 0) e, se vierem no mesmo pacote,
    /// descartar o resto faz o download travar esperando o segundo.
    fn le(&mut self, dur: Duration) -> Vec<(u16, Vec<u8>)> {
        let mut chunk = [0u8; 4096];
        let fim = Instant::now() + dur;
        loop {
            let frames = parse_frames(&mut self.buf);
            if !frames.is_empty() {
                return frames;
            }
            if Instant::now() >= fim {
                return Vec::new();
            }
            let restante = fim.saturating_duration_since(Instant::now());
            let ms = restante.as_millis().min(50) as u16;
            let pronto = {
                let mut fds = [PollFd::new(self.file.as_fd(), PollFlags::POLLIN)];
                let _ = poll(&mut fds, PollTimeout::from(ms.max(1)));
                fds[0]
                    .revents()
                    .unwrap_or(PollFlags::empty())
                    .contains(PollFlags::POLLIN)
            };
            if pronto {
                match self.file.read(&mut chunk) {
                    Ok(0) | Err(_) => return Vec::new(),
                    Ok(n) => self.buf.extend_from_slice(&chunk[..n]),
                }
            }
        }
    }

    pub fn request(
        &mut self,
        cmd: u16,
        content: &[u8],
        expect: Option<u16>,
        timeout: Duration,
        tentativas: usize,
    ) -> Result<Vec<u8>, Erro> {
        for _ in 0..tentativas {
            self.escreve(&build_frame(cmd, content))?;
            let Some(expect) = expect else {
                return Ok(Vec::new());
            };
            let limite = Instant::now() + timeout;
            while Instant::now() < limite {
                for (c, p) in self.le(Duration::from_millis(200)) {
                    if c == expect {
                        return Ok(p);
                    }
                }
            }
        }
        Err(Erro::SemResposta(expect.unwrap_or(cmd)))
    }

    pub fn handshake(&mut self) -> Result<u32, Erro> {
        let p = self.request(
            HANDSHAKE,
            &[],
            Some(HANDSHAKE_RESP),
            Duration::from_secs(2),
            5,
        )?;
        if p.len() < 4 {
            return Err(Erro::Recusado("handshake curto".into()));
        }
        Ok(u32::from_be_bytes([p[0], p[1], p[2], p[3]]))
    }

    pub fn status(&mut self) -> Result<Status, Erro> {
        let p = self.request(
            GET_STATUS,
            &[],
            Some(GET_STATUS_RESP),
            Duration::from_secs(2),
            5,
        )?;
        parse_status(&p).ok_or(Erro::Recusado("status curto".into()))
    }

    /// Envia e espera um ACK curto; **não falha** se o firmware não responder.
    /// É o comportamento do `minitela_tags.py` (o app oficial também não espera).
    fn envia_sem_ack(&mut self, cmd: u16, content: &[u8], espera: Duration) -> Result<(), Erro> {
        self.escreve(&build_frame(cmd, content))?;
        let _ = self.le(espera);
        Ok(())
    }

    pub fn set_registradores(&mut self, pares: &[(u16, u32)]) -> Result<(), Erro> {
        for (reg, _) in pares {
            confere(*reg)?;
        }
        let mut content = vec![(0b1000 << 4) | ((pares.len() as u8 - 1) & 0x0F)];
        for (reg, val) in pares {
            content.extend_from_slice(&reg.to_be_bytes());
            content.extend_from_slice(&val.to_be_bytes());
        }
        self.envia_sem_ack(SET_REGISTER, &content, Duration::from_millis(300))
    }

    /// Escreve uma tag de texto (`0x0090` com cabeçalho `0xD0`).
    pub fn set_texto(&mut self, reg: u16, texto: &str) -> Result<(), Erro> {
        confere(reg)?;
        let bytes = texto.as_bytes();
        let mut content = Vec::with_capacity(5 + bytes.len());
        content.push(0xD0);
        content.extend_from_slice(&reg.to_be_bytes());
        content.extend_from_slice(&(bytes.len() as u16).to_be_bytes());
        content.extend_from_slice(bytes);
        self.envia_sem_ack(SET_REGISTER, &content, Duration::from_millis(300))
    }

    pub fn pagina(&mut self, n: u32) -> Result<(), Erro> {
        self.set_registradores(&[(TAG_PAGE, n)])
    }

    pub fn brilho(&mut self, n: u32) -> Result<(), Erro> {
        self.set_registradores(&[(TAG_BACKLIGHT, n.clamp(0, 100))])
    }

    /// Grava um `.acf` na região de textura, seguindo o fluxo do app oficial.
    pub fn envia_textura(
        &mut self,
        dados: &[u8],
        mut progresso: impl FnMut(u8),
    ) -> Result<(), Erro> {
        if dados.len() > MAX_FILE {
            return Err(Erro::Recusado(format!(
                "arquivo grande demais: {} > {MAX_FILE}",
                dados.len()
            )));
        }
        let digest = Md5::digest(dados);
        let md5: String = digest.iter().map(|b| format!("{b:02x}")).collect();

        self.handshake()?;
        let st = self.status()?;
        let mut offset = 0u32;
        match st.status {
            0x10 | 0x11 => {} // já em download: recomeça do zero
            0x20 => {
                let r = self.request(
                    SWITCH_STATE,
                    &[0x10],
                    Some(SWITCH_STATE_RESP),
                    Duration::from_secs(5),
                    1,
                )?;
                if r.len() >= 4 && u32::from_be_bytes([r[0], r[1], r[2], r[3]]) != 0 {
                    return Err(Erro::Recusado("nao entrou em modo download".into()));
                }
            }
            outro => return Err(Erro::Recusado(format!("estado inesperado: {outro:#04x}"))),
        }

        let mut req = Vec::new();
        req.extend_from_slice(&TEXTURE_ADDR.to_be_bytes());
        req.extend_from_slice(&(dados.len() as u32).to_be_bytes());
        req.extend_from_slice(&hex_bytes(&md5));

        let resp = self.request(
            REQUEST_DOWNLOAD,
            &req,
            Some(REQUEST_DOWNLOAD_RESP),
            Duration::from_secs(60),
            1,
        )?;
        let (mut max_page, mut code) = par_u32u32(&resp);
        if code == 0xFFFF_FFFF {
            // o chip está apagando a flash: o segundo C1 traz code=0
            let limite = Instant::now() + Duration::from_secs(60);
            while Instant::now() < limite {
                for (c, p) in self.le(Duration::from_millis(100)) {
                    if c == REQUEST_DOWNLOAD_RESP && p.len() >= 8 {
                        max_page = u32::from_be_bytes([p[0], p[1], p[2], p[3]]);
                        code = u32::from_be_bytes([p[4], p[5], p[6], p[7]]);
                        if code == 0 {
                            break;
                        }
                    }
                }
                if code == 0 {
                    break;
                }
            }
        }
        if code != 0 {
            return Err(Erro::Recusado(format!("REQUEST_DOWNLOAD code={code:#x}")));
        }
        let page = max_page.max(1) as usize;

        while (offset as usize) < dados.len() {
            let fim = ((offset as usize) + page).min(dados.len());
            let mut content = Vec::with_capacity(4 + fim - offset as usize);
            content.extend_from_slice(&offset.to_be_bytes());
            content.extend_from_slice(&dados[offset as usize..fim]);
            let resp = self.request(
                DOWNLOAD_DATA,
                &content,
                Some(DOWNLOAD_DATA_RESP),
                Duration::from_secs(5),
                5,
            )?;
            let code = if resp.len() >= 4 {
                u32::from_be_bytes([resp[0], resp[1], resp[2], resp[3]])
            } else {
                0
            };
            if code == 0xFFFF_FFFF {
                let limite = Instant::now() + Duration::from_secs(60);
                while Instant::now() < limite {
                    let mut ok = false;
                    for (c, p) in self.le(Duration::from_millis(100)) {
                        if c == DOWNLOAD_DATA_RESP
                            && p.len() >= 4
                            && u32::from_be_bytes([p[0], p[1], p[2], p[3]]) == 0
                        {
                            ok = true;
                        }
                    }
                    if ok {
                        break;
                    }
                }
            } else if code != 0 {
                continue; // reenvia a mesma página
            }
            offset = fim as u32;
            progresso(((offset as usize * 100) / dados.len()) as u8);
        }

        let _ = self.request(
            DOWNLOAD_COMPLETE,
            &[],
            Some(DOWNLOAD_COMPLETE_RESP),
            Duration::from_secs(5),
            1,
        );
        Ok(())
    }
}

fn par_u32u32(p: &[u8]) -> (u32, u32) {
    if p.len() < 8 {
        return (0, 0);
    }
    (
        u32::from_be_bytes([p[0], p[1], p[2], p[3]]),
        u32::from_be_bytes([p[4], p[5], p[6], p[7]]),
    )
}

fn hex_bytes(s: &str) -> Vec<u8> {
    (0..s.len() / 2)
        .filter_map(|i| u8::from_str_radix(&s[i * 2..i * 2 + 2], 16).ok())
        .collect()
}

/// Porta mais recente em `/dev/ttyACM*` (o nó sobe a cada reenumeração).
pub fn encontra_porta() -> Option<PathBuf> {
    let mut candidatos: Vec<(std::time::SystemTime, PathBuf)> = std::fs::read_dir("/dev")
        .ok()?
        .flatten()
        .filter(|e| e.file_name().to_string_lossy().starts_with("ttyACM"))
        .filter_map(|e| {
            let meta = e.metadata().ok()?;
            Some((meta.modified().ok()?, e.path()))
        })
        .collect();
    candidatos.sort();
    candidatos.pop().map(|(_, p)| p)
}

/// O app oficial está rodando? (varre `/proc/*/comm`)
pub fn app_oficial_rodando() -> bool {
    let Ok(entradas) = std::fs::read_dir("/proc") else {
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
        if let Ok(comm) = std::fs::read_to_string(e.path().join("comm"))
            && comm.trim() == "minitela"
        {
            return true;
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn frame_de_handshake() {
        let f = build_frame(HANDSHAKE, &[]);
        assert_eq!(
            f,
            vec![b'A', b'H', 0x00, 0x02, 0x00, 0x80, 0x00, 0x00, b'M', b'I']
        );
    }

    #[test]
    fn frame_com_conteudo() {
        let f = build_frame(SET_REGISTER, &[0x80, 0x00, 0x02, 0x00, 0x00, 0x00, 0x05]);
        // len = 2 + 7 = 9
        assert_eq!(&f[2..4], &[0x00, 0x09]);
        assert_eq!(f.len(), 9 + 8);
        assert_eq!(&f[f.len() - 2..], b"MI");
    }

    #[test]
    fn parse_de_dois_frames_juntos() {
        let mut buf = build_frame(HANDSHAKE_RESP, &1024u32.to_be_bytes());
        buf.extend(build_frame(GET_STATUS_RESP, &[0x20]));
        let frames = parse_frames(&mut buf);
        assert_eq!(frames.len(), 2);
        assert_eq!(frames[0].0, HANDSHAKE_RESP);
        assert_eq!(
            u32::from_be_bytes([
                frames[0].1[0],
                frames[0].1[1],
                frames[0].1[2],
                frames[0].1[3]
            ]),
            1024
        );
        assert_eq!(frames[1].0, GET_STATUS_RESP);
        assert!(buf.is_empty());
    }

    #[test]
    fn parse_ignora_lixo_antes() {
        let mut buf = vec![0xFF, 0x00, 0x13];
        buf.extend(build_frame(GET_STATUS_RESP, &[0x10]));
        let frames = parse_frames(&mut buf);
        assert_eq!(frames.len(), 1);
        assert_eq!(frames[0].1, vec![0x10]);
    }

    #[test]
    fn status_decodifica_offset() {
        let mut p = vec![0x20];
        p.extend_from_slice(&[0u8; 16]); // fileId
        p.extend_from_slice(&1234u32.to_be_bytes());
        let s = parse_status(&p).expect("status");
        assert_eq!(s.status, 0x20);
        assert_eq!(s.offset, 1234);
    }

    /// Grava de verdade na tela. Rode com:
    ///   MINITELA_ACF=<arquivo.acf> cargo test -- --ignored grava_na_tela
    /// (o app oficial precisa estar parado)
    #[test]
    #[ignore]
    fn grava_na_tela() {
        let caminho = std::env::var("MINITELA_ACF").expect("defina MINITELA_ACF");
        let dados = std::fs::read(&caminho).expect("ler acf");
        assert!(!app_oficial_rodando(), "pare o app oficial antes");
        let porta = encontra_porta().expect("nenhuma /dev/ttyACM*");
        let mut p = Porta::abre(porta).expect("abrir porta");
        let mut ultimo = 0u8;
        p.envia_textura(&dados, |pct| {
            if pct / 25 != ultimo / 25 {
                ultimo = pct;
                eprintln!("  {pct}%");
            }
        })
        .expect("enviar textura");
    }

    #[test]
    fn registrador_desconhecido_e_recusado() {
        assert!(confere(1081).is_err(), "1081 nao existe no tema");
        assert!(
            confere(1084).is_err(),
            "1084 (wifi_sinal) nao existe no tema"
        );
        assert!(confere(1082).is_ok(), "bateria");
        assert!(confere(2006).is_ok(), "relogio");
    }

    #[test]
    fn lista_de_registradores_tem_os_que_usamos() {
        for id in [TAG_PAGE, TAG_BACKLIGHT] {
            assert!(REGISTRADORES.contains(&id), "{id} precisa estar na lista");
        }
    }

    /// Frame capturado do app oficial (só o CRC dele é 0xE2CB; mandamos 0x0000).
    #[test]
    fn frame_da_bateria_bate_com_o_app_oficial() {
        let official = [
            0x41, 0x48, 0x00, 0x0B, 0x00, 0x90, 0xD0, 0x04, 0x3A, 0x00, 0x04, b'1', b'0', b'0',
            b'%', 0xE2, 0xCB, 0x4D, 0x49,
        ];
        let nosso = build_frame(
            SET_REGISTER,
            &[0xD0, 0x04, 0x3A, 0x00, 0x04, b'1', b'0', b'0', b'%'],
        );
        assert_eq!(&nosso[..15], &official[..15], "cabecalho e conteudo");
        assert_eq!(&nosso[15..17], &[0x00, 0x00], "crc desligado");
        assert_eq!(nosso[17..], official[17..], "fim do frame");
    }

    #[test]
    fn hex_do_md5() {
        assert_eq!(hex_bytes("00ff10"), vec![0x00, 0xFF, 0x10]);
        assert_eq!(hex_bytes(""), Vec::<u8>::new());
    }
}
