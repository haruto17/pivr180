mod captures;
// Not yet wired to a Tauri command; that lands with #33.
#[cfg_attr(not(test), allow(dead_code))]
mod correction;
mod import;
mod storage;

use base64::Engine;
use captures::Side;
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
async fn list_captures(app: AppHandle) -> Result<Vec<String>, String> {
    let home = app.path().home_dir().map_err(|e| e.to_string())?;
    let path = settings_path(&app)?;
    tauri::async_runtime::spawn_blocking(move || {
        let settings = StorageSettings::load(&path, &home).map_err(|e| e.to_string())?;
        captures::list_captures(&settings.captures_dir()).map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn capture_thumbnail(app: AppHandle, id: String, side: Side) -> Result<String, String> {
    let home = app.path().home_dir().map_err(|e| e.to_string())?;
    let path = settings_path(&app)?;
    let cache_dir = app.path().app_cache_dir().map_err(|e| e.to_string())?;
    tauri::async_runtime::spawn_blocking(move || {
        let settings = StorageSettings::load(&path, &home).map_err(|e| e.to_string())?;
        let cached = captures::thumbnail(&settings.captures_dir(), &cache_dir, &id, side)
            .map_err(|e| e.to_string())?;
        let jpeg = std::fs::read(cached).map_err(|e| e.to_string())?;
        Ok(format!(
            "data:image/jpeg;base64,{}",
            base64::engine::general_purpose::STANDARD.encode(jpeg)
        ))
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

#[tauri::command]
async fn get_delete_after_import(app: AppHandle) -> Result<bool, String> {
    let home = app.path().home_dir().map_err(|e| e.to_string())?;
    let path = settings_path(&app)?;
    tauri::async_runtime::spawn_blocking(move || {
        StorageSettings::load(&path, &home)
            .map(|settings| settings.delete_after_import)
            .map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn set_delete_after_import(app: AppHandle, enabled: bool) -> Result<bool, String> {
    let home = app.path().home_dir().map_err(|e| e.to_string())?;
    let path = settings_path(&app)?;
    tauri::async_runtime::spawn_blocking(move || {
        StorageSettings::change_delete_after_import(enabled, &path, &home)
            .map(|settings| settings.delete_after_import)
            .map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
async fn import_captures(app: AppHandle) -> Result<import::ImportResult, String> {
    let home = app.path().home_dir().map_err(|e| e.to_string())?;
    let path = settings_path(&app)?;
    tauri::async_runtime::spawn_blocking(move || {
        let settings = StorageSettings::load(&path, &home).map_err(|e| e.to_string())?;
        import::import_captures(
            &import::remote_source(&settings.host),
            &settings.captures_dir(),
            settings.delete_after_import,
        )
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
            list_captures,
            capture_thumbnail,
            get_import_host,
            set_import_host,
            get_delete_after_import,
            set_delete_after_import,
            import_captures
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
