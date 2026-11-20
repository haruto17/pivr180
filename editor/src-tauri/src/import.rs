use std::ffi::OsString;
use std::fs;
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::{Mutex, TryLockError};

static IMPORT_LOCK: Mutex<()> = Mutex::new(());

pub const REMOTE_CAPTURES_DIR: &str = "/data/captures/";

pub fn remote_source(host: &str) -> String {
    format!("{host}:{REMOTE_CAPTURES_DIR}")
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
    // No --delete / --remove-source-files: the Pi keeps its captures after import.
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

pub fn import_captures(source: &str, dest: &Path) -> Result<Vec<String>, String> {
    let _guard = match IMPORT_LOCK.try_lock() {
        Ok(guard) => guard,
        Err(TryLockError::Poisoned(e)) => e.into_inner(),
        Err(TryLockError::WouldBlock) => return Err("取り込み中です".to_string()),
    };
    run_rsync(source, dest)
}

fn run_rsync(source: &str, dest: &Path) -> Result<Vec<String>, String> {
    fs::create_dir_all(dest).map_err(|e| e.to_string())?;
    let output = Command::new("rsync")
        .args(rsync_args(source, dest))
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
        let err = import_captures("/nonexistent/", &dir.path().join("captures")).unwrap_err();
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
}
