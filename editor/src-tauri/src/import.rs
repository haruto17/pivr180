use serde::Serialize;
use std::ffi::OsString;
use std::fs;
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::{Mutex, TryLockError};

static IMPORT_LOCK: Mutex<()> = Mutex::new(());

pub const REMOTE_CAPTURES_DIR: &str = "/data/captures/";

const CAPTURE_FILES: [&str; 3] = ["left.jpg", "right.jpg", "meta.json"];
const META_FILE: &str = "meta.json";
pub const REMOVE_BATCH_SIZE: usize = 100;

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

pub fn is_complete_meta(content: &[u8]) -> bool {
    // Not just is_file(): the device creates meta.json before writing it, so an empty or partial file can be imported mid-capture.
    // The trailing newline is checked as well because the device writes json.dumps(...) + "\n" in one go, and a partial file cut just before it would still parse.
    content.ends_with(b"\n")
        && serde_json::from_slice::<serde_json::Map<String, serde_json::Value>>(content).is_ok()
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
        .filter(|name| {
            fs::read(dest.join(name).join(META_FILE)).is_ok_and(|meta| is_complete_meta(&meta))
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
        (result.removed, result.remove_error) = remove_imported(source, dest, &result.imported);
    }
    Ok(result)
}

fn remove_imported(
    source: &str,
    dest: &Path,
    imported: &[String],
) -> (Vec<String>, Option<String>) {
    let changed = match rsync(verify_args(source, dest)) {
        Ok(changed) => changed,
        Err(e) => {
            return (
                Vec::new(),
                Some(format!(
                    "削除前の確認に失敗したため、Pi から削除しませんでした: {e}"
                )),
            );
        }
    };
    let removable = removable_captures(imported, &changed, dest);
    let mut removed = Vec::new();
    // Not one command for all captures: thousands of paths in one ssh argument exceed the OS argument limit.
    for batch in removable.chunks(REMOVE_BATCH_SIZE) {
        if let Err(e) = remove_from_source(source, batch) {
            return (
                removed,
                Some(format!(
                    "Pi からの削除が途中で失敗しました（残りの一部は削除されている可能性があります）: {e}"
                )),
            );
        }
        removed.extend_from_slice(batch);
    }
    (removed, None)
}

fn remove_from_source(source: &str, names: &[String]) -> Result<(), String> {
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
            let content = if *file == META_FILE {
                format!("{{\n  \"id\": \"{name}\"\n}}\n")
            } else {
                name.to_string()
            };
            fs::write(capture.join(file), content).unwrap();
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
    fn is_complete_meta_accepts_only_meta_written_to_the_end() {
        let meta = b"{\n  \"schema_version\": 1\n}\n";
        assert!(is_complete_meta(meta));
        for len in 0..meta.len() {
            assert!(!is_complete_meta(&meta[..len]), "{len}");
        }
        assert!(!is_complete_meta(b"[]\n"));
    }

    #[test]
    fn removable_captures_skip_captures_whose_meta_is_still_being_written() {
        let dir = tempdir().unwrap();
        let all = ["left.jpg", "right.jpg", "meta.json"];
        for (name, meta) in [
            ("20260101-000000-001", ""),
            ("20260101-000000-002", "{\n  \"schema_version\""),
            ("20260101-000000-003", "{\n  \"schema_version\": 1\n}"),
        ] {
            write_capture(dir.path(), name, &all);
            fs::write(dir.path().join(name).join(META_FILE), meta).unwrap();
        }
        write_capture(dir.path(), "20260101-000000-004", &all);

        let removable = removable_captures(
            &names(&[
                "20260101-000000-001",
                "20260101-000000-002",
                "20260101-000000-003",
                "20260101-000000-004",
            ]),
            &[],
            dir.path(),
        );

        assert_eq!(removable, names(&["20260101-000000-004"]));
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
        write_capture(&source, "20260102-000000-003", &all);
        fs::write(source.join("20260102-000000-003").join(META_FILE), "").unwrap();
        let originals: Vec<Vec<u8>> = all
            .iter()
            .map(|file| fs::read(source.join("20260102-000000-001").join(file)).unwrap())
            .collect();

        let result = run_import(source.to_str().unwrap(), &dest, true).unwrap();

        assert_eq!(
            result,
            ImportResult {
                imported: names(&[
                    "20260102-000000-001",
                    "20260102-000000-002",
                    "20260102-000000-003",
                ]),
                removed: names(&["20260102-000000-001"]),
                remove_error: None,
            }
        );
        assert!(!source.join("20260102-000000-001").exists());
        for (file, original) in all.iter().zip(&originals) {
            assert_eq!(
                &fs::read(dest.join("20260102-000000-001").join(file)).unwrap(),
                original
            );
        }
        for kept in [
            "20260101-000000-001",
            "20260102-000000-002",
            "20260102-000000-003",
        ] {
            assert!(source.join(kept).join("left.jpg").is_file(), "{kept}");
        }
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
        assert!(err.contains("Pi からの削除が途中で失敗しました"), "{err}");
        assert!(
            source
                .join("20260101-000000-001")
                .join("left.jpg")
                .is_file()
        );
    }

    #[test]
    fn ssh_remove_args_for_a_full_batch_stay_well_within_argument_limits() {
        let ids: Vec<String> = (0..REMOVE_BATCH_SIZE)
            .map(|i| format!("20260101-000000-{:03}", i % 1000))
            .collect();
        let args = ssh_remove_args("pi@pivr180.local", &ids);
        assert!(args.last().unwrap().len() < 4096);
    }

    #[test]
    fn removal_runs_in_batches_and_reports_captures_removed_before_a_failed_batch() {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempdir().unwrap();
        let source = dir.path().join("pi").join("captures");
        let all = ["left.jpg", "right.jpg", "meta.json"];
        let ids: Vec<String> = (0..REMOVE_BATCH_SIZE * 2 + 50)
            .map(|i| format!("20260101-{:06}-000", i))
            .collect();
        for id in &ids {
            write_capture(&source, id, &all);
        }
        let locked = source.join(&ids[REMOVE_BATCH_SIZE * 2 + 10]);
        fs::set_permissions(&locked, fs::Permissions::from_mode(0o555)).unwrap();
        let dest = dir.path().join("library").join("captures");

        let result = run_import(source.to_str().unwrap(), &dest, true);
        let locked_copy = dest.join(&ids[REMOVE_BATCH_SIZE * 2 + 10]);
        for path in [&locked, &locked_copy] {
            fs::set_permissions(path, fs::Permissions::from_mode(0o755)).unwrap();
        }

        let result = result.unwrap();
        assert_eq!(result.imported, ids);
        assert_eq!(result.removed, ids[..REMOVE_BATCH_SIZE * 2]);
        let err = result.remove_error.unwrap();
        assert!(err.contains("Pi からの削除が途中で失敗しました"), "{err}");
        for id in &ids[..REMOVE_BATCH_SIZE * 2] {
            assert!(!source.join(id).exists(), "{id}");
        }
        assert!(locked.join("left.jpg").is_file());
    }
}
