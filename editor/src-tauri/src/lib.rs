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
fn get_storage_settings(app: AppHandle) -> Result<StoragePaths, String> {
    let home = app.path().home_dir().map_err(|e| e.to_string())?;
    StorageSettings::load(&settings_path(&app)?, &home)
        .map(|settings| settings.paths())
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn set_storage_settings(app: AppHandle, root: PathBuf) -> Result<StoragePaths, String> {
    StorageSettings::change_root(root, &settings_path(&app)?)
        .map(|settings| settings.paths())
        .map_err(|e| e.to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            get_storage_settings,
            set_storage_settings
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
