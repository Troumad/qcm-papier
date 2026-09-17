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

use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};

use std::net::{TcpListener, TcpStream};
use std::process::{Child, Command};
use std::sync::Mutex;
use std::thread::sleep;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

struct Server(Mutex<Option<Child>>);

struct Desktop {
    port: u16,
    project_path: Mutex<Option<PathBuf>>,
    pending_path: Mutex<Option<PathBuf>>,
    ready: AtomicBool,
    exiting: AtomicBool,
}

fn validate_window(window: &tauri::WebviewWindow, state: &Desktop) -> Result<(), String> {
    let url = window.url().map_err(|e| e.to_string())?;
    if window.label() != "main"
        || url.scheme() != "http"
        || url.host_str() != Some("127.0.0.1")
        || url.port() != Some(state.port)
    {
        return Err("Commande réservée à la fenêtre QCM-Papier.".into());
    }
    Ok(())
}

#[tauri::command]
async fn save_document(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Desktop>,
    data: Vec<u8>,
    name: String,
    project: bool,
    save_as: bool,
) -> Result<Option<String>, String> {
    validate_window(&window, &state)?;
    let project_path = state
        .project_path
        .lock()
        .map_err(|e| e.to_string())?
        .clone();
    let previous = if project && !save_as {
        project_path.clone()
    } else {
        None
    };
    let target = if let Some(path) = previous {
        path
    } else {
        let safe_name = name.rsplit(['/', '\\']).next().unwrap_or("document");
        let mut dialog = rfd::AsyncFileDialog::new().set_file_name(safe_name);
        // Les dialogues système peuvent retenir un dossier utilisé par une autre
        // application. Toujours repartir du projet courant pour chaque export.
        if let Some(directory) = project_path.as_deref().and_then(|path| path.parent()) {
            dialog = dialog.set_directory(directory);
        }
        if project {
            dialog = dialog.add_filter("Projet QCM", &["json"]);
        }
        let Some(file) = dialog.save_file().await else {
            return Ok(None);
        };
        file.path().to_path_buf()
    };
    // Écriture atomique : une interruption ne tronque pas le fichier existant.
    let parent = target.parent().ok_or("Dossier de sauvegarde invalide")?;
    let mut temp = tempfile::NamedTempFile::new_in(parent).map_err(|e| e.to_string())?;
    temp.write_all(&data).map_err(|e| e.to_string())?;
    temp.as_file().sync_all().map_err(|e| e.to_string())?;
    temp.persist(&target).map_err(|e| e.to_string())?;
    if project {
        *state.project_path.lock().map_err(|e| e.to_string())? = Some(target.clone());
    }
    Ok(Some(target.to_string_lossy().into_owned()))
}

#[tauri::command]
async fn open_document(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Desktop>,
) -> Result<Option<(String, String)>, String> {
    validate_window(&window, &state)?;
    let Some(file) = rfd::AsyncFileDialog::new()
        .add_filter("Projet QCM", &["json"])
        .pick_file()
        .await
    else {
        return Ok(None);
    };
    let content = std::fs::read_to_string(file.path()).map_err(|e| e.to_string())?;
    *state.pending_path.lock().map_err(|e| e.to_string())? = Some(file.path().to_path_buf());
    Ok(Some((file.file_name(), content)))
}

#[tauri::command]
fn accept_document(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Desktop>,
) -> Result<Option<String>, String> {
    validate_window(&window, &state)?;
    let path = state.pending_path.lock().map_err(|e| e.to_string())?.take();
    let name = path.as_ref().map(|p| p.to_string_lossy().into_owned());
    *state.project_path.lock().map_err(|e| e.to_string())? = path;
    Ok(name)
}

#[tauri::command]
fn reset_document(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Desktop>,
) -> Result<(), String> {
    validate_window(&window, &state)?;
    *state.project_path.lock().map_err(|e| e.to_string())? = None;
    Ok(())
}

#[tauri::command]
fn desktop_ready(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Desktop>,
) -> Result<(), String> {
    validate_window(&window, &state)?;
    state.ready.store(true, Ordering::SeqCst);
    Ok(())
}

#[tauri::command]
fn close_document(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, Desktop>,
) -> Result<(), String> {
    validate_window(&window, &state)?;
    state.exiting.store(true, Ordering::SeqCst);
    window.app_handle().exit(0);
    Ok(())
}

fn ask_close(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.eval("window.dispatchEvent(new Event('qcm-close-requested'))");
    }
}

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|listener| listener.local_addr())
        .map(|addr| addr.port())
        .expect("aucun port local disponible")
}

fn spawn_server(port: u16, project: Option<&std::path::Path>) -> std::io::Result<Child> {
    let port = port.to_string();
    // --exit-with-parent : le serveur s'arrête même si l'application est tuée
    // sans passer par la fermeture normale de la fenêtre.
    let serve_args = [
        "serve",
        "--no-browser",
        "--exit-with-parent",
        "--port",
        port.as_str(),
    ];
    let mut command = if let Ok(server) = std::env::var("QCM_PAPIER_SERVER") {
        Command::new(server)
    } else {
        let default_python = if cfg!(windows) { "python" } else { "python3" };
        let python =
            std::env::var("QCM_PAPIER_PYTHON").unwrap_or_else(|_| default_python.to_string());
        let mut command = Command::new(python);
        command.args(["-m", "qcm_papier"]);
        command
    };
    command.args(serve_args);
    if let Some(path) = project {
        command.arg("--project").arg(path);
    }
    command.spawn()
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
    let project_path = std::env::var_os("QCM_PAPIER_PROJECT")
        .filter(|path| !path.is_empty())
        .map(|path| std::fs::canonicalize(PathBuf::from(path)))
        .transpose()
        .unwrap_or_else(|error| {
            eprintln!("Projet introuvable : {error}");
            std::process::exit(1);
        });
    let child = spawn_server(port, project_path.as_deref()).unwrap_or_else(|error| {
        eprintln!("Impossible de lancer le serveur Python : {error}");
        std::process::exit(1);
    });

    let app = tauri::Builder::default()
        .manage(Server(Mutex::new(Some(child))))
        .manage(Desktop { port, project_path: Mutex::new(project_path), pending_path: Mutex::new(None), ready: AtomicBool::new(false), exiting: AtomicBool::new(false) })
        .invoke_handler(tauri::generate_handler![save_document, reset_document, close_document, desktop_ready, open_document, accept_document])
        .setup(move |app| {
            if !wait_for_server(port, Duration::from_secs(30)) {
                return Err("le serveur Python n'a pas démarré (qcm-papier est-il installé avec l'extra web ?)".into());
            }
            app.add_capability(tauri::ipc::CapabilityBuilder::new("desktop-documents")
                .window("main").local(false).remote(format!("http://127.0.0.1:{port}/*"))
                .permission("allow-save-document").permission("allow-reset-document")
                .permission("allow-close-document").permission("allow-desktop-ready")
                .permission("allow-open-document").permission("allow-accept-document"))?;
            let url = format!("http://127.0.0.1:{port}/").parse()?;
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url))
                .on_navigation(move |url| url.scheme() == "http" && url.host_str() == Some("127.0.0.1") && url.port() == Some(port))
                .title("QCM-Papier")
                .inner_size(1280.0, 860.0)
                .build()?;
            let handle = app.handle().clone();
            window.on_window_event(move |event| {
                let desktop = handle.state::<Desktop>();
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    if desktop.ready.load(Ordering::SeqCst) && !desktop.exiting.load(Ordering::SeqCst) {
                        api.prevent_close();
                        ask_close(&handle);
                    }
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("erreur au démarrage de l'application");

    app.run(|handle, event| {
        if let RunEvent::ExitRequested { api, .. } = &event {
            let desktop = handle.state::<Desktop>();
            if desktop.ready.load(Ordering::SeqCst) && !desktop.exiting.load(Ordering::SeqCst) {
                api.prevent_exit();
                ask_close(handle);
            }
        }
        if let RunEvent::Exit = event {
            if let Some(mut child) = handle.state::<Server>().0.lock().unwrap().take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    });
}
