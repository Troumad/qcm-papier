//! Application de bureau QCM-Papier.
//!
//! Tauri ne sert que d'enveloppe : il lance le serveur Python local
//! (`qcm-papier serve`) sur un port libre, attend qu'il réponde, puis ouvre
//! une fenêtre sur l'interface web. Toute la logique reste en Python.
//!
//! Commande du serveur :
//! - `QCM_PAPIER_SERVER` : exécutable autonome du serveur (ex. construit avec
//!   PyInstaller), lancé avec les arguments de `serve` ;
//! - sinon `QCM_PAPIER_PYTHON` (défaut `python3`, ou `python` sous Windows)
//!   avec `-m qcm_papier serve`.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::{TcpListener, TcpStream};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::thread::sleep;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

struct Server(Mutex<Option<Child>>);

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|listener| listener.local_addr())
        .map(|addr| addr.port())
        .expect("aucun port local disponible")
}

fn spawn_server(port: u16) -> std::io::Result<Child> {
    let port = port.to_string();
    // --exit-with-parent : le serveur s'arrête même si l'application est tuée
    // sans passer par la fermeture normale de la fenêtre.
    let serve_args = ["serve", "--no-browser", "--exit-with-parent", "--port", port.as_str()];
    if let Ok(server) = std::env::var("QCM_PAPIER_SERVER") {
        return Command::new(server).args(serve_args).spawn();
    }
    let default_python = if cfg!(windows) { "python" } else { "python3" };
    let python = std::env::var("QCM_PAPIER_PYTHON").unwrap_or_else(|_| default_python.to_string());
    Command::new(python).args(["-m", "qcm_papier"]).args(serve_args).spawn()
}

fn wait_for_server(port: u16, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
        }
        sleep(Duration::from_millis(100));
    }
    false
}

fn main() {
    let port = free_port();
    let child = spawn_server(port).unwrap_or_else(|error| {
        eprintln!("Impossible de lancer le serveur Python : {error}");
        std::process::exit(1);
    });

    let app = tauri::Builder::default()
        .manage(Server(Mutex::new(Some(child))))
        .setup(move |app| {
            if !wait_for_server(port, Duration::from_secs(30)) {
                return Err("le serveur Python n'a pas démarré (qcm-papier est-il installé avec l'extra web ?)".into());
            }
            let url = format!("http://127.0.0.1:{port}/").parse()?;
            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
                .title("QCM-Papier")
                .inner_size(1280.0, 860.0)
                .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("erreur au démarrage de l'application");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(mut child) = handle.state::<Server>().0.lock().unwrap().take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    });
}
