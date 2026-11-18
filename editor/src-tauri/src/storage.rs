use serde::{Deserialize, Serialize};
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StorageSettings {
    pub root: PathBuf,
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
        }
    }

    pub fn captures_dir(&self) -> PathBuf {
        self.root.join("captures")
    }

    pub fn exports_dir(&self) -> PathBuf {
        self.root.join("exports")
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

    pub fn change_root(root: PathBuf, path: &Path) -> io::Result<Self> {
        if !root.is_absolute() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                format!("保存先は絶対パスで指定してください: {}", root.display()),
            ));
        }
        let settings = Self { root };
        fs::create_dir_all(settings.captures_dir())?;
        fs::create_dir_all(settings.exports_dir())?;
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
        }
        .save(&path)
        .unwrap();
        let settings = StorageSettings {
            root: PathBuf::from("/new/pivr180"),
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
        let err = StorageSettings::change_root(PathBuf::from("relative/dir"), &path).unwrap_err();
        assert_eq!(err.kind(), io::ErrorKind::InvalidInput);
        assert!(!path.exists());
    }

    #[test]
    fn change_root_creates_captures_and_exports_and_saves() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("settings.json");
        let root = dir.path().join("library");
        let settings = StorageSettings::change_root(root.clone(), &path).unwrap();
        assert!(root.join("captures").is_dir());
        assert!(root.join("exports").is_dir());
        assert_eq!(
            StorageSettings::load(&path, Path::new("/home/me")).unwrap(),
            settings
        );
    }
}
