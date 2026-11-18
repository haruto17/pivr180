mod storage;

use std::path::PathBuf;
use storage::{StoragePaths, StorageSettings};
use tauri::{AppHandle, Manager};

fn settings_path(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_config_dir()
        .map(|dir| dir.join("settings.json"))
        .map_err(|e| e.to_string())
}

#[tauri::command]
async fn get_storage_settings(app: AppHandle) -> Result<StoragePaths, String> {
    let home = app.path().home_dir().map_err(|e| e.to_string())?;
    let path = settings_path(&app)?;
    tauri::async_runtime::spawn_blocking(move || {
        StorageSettings::load(&path, &home)
            .map(|settings| settings.paths())
            .map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn set_storage_settings(app: AppHandle, root: PathBuf) -> Result<StoragePaths, String> {
    let home = app.path().home_dir().map_err(|e| e.to_string())?;
    let path = settings_path(&app)?;
    tauri::async_runtime::spawn_blocking(move || {
        StorageSettings::change_root(root, &path, &home)
            .map(|settings| settings.paths())
            .map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn get_import_host(app: AppHandle) -> Result<String, String> {
    let home = app.path().home_dir().map_err(|e| e.to_string())?;
    let path = settings_path(&app)?;
    tauri::async_runtime::spawn_blocking(move || {
        StorageSettings::load(&path, &home)
            .map(|settings| settings.host)
            .map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn set_import_host(app: AppHandle, host: String) -> Result<String, String> {
    let home = app.path().home_dir().map_err(|e| e.to_string())?;
    let path = settings_path(&app)?;
    tauri::async_runtime::spawn_blocking(move || {
        StorageSettings::change_host(&host, &path, &home)
            .map(|settings| settings.host)
            .map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            get_storage_settings,
            set_storage_settings,
            get_import_host,
            set_import_host
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    #[test]
    fn tauri_config_has_app_identity() {
        let config: serde_json::Value =
            serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
        assert_eq!(config["identifier"], "com.haruto17.pivr180.editor");
        assert_eq!(config["productName"], "pivr180 editor");
    }
}
