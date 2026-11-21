use serde::{Deserialize, Serialize};
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, PoisonError};

static CHANGE_ROOT_LOCK: Mutex<()> = Mutex::new(());

pub const DEFAULT_HOST: &str = "pivr180.local";

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StorageSettings {
    pub root: PathBuf,
    #[serde(default = "default_host")]
    pub host: String,
    #[serde(default)]
    pub delete_after_import: bool,
}

fn default_host() -> String {
    DEFAULT_HOST.to_string()
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct StoragePaths {
    pub root: PathBuf,
    pub captures: PathBuf,
    pub exports: PathBuf,
}

impl StorageSettings {
    pub fn default_for(home: &Path) -> Self {
        Self {
            root: home.join("Pictures").join("pivr180"),
            host: default_host(),
            delete_after_import: false,
        }
    }

    pub fn captures_dir(&self) -> PathBuf {
        self.root.join("captures")
    }

    pub fn exports_dir(&self) -> PathBuf {
        self.root.join("exports")
    }

    pub fn corrections_dir(&self) -> PathBuf {
        self.root.join("corrections")
    }

    pub fn paths(&self) -> StoragePaths {
        StoragePaths {
            root: self.root.clone(),
            captures: self.captures_dir(),
            exports: self.exports_dir(),
        }
    }

    pub fn load(path: &Path, home: &Path) -> io::Result<Self> {
        match fs::read_to_string(path) {
            Ok(content) => serde_json::from_str(&content).map_err(io::Error::other),
            Err(e) if e.kind() == io::ErrorKind::NotFound => Ok(Self::default_for(home)),
            Err(e) => Err(e),
        }
    }

    pub fn save(&self, path: &Path) -> io::Result<()> {
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let content = serde_json::to_string_pretty(self).map_err(io::Error::other)?;
        // Not fs::write(path): it truncates first, so a failed write would destroy the previous settings.
        let tmp = path.with_extension("json.tmp");
        fs::write(&tmp, content)?;
        fs::rename(&tmp, path)
    }

    pub fn change_root(root: PathBuf, path: &Path, home: &Path) -> io::Result<Self> {
        if !root.is_absolute() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!("保存先は絶対パスで指定してください: {}", root.display()),
            ));
        }
        let _guard = CHANGE_ROOT_LOCK
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        let settings = Self {
            root,
            ..Self::load(path, home)?
        };
        fs::create_dir_all(settings.captures_dir())?;
        fs::create_dir_all(settings.exports_dir())?;
        settings.save(path)?;
        Ok(settings)
    }

    pub fn change_host(host: &str, path: &Path, home: &Path) -> io::Result<Self> {
        let host = host.trim();
        // Not passed through as-is: a leading '-' would be parsed as an rsync option, and whitespace or ':' breaks the host:path source.
        if host.is_empty()
            || host.starts_with('-')
            || host.contains(|c: char| c.is_whitespace() || c == ':' || c == '/')
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!("接続先が不正です: {host:?}"),
            ));
        }
        let _guard = CHANGE_ROOT_LOCK
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        let settings = Self {
            host: host.to_string(),
            ..Self::load(path, home)?
        };
        settings.save(path)?;
        Ok(settings)
    }

    pub fn change_delete_after_import(
        delete_after_import: bool,
        path: &Path,
        home: &Path,
    ) -> io::Result<Self> {
        let _guard = CHANGE_ROOT_LOCK
            .lock()
            .unwrap_or_else(PoisonError::into_inner);
        let settings = Self {
            delete_after_import,
            ..Self::load(path, home)?
        };
        settings.save(path)?;
        Ok(settings)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn default_root_is_pictures_pivr180_under_home() {
        let settings = StorageSettings::default_for(Path::new("/Users/someone"));
        assert_eq!(
            settings.root,
            PathBuf::from("/Users/someone/Pictures/pivr180")
        );
    }

    #[test]
    fn captures_and_exports_live_under_root() {
        let settings = StorageSettings {
            root: PathBuf::from("/data/pivr180"),
            host: DEFAULT_HOST.to_string(),
            delete_after_import: false,
        };
        assert_eq!(
            settings.paths(),
            StoragePaths {
                root: PathBuf::from("/data/pivr180"),
                captures: PathBuf::from("/data/pivr180/captures"),
                exports: PathBuf::from("/data/pivr180/exports"),
            }
        );
    }

    #[test]
    fn corrections_live_under_root() {
        let settings = StorageSettings::default_for(Path::new("/Users/someone"));
        assert_eq!(
            settings.corrections_dir(),
            PathBuf::from("/Users/someone/Pictures/pivr180/corrections")
        );
    }

    #[test]
    fn load_returns_default_when_settings_file_is_missing() {
        let dir = tempdir().unwrap();
        let settings =
            StorageSettings::load(&dir.path().join("settings.json"), Path::new("/home/me"))
                .unwrap();
        assert_eq!(
            settings,
            StorageSettings::default_for(Path::new("/home/me"))
        );
    }

    #[test]
    fn saved_settings_are_loaded_back() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("config").join("settings.json");
        let settings = StorageSettings {
            root: PathBuf::from("/Volumes/ext/pivr180"),
            host: DEFAULT_HOST.to_string(),
            delete_after_import: false,
        };
        settings.save(&path).unwrap();
        assert_eq!(
            StorageSettings::load(&path, Path::new("/home/me")).unwrap(),
            settings
        );
    }

    #[test]
    fn saving_over_existing_settings_replaces_them_without_leaving_temp_file() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("settings.json");
        StorageSettings {
            root: PathBuf::from("/old/pivr180"),
            host: DEFAULT_HOST.to_string(),
            delete_after_import: false,
        }
        .save(&path)
        .unwrap();
        let settings = StorageSettings {
            root: PathBuf::from("/new/pivr180"),
            host: DEFAULT_HOST.to_string(),
            delete_after_import: false,
        };
        settings.save(&path).unwrap();
        assert_eq!(
            StorageSettings::load(&path, Path::new("/home/me")).unwrap(),
            settings
        );
        let entries: Vec<_> = fs::read_dir(dir.path())
            .unwrap()
            .map(|entry| entry.unwrap().file_name())
            .collect();
        assert_eq!(entries, vec!["settings.json"]);
    }

    #[test]
    fn change_root_rejects_relative_path() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("settings.json");
        let err = StorageSettings::change_root(
            PathBuf::from("relative/dir"),
            &path,
            Path::new("/home/me"),
        )
        .unwrap_err();
        assert_eq!(err.kind(), io::ErrorKind::InvalidInput);
        assert!(!path.exists());
    }

    #[test]
    fn change_root_creates_captures_and_exports_and_saves() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("settings.json");
        let root = dir.path().join("library");
        let settings =
            StorageSettings::change_root(root.clone(), &path, Path::new("/home/me")).unwrap();
        assert!(root.join("captures").is_dir());
        assert!(root.join("exports").is_dir());
        assert_eq!(
            StorageSettings::load(&path, Path::new("/home/me")).unwrap(),
            settings
        );
    }

    #[test]
    fn concurrent_change_root_calls_persist_one_of_the_roots_without_leaving_temp_file() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("settings.json");
        let roots: Vec<PathBuf> = (0..8)
            .map(|i| dir.path().join(format!("library{i}")))
            .collect();
        std::thread::scope(|scope| {
            for root in &roots {
                let path = &path;
                scope.spawn(move || {
                    StorageSettings::change_root(root.clone(), path, Path::new("/home/me")).unwrap()
                });
            }
        });
        let saved = StorageSettings::load(&path, Path::new("/home/me")).unwrap();
        assert!(roots.contains(&saved.root));
        assert!(!path.with_extension("json.tmp").exists());
    }

    #[test]
    fn default_host_is_pivr180_local() {
        let settings = StorageSettings::default_for(Path::new("/home/me"));
        assert_eq!(settings.host, "pivr180.local");
    }

    #[test]
    fn settings_saved_before_host_existed_load_with_default_host() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("settings.json");
        fs::write(&path, r#"{"root": "/Volumes/ext/pivr180"}"#).unwrap();
        assert_eq!(
            StorageSettings::load(&path, Path::new("/home/me")).unwrap(),
            StorageSettings {
                root: PathBuf::from("/Volumes/ext/pivr180"),
                host: "pivr180.local".to_string(),
                delete_after_import: false,
            }
        );
    }

    #[test]
    fn change_host_saves_host_and_keeps_root() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("settings.json");
        let root = dir.path().join("library");
        StorageSettings::change_root(root.clone(), &path, Path::new("/home/me")).unwrap();
        let settings =
            StorageSettings::change_host(" pi@pivr180.local ", &path, Path::new("/home/me"))
                .unwrap();
        assert_eq!(
            settings,
            StorageSettings {
                root,
                host: "pi@pivr180.local".to_string(),
                delete_after_import: false,
            }
        );
        assert_eq!(
            StorageSettings::load(&path, Path::new("/home/me")).unwrap(),
            settings
        );
    }

    #[test]
    fn change_root_keeps_host() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("settings.json");
        StorageSettings::change_host("raspberrypi.local", &path, Path::new("/home/me")).unwrap();
        let settings =
            StorageSettings::change_root(dir.path().join("library"), &path, Path::new("/home/me"))
                .unwrap();
        assert_eq!(settings.host, "raspberrypi.local");
    }

    #[test]
    fn change_host_rejects_values_rsync_would_misread() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("settings.json");
        for host in [
            "",
            "  ",
            "-oProxyCommand=x",
            "pi local",
            "pivr180.local:/etc",
            "a/b",
        ] {
            let err = StorageSettings::change_host(host, &path, Path::new("/home/me")).unwrap_err();
            assert_eq!(err.kind(), io::ErrorKind::InvalidInput, "{host:?}");
        }
        assert!(!path.exists());
    }

    #[test]
    fn delete_after_import_is_off_by_default() {
        let settings = StorageSettings::default_for(Path::new("/home/me"));
        assert!(!settings.delete_after_import);
    }

    #[test]
    fn settings_saved_before_delete_after_import_existed_load_with_it_off() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("settings.json");
        fs::write(
            &path,
            r#"{"root": "/Volumes/ext/pivr180", "host": "raspberrypi.local"}"#,
        )
        .unwrap();
        let settings = StorageSettings::load(&path, Path::new("/home/me")).unwrap();
        assert!(!settings.delete_after_import);
        assert_eq!(settings.host, "raspberrypi.local");
    }

    #[test]
    fn change_delete_after_import_saves_it_and_keeps_root_and_host() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("settings.json");
        let root = dir.path().join("library");
        StorageSettings::change_root(root.clone(), &path, Path::new("/home/me")).unwrap();
        StorageSettings::change_host("raspberrypi.local", &path, Path::new("/home/me")).unwrap();
        let settings =
            StorageSettings::change_delete_after_import(true, &path, Path::new("/home/me"))
                .unwrap();
        assert_eq!(
            settings,
            StorageSettings {
                root,
                host: "raspberrypi.local".to_string(),
                delete_after_import: true,
            }
        );
        assert_eq!(
            StorageSettings::load(&path, Path::new("/home/me")).unwrap(),
            settings
        );
    }

    #[test]
    fn change_root_and_host_keep_delete_after_import() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("settings.json");
        StorageSettings::change_delete_after_import(true, &path, Path::new("/home/me")).unwrap();
        StorageSettings::change_root(dir.path().join("library"), &path, Path::new("/home/me"))
            .unwrap();
        let settings =
            StorageSettings::change_host("raspberrypi.local", &path, Path::new("/home/me"))
                .unwrap();
        assert!(settings.delete_after_import);
    }
}
