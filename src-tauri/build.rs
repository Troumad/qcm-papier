fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "save_document",
            "reset_document",
            "close_document",
            "desktop_ready",
            "open_document",
            "accept_document",
        ]),
    ))
    .expect("configuration Tauri invalide");
}
