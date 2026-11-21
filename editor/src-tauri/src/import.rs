use serde::Serialize;
use std::ffi::OsString;
use std::fs;
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::{Mutex, TryLockError};

static IMPORT_LOCK: Mutex<()> = Mutex::new(());

pub const REMOTE_CAPTURES_DIR: &str = "/data/captures/";

const CAPTURE_FILES: [&str; 3] = ["left.jpg", "right.jpg", "meta.json"];

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ImportResult {
    pub imported: Vec<String>,
    pub removed: Vec<String>,
    pub remove_error: Option<String>,
}

pub fn remote_source(host: &str) -> String {
    format!("{host}:{REMOTE_CAPTURES_DIR}")
}

pub fn remote_host(source: &str) -> Option<&str> {
    source.strip_suffix(&format!(":{REMOTE_CAPTURES_DIR}"))
}

pub fn rsync_args(source: &str, dest: &Path) -> Vec<OsString> {
    let mut source = source.to_string();
    if !source.ends_with('/') {
        source.push('/');
    }
    let mut dest = dest.as_os_str().to_owned();
    if !dest.to_string_lossy().ends_with('/') {
        dest.push("/");
    }
    // No --delete: captures already removed from the Pi must stay on the Mac.
    // No --remove-source-files: it removes each transferred file, so a capture still being written on the Pi could lose its files; removal is done per verified capture instead.
    // Not --itemize-changes: each line would carry a change-code prefix to strip, while --out-format=%n prints bare paths on both openrsync and GNU rsync.
    vec![
        "-a".into(),
        "-e".into(),
        "ssh -o BatchMode=yes -o ConnectTimeout=10".into(),
        "--out-format=%n".into(),
        source.into(),
        dest,
    ]
}

pub fn verify_args(source: &str, dest: &Path) -> Vec<OsString> {
    let mut args = rsync_args(source, dest);
    args.insert(0, "-n".into());
    args
}

pub fn is_capture_id(name: &str) -> bool {
    let parts: Vec<&str> = name.split('-').collect();
    parts.len() == 3
        && [8, 6, 3]
            .iter()
            .zip(&parts)
            .all(|(len, part)| part.len() == *len && part.bytes().all(|b| b.is_ascii_digit()))
}

pub fn removable_captures(imported: &[String], changed: &[String], dest: &Path) -> Vec<String> {
    imported
        .iter()
        .filter(|name| is_capture_id(name) && !changed.contains(name))
        .filter(|name| {
            CAPTURE_FILES
                .iter()
                .all(|file| dest.join(name).join(file).is_file())
        })
        .cloned()
        .collect()
}

pub fn ssh_remove_args(host: &str, names: &[String]) -> Vec<OsString> {
    let mut command = "rm -rf --".to_string();
    for name in names {
        command.push_str(&format!(" '{REMOTE_CAPTURES_DIR}{name}'"));
    }
    vec![
        "-o".into(),
        "BatchMode=yes".into(),
        "-o".into(),
        "ConnectTimeout=10".into(),
        "--".into(),
        host.into(),
        command.into(),
    ]
}

pub fn parse_imported(stdout: &str) -> Vec<String> {
    let mut captures: Vec<String> = Vec::new();
    for line in stdout.lines() {
        let Some((capture, file)) = line.trim_end().split_once('/') else {
            continue;
        };
        if capture.is_empty() || capture == "." || file.is_empty() {
            continue;
        }
        if !captures.iter().any(|c| c == capture) {
            captures.push(capture.to_string());
        }
    }
    captures
}

pub fn import_captures(
    source: &str,
    dest: &Path,
    delete_after_import: bool,
) -> Result<ImportResult, String> {
    let _guard = match IMPORT_LOCK.try_lock() {
        Ok(guard) => guard,
        Err(TryLockError::Poisoned(e)) => e.into_inner(),
        Err(TryLockError::WouldBlock) => return Err("取り込み中です".to_string()),
    };
    run_import(source, dest, delete_after_import)
}

fn run_import(
    source: &str,
    dest: &Path,
    delete_after_import: bool,
) -> Result<ImportResult, String> {
    let imported = run_rsync(source, dest)?;
    let mut result = ImportResult {
        imported,
        removed: Vec::new(),
        remove_error: None,
    };
    if delete_after_import && !result.imported.is_empty() {
        match remove_imported(source, dest, &result.imported) {
            Ok(removed) => result.removed = removed,
            Err(e) => result.remove_error = Some(e),
        }
    }
    Ok(result)
}

fn remove_imported(source: &str, dest: &Path, imported: &[String]) -> Result<Vec<String>, String> {
    let changed = rsync(verify_args(source, dest))
        .map_err(|e| format!("削除前の確認に失敗したため、Pi から削除しませんでした: {e}"))?;
    let removable = removable_captures(imported, &changed, dest);
    remove_from_source(source, &removable).map_err(|e| {
        format!("Pi から削除できませんでした（一部は削除されている可能性があります）: {e}")
    })?;
    Ok(removable)
}

fn remove_from_source(source: &str, names: &[String]) -> Result<(), String> {
    if names.is_empty() {
        return Ok(());
    }
    let Some(host) = remote_host(source) else {
        for name in names {
            fs::remove_dir_all(Path::new(source).join(name)).map_err(|e| e.to_string())?;
        }
        return Ok(());
    };
    let output = Command::new("ssh")
        .args(ssh_remove_args(host, names))
        .stdin(Stdio::null())
        .output()
        .map_err(|e| format!("ssh を実行できません: {e}"))?;
    if !output.status.success() {
        return Err(format!(
            "ssh が失敗しました ({}): {}",
            output.status,
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(())
}

fn run_rsync(source: &str, dest: &Path) -> Result<Vec<String>, String> {
    fs::create_dir_all(dest).map_err(|e| e.to_string())?;
    rsync(rsync_args(source, dest))
}

fn rsync(args: Vec<OsString>) -> Result<Vec<String>, String> {
    let output = Command::new("rsync")
        .args(args)
        .stdin(Stdio::null())
        .output()
        .map_err(|e| format!("rsync を実行できません: {e}"))?;
    if !output.status.success() {
        return Err(format!(
            "rsync が失敗しました ({}): {}",
            output.status,
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    Ok(parse_imported(&String::from_utf8_lossy(&output.stdout)))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    use tempfile::tempdir;

    fn args_as_strings(args: Vec<OsString>) -> Vec<String> {
        args.into_iter().map(|a| a.into_string().unwrap()).collect()
    }

    #[test]
    fn remote_source_is_captures_dir_on_host() {
        assert_eq!(
            remote_source("pivr180.local"),
            "pivr180.local:/data/captures/"
        );
    }

    #[test]
    fn rsync_args_copy_capture_folders_into_dest_without_deleting_or_prompting() {
        let args = args_as_strings(rsync_args(
            "pivr180.local:/data/captures/",
            Path::new("/Users/me/Pictures/pivr180/captures"),
        ));
        assert_eq!(
            args,
            vec![
                "-a",
                "-e",
                "ssh -o BatchMode=yes -o ConnectTimeout=10",
                "--out-format=%n",
                "pivr180.local:/data/captures/",
                "/Users/me/Pictures/pivr180/captures/",
            ]
        );
        assert!(!args.iter().any(|a| a.contains("--delete")));
        assert!(!args.iter().any(|a| a.contains("--remove-source-files")));
    }

    #[test]
    fn rsync_args_add_trailing_slashes_so_folders_land_directly_in_dest() {
        let args = args_as_strings(rsync_args(
            "/src/captures",
            &PathBuf::from("/dst/captures/"),
        ));
        assert_eq!(
            &args[args.len() - 2..],
            ["/src/captures/", "/dst/captures/"]
        );
    }

    #[test]
    fn parse_imported_lists_each_capture_with_transferred_files_once() {
        let stdout = "./\n\
            20260101-000000-001/\n\
            20260101-000000-001/left.jpg\n\
            20260101-000000-001/meta.json\n\
            20260101-000000-001/right.jpg\n\
            20260101-000000-002/\n\
            20260101-000000-002/left.jpg\n";
        assert_eq!(
            parse_imported(stdout),
            vec!["20260101-000000-001", "20260101-000000-002"]
        );
    }

    #[test]
    fn parse_imported_ignores_folders_without_transferred_files() {
        assert_eq!(
            parse_imported("./\n20260101-000000-001/\n"),
            Vec::<String>::new()
        );
        assert_eq!(parse_imported(""), Vec::<String>::new());
    }

    #[test]
    fn import_is_rejected_while_another_import_runs() {
        let _running = IMPORT_LOCK.lock().unwrap();
        let dir = tempdir().unwrap();
        let err =
            import_captures("/nonexistent/", &dir.path().join("captures"), false).unwrap_err();
        assert!(err.contains("取り込み中"), "{err}");
    }

    #[test]
    fn rsync_failure_reports_stderr() {
        let dir = tempdir().unwrap();
        let missing = dir.path().join("missing");
        let err = run_rsync(missing.to_str().unwrap(), &dir.path().join("captures")).unwrap_err();
        assert!(err.contains("rsync が失敗しました"), "{err}");
        assert!(err.contains("missing"), "{err}");
    }

    #[test]
    fn rsync_imports_new_captures_once_and_keeps_source() {
        let dir = tempdir().unwrap();
        let source = dir.path().join("pi").join("captures");
        let names = ["20260101-000000-001", "20260101-000000-002"];
        for name in names {
            let capture = source.join(name);
            fs::create_dir_all(&capture).unwrap();
            for file in ["left.jpg", "right.jpg", "meta.json"] {
                fs::write(capture.join(file), name).unwrap();
            }
        }
        let dest = dir.path().join("library").join("captures");

        let first = run_rsync(source.to_str().unwrap(), &dest).unwrap();
        assert_eq!(first, names);
        for name in names {
            for file in ["left.jpg", "right.jpg", "meta.json"] {
                assert_eq!(
                    fs::read_to_string(dest.join(name).join(file)).unwrap(),
                    name
                );
            }
        }

        let second = run_rsync(source.to_str().unwrap(), &dest).unwrap();
        assert_eq!(second, Vec::<String>::new());
        for name in names {
            assert!(source.join(name).join("left.jpg").is_file());
        }
    }

    fn write_capture(dir: &Path, name: &str, files: &[&str]) {
        let capture = dir.join(name);
        fs::create_dir_all(&capture).unwrap();
        for file in files {
            fs::write(capture.join(file), name).unwrap();
        }
    }

    fn names(names: &[&str]) -> Vec<String> {
        names.iter().map(|n| n.to_string()).collect()
    }

    #[test]
    fn remote_host_is_taken_only_from_a_remote_captures_source() {
        assert_eq!(
            remote_host(&remote_source("pi@pivr180.local")),
            Some("pi@pivr180.local")
        );
        assert_eq!(remote_host("/tmp/pi/captures/"), None);
    }

    #[test]
    fn verify_args_are_a_dry_run_of_the_import() {
        let dest = Path::new("/Users/me/Pictures/pivr180/captures");
        let args = args_as_strings(verify_args("pivr180.local:/data/captures/", dest));
        assert_eq!(args[0], "-n");
        assert_eq!(
            args[1..],
            args_as_strings(rsync_args("pivr180.local:/data/captures/", dest))
        );
    }

    #[test]
    fn is_capture_id_accepts_only_device_capture_folder_names() {
        assert!(is_capture_id("20260101-000000-001"));
        for name in [
            "",
            "..",
            "20260101-000000",
            "20260101-000000-0001",
            "2026010a-000000-001",
            "20260101-000000-001 x",
            "20260101-000000-001'",
            "20260101_000000_001",
        ] {
            assert!(!is_capture_id(name), "{name:?}");
        }
    }

    #[test]
    fn removable_captures_are_imported_complete_and_unchanged_since_import() {
        let dir = tempdir().unwrap();
        let all = ["left.jpg", "right.jpg", "meta.json"];
        write_capture(dir.path(), "20260101-000000-001", &all);
        write_capture(
            dir.path(),
            "20260101-000000-002",
            &["left.jpg", "right.jpg"],
        );
        write_capture(dir.path(), "20260101-000000-003", &all);
        write_capture(dir.path(), "20260101-000000-004", &all);
        write_capture(dir.path(), "not-a-capture", &all);

        let removable = removable_captures(
            &names(&[
                "20260101-000000-001",
                "20260101-000000-002",
                "20260101-000000-003",
                "not-a-capture",
            ]),
            &names(&["20260101-000000-003"]),
            dir.path(),
        );

        assert_eq!(removable, names(&["20260101-000000-001"]));
    }

    #[test]
    fn ssh_remove_args_remove_only_the_quoted_capture_folders_without_prompting() {
        let args = args_as_strings(ssh_remove_args(
            "pi@pivr180.local",
            &names(&["20260101-000000-001", "20260101-000000-002"]),
        ));
        assert_eq!(
            args,
            vec![
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                "--",
                "pi@pivr180.local",
                "rm -rf -- '/data/captures/20260101-000000-001' '/data/captures/20260101-000000-002'",
            ]
        );
    }

    #[test]
    fn import_keeps_source_when_delete_after_import_is_off() {
        let dir = tempdir().unwrap();
        let source = dir.path().join("pi").join("captures");
        write_capture(
            &source,
            "20260101-000000-001",
            &["left.jpg", "right.jpg", "meta.json"],
        );
        let dest = dir.path().join("library").join("captures");

        let result = run_import(source.to_str().unwrap(), &dest, false).unwrap();

        assert_eq!(
            result,
            ImportResult {
                imported: names(&["20260101-000000-001"]),
                removed: Vec::new(),
                remove_error: None,
            }
        );
        assert!(
            source
                .join("20260101-000000-001")
                .join("left.jpg")
                .is_file()
        );
    }

    #[test]
    fn import_removes_only_captures_imported_completely_in_this_run_when_on() {
        let dir = tempdir().unwrap();
        let source = dir.path().join("pi").join("captures");
        let dest = dir.path().join("library").join("captures");
        let all = ["left.jpg", "right.jpg", "meta.json"];
        write_capture(&source, "20260101-000000-001", &all);
        run_rsync(source.to_str().unwrap(), &dest).unwrap();
        write_capture(&source, "20260102-000000-001", &all);
        write_capture(&source, "20260102-000000-002", &["left.jpg"]);

        let result = run_import(source.to_str().unwrap(), &dest, true).unwrap();

        assert_eq!(
            result,
            ImportResult {
                imported: names(&["20260102-000000-001", "20260102-000000-002"]),
                removed: names(&["20260102-000000-001"]),
                remove_error: None,
            }
        );
        assert!(!source.join("20260102-000000-001").exists());
        for file in all {
            assert_eq!(
                fs::read_to_string(dest.join("20260102-000000-001").join(file)).unwrap(),
                "20260102-000000-001"
            );
        }
        assert!(
            source
                .join("20260101-000000-001")
                .join("left.jpg")
                .is_file()
        );
        assert!(
            source
                .join("20260102-000000-002")
                .join("left.jpg")
                .is_file()
        );
    }

    #[test]
    fn import_removes_nothing_when_rsync_fails() {
        let dir = tempdir().unwrap();
        let missing = dir.path().join("missing");
        let err = run_import(
            missing.to_str().unwrap(),
            &dir.path().join("captures"),
            true,
        )
        .unwrap_err();
        assert!(err.contains("rsync が失敗しました"), "{err}");
    }

    #[test]
    fn removal_failure_is_reported_with_the_import_result() {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempdir().unwrap();
        let source = dir.path().join("pi").join("captures");
        write_capture(
            &source,
            "20260101-000000-001",
            &["left.jpg", "right.jpg", "meta.json"],
        );
        let capture = source.join("20260101-000000-001");
        fs::set_permissions(&capture, fs::Permissions::from_mode(0o555)).unwrap();
        let dest = dir.path().join("library").join("captures");

        let result = run_import(source.to_str().unwrap(), &dest, true);
        for locked in [capture, dest.join("20260101-000000-001")] {
            fs::set_permissions(locked, fs::Permissions::from_mode(0o755)).unwrap();
        }

        let result = result.unwrap();
        assert_eq!(result.imported, names(&["20260101-000000-001"]));
        assert_eq!(result.removed, Vec::<String>::new());
        let err = result.remove_error.unwrap();
        assert!(err.contains("Pi から削除できませんでした"), "{err}");
        assert!(
            source
                .join("20260101-000000-001")
                .join("left.jpg")
                .is_file()
        );
    }
}
