use std::ffi::OsString;
use std::fs;
use std::io;
use std::net::{IpAddr, Ipv4Addr, UdpSocket};
use std::path::Path;
use std::process::{Command, Stdio};

pub const CERT_FILE: &str = "cert.pem";
pub const KEY_FILE: &str = "key.pem";

// Not just "mkcert": an app launched from Finder does not get the Homebrew PATH from the shell profile.
const MKCERT_PROGRAMS: [&str; 3] = [
    "mkcert",
    "/opt/homebrew/bin/mkcert",
    "/usr/local/bin/mkcert",
];

pub fn cert_names(local_domain: Option<String>, lan_ip: Option<IpAddr>) -> Vec<String> {
    local_domain
        .into_iter()
        .chain(lan_ip.map(|ip| ip.to_string()))
        .chain(["localhost".to_string()])
        .collect()
}

pub fn mkcert_args(cert_dir: &Path, names: &[String]) -> Vec<OsString> {
    let mut args: Vec<OsString> = vec![
        "-cert-file".into(),
        cert_dir.join(CERT_FILE).into(),
        "-key-file".into(),
        cert_dir.join(KEY_FILE).into(),
    ];
    args.extend(names.iter().map(OsString::from));
    args
}

pub fn ensure_certificate(
    cert_dir: &Path,
    names: &[String],
    run: impl FnOnce(Vec<OsString>) -> Result<(), String>,
) -> Result<(), String> {
    let cert = cert_dir.join(CERT_FILE);
    let key = cert_dir.join(KEY_FILE);
    if cert.is_file() && key.is_file() {
        return Ok(());
    }
    fs::create_dir_all(cert_dir)
        .map_err(|e| format!("{} を作成できません: {e}", cert_dir.display()))?;
    run(mkcert_args(cert_dir, names))?;
    if !(cert.is_file() && key.is_file()) {
        return Err(format!(
            "mkcert を実行しましたが、{} と {} ができていません",
            cert.display(),
            key.display()
        ));
    }
    Ok(())
}

pub fn run_mkcert(args: Vec<OsString>) -> Result<(), String> {
    run_first_found(&MKCERT_PROGRAMS, args)
}

fn run_first_found(programs: &[&str], args: Vec<OsString>) -> Result<(), String> {
    for program in programs {
        let output = match Command::new(program)
            .args(&args)
            .stdin(Stdio::null())
            .output()
        {
            Ok(output) => output,
            Err(e) if e.kind() == io::ErrorKind::NotFound => continue,
            Err(e) => return Err(format!("mkcert を実行できません: {e}")),
        };
        if !output.status.success() {
            return Err(format!(
                "mkcert が失敗しました ({}): {}",
                output.status,
                String::from_utf8_lossy(&output.stderr).trim()
            ));
        }
        return Ok(());
    }
    Err("mkcert が見つかりません。`brew install mkcert` で入れ、`mkcert -install` を実行してから editor を再起動してください".to_string())
}

pub fn lan_ip() -> Option<IpAddr> {
    // Not listing the network interfaces: that needs a new dependency, while connecting a UDP socket only asks the OS which address it would send from, without sending anything.
    let socket = UdpSocket::bind((Ipv4Addr::UNSPECIFIED, 0)).ok()?;
    socket.connect((Ipv4Addr::new(8, 8, 8, 8), 80)).ok()?;
    Some(socket.local_addr().ok()?.ip()).filter(|ip| !ip.is_loopback() && !ip.is_unspecified())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;

    fn names() -> Vec<String> {
        vec![
            "pivr-mac.local".to_string(),
            "192.168.1.20".to_string(),
            "localhost".to_string(),
        ]
    }

    fn write_pems(dir: &Path) {
        fs::write(dir.join(CERT_FILE), b"cert").unwrap();
        fs::write(dir.join(KEY_FILE), b"key").unwrap();
    }

    #[test]
    fn names_are_the_local_domain_the_lan_ip_and_localhost() {
        assert_eq!(
            cert_names(
                Some("pivr-mac.local".to_string()),
                Some(IpAddr::V4(Ipv4Addr::new(192, 168, 1, 20)))
            ),
            names()
        );
    }

    #[test]
    fn names_skip_what_is_unknown() {
        assert_eq!(cert_names(None, None), ["localhost"]);
        assert_eq!(
            cert_names(None, Some(IpAddr::V4(Ipv4Addr::new(10, 0, 0, 5)))),
            ["10.0.0.5", "localhost"]
        );
        assert_eq!(
            cert_names(Some("pivr-mac.local".to_string()), None),
            ["pivr-mac.local", "localhost"]
        );
    }

    #[test]
    fn mkcert_writes_the_cert_and_key_into_the_cert_dir_for_all_names() {
        assert_eq!(
            mkcert_args(Path::new("/certs"), &names()),
            [
                "-cert-file",
                "/certs/cert.pem",
                "-key-file",
                "/certs/key.pem",
                "pivr-mac.local",
                "192.168.1.20",
                "localhost"
            ]
            .map(OsString::from)
        );
    }

    #[test]
    fn existing_certificate_is_kept() {
        let dir = tempfile::tempdir().unwrap();
        write_pems(dir.path());

        ensure_certificate(dir.path(), &names(), |_| {
            panic!("mkcert must not run");
        })
        .unwrap();

        assert_eq!(fs::read(dir.path().join(CERT_FILE)).unwrap(), b"cert");
        assert_eq!(fs::read(dir.path().join(KEY_FILE)).unwrap(), b"key");
    }

    #[test]
    fn missing_certificate_is_issued_into_a_new_cert_dir() {
        let dir = tempfile::tempdir().unwrap();
        let cert_dir = dir.path().join("config").join("certs");
        let ran = RefCell::new(None);

        ensure_certificate(&cert_dir, &names(), |args| {
            assert!(cert_dir.is_dir());
            write_pems(&cert_dir);
            *ran.borrow_mut() = Some(args);
            Ok(())
        })
        .unwrap();

        assert_eq!(ran.into_inner(), Some(mkcert_args(&cert_dir, &names())));
    }

    #[test]
    fn certificate_is_issued_again_when_only_one_file_exists() {
        for existing in [CERT_FILE, KEY_FILE] {
            let dir = tempfile::tempdir().unwrap();
            fs::write(dir.path().join(existing), b"old").unwrap();
            let ran = RefCell::new(false);

            ensure_certificate(dir.path(), &names(), |_| {
                write_pems(dir.path());
                *ran.borrow_mut() = true;
                Ok(())
            })
            .unwrap();

            assert!(ran.into_inner(), "{existing}");
        }
    }

    #[test]
    fn mkcert_failure_is_reported() {
        let dir = tempfile::tempdir().unwrap();

        let error =
            ensure_certificate(dir.path(), &names(), |_| Err("boom".to_string())).unwrap_err();

        assert_eq!(error, "boom");
    }

    #[test]
    fn missing_files_after_mkcert_are_reported() {
        let dir = tempfile::tempdir().unwrap();

        let error = ensure_certificate(dir.path(), &names(), |_| {
            fs::write(dir.path().join(CERT_FILE), b"cert").unwrap();
            Ok(())
        })
        .unwrap_err();

        assert!(error.contains("key.pem"), "{error}");
    }

    #[test]
    fn unwritable_cert_dir_is_reported() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("file");
        fs::write(&file, b"x").unwrap();
        let cert_dir = file.join("certs");

        let error = ensure_certificate(&cert_dir, &names(), |_| {
            panic!("mkcert must not run");
        })
        .unwrap_err();

        assert!(error.contains("certs"), "{error}");
    }

    #[test]
    fn missing_mkcert_asks_to_install_it() {
        let error = run_first_found(&["/nonexistent/mkcert"], Vec::new()).unwrap_err();

        assert!(error.contains("brew install mkcert"), "{error}");
    }

    #[test]
    fn mkcert_is_looked_up_in_the_next_location_when_not_found() {
        assert_eq!(
            run_first_found(&["/nonexistent/mkcert", "true"], Vec::new()),
            Ok(())
        );
    }

    #[test]
    fn failing_mkcert_is_reported_with_its_status() {
        let error = run_first_found(&["false"], Vec::new()).unwrap_err();

        assert!(error.contains("mkcert が失敗しました"), "{error}");
    }
}
