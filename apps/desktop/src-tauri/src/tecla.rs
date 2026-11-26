//! Tecla "mini tela" do notebook (KEY_PROG1) — quem trata é o app que está no controle.
//!
//! O app oficial abre os `/dev/input/event*` e escuta `KEY_PROG1` (keycode 148); sem
//! ninguém escutando, apertar a tecla não faz nada. Aqui a tecla troca a página exibida,
//! pulando as que o usuário desativou na interface.
//!
//! Leitura só: os dispositivos são `crw-rw-rw-` nesta máquina, então não precisa root.

use std::io::Read;

pub const KEY_PROG1: u16 = 148;
const EV_KEY: u16 = 1;
const EV_SYN: u16 = 0;

/// Um `input_event` no x86_64: `timeval` (16 B) + type(u16) + code(u16) + value(i32).
const TAMANHO_EVENTO: usize = 24;

fn inteiro(bytes: &[u8]) -> u16 {
    u16::from_ne_bytes([bytes[0], bytes[1]])
}

fn valor(bytes: &[u8]) -> i32 {
    i32::from_ne_bytes([bytes[0], bytes[1], bytes[2], bytes[3]])
}

/// Dispositivos de entrada legíveis (teclados dão `KEY_PROG1`).
fn dispositivos() -> Vec<std::path::PathBuf> {
    let Ok(entradas) = std::fs::read_dir("/dev/input") else {
        return Vec::new();
    };
    let mut lista: Vec<_> = entradas
        .flatten()
        .map(|e| e.path())
        .filter(|p| {
            p.file_name()
                .map(|n| n.to_string_lossy().starts_with("event"))
                .unwrap_or(false)
        })
        .collect();
    lista.sort();
    lista
}

/// Escuta a tecla em todos os dispositivos; `ao_apertar` roda na thread de leitura.
///
/// Devolve quando `seguir()` devolver `false` (o app saiu do controle).
pub fn escuta(mut seguir: impl FnMut() -> bool, mut ao_apertar: impl FnMut()) {
    let mut fds: Vec<(std::fs::File, Vec<u8>)> = Vec::new();
    for caminho in dispositivos() {
        if let Ok(arq) = std::fs::File::open(&caminho) {
            fds.push((arq, Vec::new()));
        }
    }
    if fds.is_empty() {
        return;
    }
    // leitura bloqueante por dispositivo ficaria presa num só; usa uma thread por
    // dispositivo e um canal para o evento
    let (envia, recebe) = std::sync::mpsc::channel::<()>();
    for (arq, _) in fds {
        let envia = envia.clone();
        std::thread::spawn(move || {
            let mut arq = arq;
            let mut buf = [0u8; TAMANHO_EVENTO * 64];
            loop {
                match arq.read(&mut buf) {
                    Ok(0) | Err(_) => return,
                    Ok(n) => {
                        let (eventos, _) = buf[..n].as_chunks::<TAMANHO_EVENTO>();
                        for pedaco in eventos {
                            let tipo = inteiro(&pedaco[16..18]);
                            let codigo = inteiro(&pedaco[18..20]);
                            let v = valor(&pedaco[20..24]);
                            if tipo == EV_KEY && codigo == KEY_PROG1 && v == 1 {
                                let _ = envia.send(());
                            } else if tipo == EV_SYN {
                                // fim de um pacote; nada a fazer
                            }
                        }
                    }
                }
            }
        });
    }
    // o laço principal só consome os eventos e respeita o "seguir"
    while seguir() {
        match recebe.recv_timeout(std::time::Duration::from_millis(200)) {
            Ok(()) => {
                ao_apertar();
                // drena apertos repetidos do mesmo gesto
                while recebe.try_recv().is_ok() {}
            }
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {}
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => return,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn le_evento_de_tecla() {
        // um EV_KEY/KEY_PROG1/press, como o kernel entrega
        let mut ev = [0u8; TAMANHO_EVENTO];
        ev[16..18].copy_from_slice(&EV_KEY.to_ne_bytes());
        ev[18..20].copy_from_slice(&KEY_PROG1.to_ne_bytes());
        ev[20..24].copy_from_slice(&1i32.to_ne_bytes());
        assert_eq!(inteiro(&ev[16..18]), EV_KEY);
        assert_eq!(inteiro(&ev[18..20]), KEY_PROG1);
        assert_eq!(valor(&ev[20..24]), 1);
    }
}
