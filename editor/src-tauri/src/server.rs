use crate::storage::StorageSettings;
use axum::Json;
use axum::Router;
use axum::extract::{Path as UrlPath, State};
use axum::http::{StatusCode, Uri, header};
use axum::response::{IntoResponse, Response};
use axum::routing::get;
use axum_server::tls_rustls::RustlsConfig;
use rust_embed::RustEmbed;
use serde::Serialize;
use std::fs;
use std::io;
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::sync::Arc;

pub const PORT: u16 = 8443;
const PHOTO_SUFFIX: &str = "_180_LR.jpg";

#[derive(RustEmbed)]
#[folder = "../../viewer/dist"]
#[allow_missing = true]
pub struct ViewerAssets;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Photo {
    pub name: String,
    pub url: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ServerStatus {
    pub running: bool,
    pub urls: Vec<String>,
    pub error: Option<String>,
}

impl ServerStatus {
    pub fn running(urls: Vec<String>) -> Self {
        Self {
            running: true,
            urls,
            error: None,
        }
    }

    pub fn failed(error: String) -> Self {
        Self {
            running: false,
            urls: Vec::new(),
            error: Some(error),
        }
    }
}

struct Settings {
    path: PathBuf,
    home: PathBuf,
}

pub fn router<A: RustEmbed + 'static>(settings_path: PathBuf, home: PathBuf) -> Router {
    Router::new()
        .route("/api/photos", get(photos))
        .route("/photos/{name}", get(photo))
        .fallback(asset::<A>)
        .with_state(Arc::new(Settings {
            path: settings_path,
            home,
        }))
}

pub async fn serve(cert_dir: &Path, addr: SocketAddr, app: Router) -> Result<SocketAddr, String> {
    let cert = cert_dir.join("cert.pem");
    let key = cert_dir.join("key.pem");
    let config = RustlsConfig::from_pem_file(&cert, &key)
        .await
        .map_err(|e| {
            format!(
                "証明書を読み込めません（{} と {}）: {e}",
                cert.display(),
                key.display()
            )
        })?;
    let listener = std::net::TcpListener::bind(addr)
        .map_err(|e| format!("ポート {} で待ち受けできません: {e}", addr.port()))?;
    let local_addr = listener.local_addr().map_err(|e| e.to_string())?;
    let server = axum_server::from_tcp_rustls(listener, config).map_err(|e| e.to_string())?;
    tokio::spawn(server.serve(app.into_make_service()));
    Ok(local_addr)
}

pub fn viewer_urls(hostname: Option<&str>, port: u16) -> Vec<String> {
    let mut urls = vec![format!("https://localhost:{port}/")];
    if let Some(label) = hostname
        .and_then(|name| name.split('.').next())
        .filter(|label| !label.is_empty() && *label != "localhost")
    {
        urls.push(format!("https://{label}.local:{port}/"));
    }
    urls
}

pub fn list_photos(exports_dir: &Path) -> io::Result<Vec<Photo>> {
    let entries = match fs::read_dir(exports_dir) {
        Ok(entries) => entries,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(e) => return Err(e),
    };
    let mut names = Vec::new();
    for entry in entries {
        let entry = entry?;
        if !entry.file_type()?.is_file() {
            continue;
        }
        if let Some(name) = entry.file_name().to_str().filter(|n| is_photo_name(n)) {
            names.push(name.to_string());
        }
    }
    names.sort_unstable_by(|a, b| b.cmp(a));
    Ok(names
        .into_iter()
        .map(|name| Photo {
            url: format!("/photos/{name}"),
            name,
        })
        .collect())
}

fn is_photo_name(name: &str) -> bool {
    name.ends_with(PHOTO_SUFFIX) && !name.contains(['/', '\\'])
}

fn load_settings(settings: &Settings) -> io::Result<StorageSettings> {
    StorageSettings::load(&settings.path, &settings.home)
}

fn internal_error(e: impl ToString) -> Response {
    (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()).into_response()
}

async fn photos(State(settings): State<Arc<Settings>>) -> Response {
    let listed =
        tokio::task::spawn_blocking(move || list_photos(&load_settings(&settings)?.exports_dir()))
            .await;
    match listed {
        Ok(Ok(photos)) => Json(photos).into_response(),
        Ok(Err(e)) => internal_error(e),
        Err(e) => internal_error(e),
    }
}

async fn photo(State(settings): State<Arc<Settings>>, UrlPath(name): UrlPath<String>) -> Response {
    if !is_photo_name(&name) {
        return StatusCode::NOT_FOUND.into_response();
    }
    let read = tokio::task::spawn_blocking(move || {
        let path = load_settings(&settings)?.exports_dir().join(name);
        if !fs::symlink_metadata(&path)?.is_file() {
            return Err(io::Error::from(io::ErrorKind::NotFound));
        }
        fs::read(path)
    })
    .await;
    match read {
        Ok(Ok(jpeg)) => ([(header::CONTENT_TYPE, "image/jpeg")], jpeg).into_response(),
        Ok(Err(e)) if e.kind() == io::ErrorKind::NotFound => StatusCode::NOT_FOUND.into_response(),
        Ok(Err(e)) => internal_error(e),
        Err(e) => internal_error(e),
    }
}

async fn asset<A: RustEmbed>(uri: Uri) -> Response {
    let path = match uri.path().trim_start_matches('/') {
        "" => "index.html",
        path => path,
    };
    match A::get(path) {
        Some(file) => (
            [(header::CONTENT_TYPE, file.metadata.mimetype().to_string())],
            file.data,
        )
            .into_response(),
        None => StatusCode::NOT_FOUND.into_response(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use axum::http::Request;
    use http_body_util::BodyExt;
    use std::net::Ipv4Addr;
    use tempfile::TempDir;
    use tower::ServiceExt;

    #[derive(RustEmbed)]
    #[folder = "test-fixtures/viewer"]
    struct TestAssets;

    struct Library {
        dir: TempDir,
        settings_path: PathBuf,
        root: PathBuf,
    }

    impl Library {
        fn new() -> Self {
            let dir = tempfile::tempdir().unwrap();
            let settings_path = dir.path().join("config").join("settings.json");
            let root = dir.path().join("library");
            StorageSettings {
                root: root.clone(),
                ..StorageSettings::default_for(dir.path())
            }
            .save(&settings_path)
            .unwrap();
            Self {
                settings_path,
                root,
                dir,
            }
        }

        fn exports(&self) -> PathBuf {
            self.root.join("exports")
        }

        fn add_export(&self, name: &str, content: &[u8]) {
            fs::create_dir_all(self.exports()).unwrap();
            fs::write(self.exports().join(name), content).unwrap();
        }

        fn change_root(&self, root: PathBuf) {
            StorageSettings::change_root(root, &self.settings_path, Path::new("/unused")).unwrap();
        }

        async fn get(&self, uri: &str) -> (StatusCode, Option<String>, Vec<u8>) {
            let response = router::<TestAssets>(self.settings_path.clone(), PathBuf::from("/"))
                .oneshot(Request::get(uri).body(Body::empty()).unwrap())
                .await
                .unwrap();
            let status = response.status();
            let content_type = response
                .headers()
                .get(header::CONTENT_TYPE)
                .map(|v| v.to_str().unwrap().to_string());
            let body = response.into_body().collect().await.unwrap().to_bytes();
            (status, content_type, body.to_vec())
        }

        async fn photo_names(&self) -> Vec<String> {
            let (status, _, body) = self.get("/api/photos").await;
            assert_eq!(status, StatusCode::OK);
            let photos: Vec<serde_json::Value> = serde_json::from_slice(&body).unwrap();
            photos
                .iter()
                .map(|p| p["name"].as_str().unwrap().to_string())
                .collect()
        }
    }

    #[tokio::test]
    async fn photo_list_returns_exported_photos_newest_first_with_their_urls() {
        let library = Library::new();
        library.add_export("20260101-090000-000_180_LR.jpg", b"a");
        library.add_export("20260102-090000-000_180_LR.jpg", b"b");

        let (status, content_type, body) = library.get("/api/photos").await;

        assert_eq!(status, StatusCode::OK);
        assert_eq!(content_type.as_deref(), Some("application/json"));
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&body).unwrap(),
            serde_json::json!([
                {
                    "name": "20260102-090000-000_180_LR.jpg",
                    "url": "/photos/20260102-090000-000_180_LR.jpg"
                },
                {
                    "name": "20260101-090000-000_180_LR.jpg",
                    "url": "/photos/20260101-090000-000_180_LR.jpg"
                }
            ])
        );
    }

    #[tokio::test]
    async fn photo_list_skips_files_that_are_not_exported_photos() {
        let library = Library::new();
        library.add_export("20260101-090000-000_180_LR.jpg", b"a");
        library.add_export("20260101-090000-000_180_LR.jpg.tmp", b"partial");
        library.add_export("notes.txt", b"x");
        fs::create_dir_all(library.exports().join("20260102-090000-000_180_LR.jpg")).unwrap();

        assert_eq!(
            library.photo_names().await,
            ["20260101-090000-000_180_LR.jpg"]
        );
    }

    #[tokio::test]
    async fn photo_list_does_not_include_captures() {
        let library = Library::new();
        let capture = library.root.join("captures").join("20260101-090000-000");
        fs::create_dir_all(&capture).unwrap();
        fs::write(capture.join("left_180_LR.jpg"), b"x").unwrap();

        assert!(library.photo_names().await.is_empty());
    }

    #[tokio::test]
    async fn photo_list_is_empty_without_an_exports_directory() {
        let library = Library::new();

        assert!(library.photo_names().await.is_empty());
    }

    #[tokio::test]
    async fn photo_list_follows_a_changed_storage_root() {
        let library = Library::new();
        library.add_export("20260101-090000-000_180_LR.jpg", b"a");
        let other = library.dir.path().join("other");
        library.change_root(other.clone());
        fs::write(
            other.join("exports").join("20260301-090000-000_180_LR.jpg"),
            b"c",
        )
        .unwrap();

        assert_eq!(
            library.photo_names().await,
            ["20260301-090000-000_180_LR.jpg"]
        );
    }

    #[tokio::test]
    async fn photo_is_served_as_jpeg() {
        let library = Library::new();
        library.add_export("20260101-090000-000_180_LR.jpg", b"jpeg bytes");

        let (status, content_type, body) =
            library.get("/photos/20260101-090000-000_180_LR.jpg").await;

        assert_eq!(status, StatusCode::OK);
        assert_eq!(content_type.as_deref(), Some("image/jpeg"));
        assert_eq!(body, b"jpeg bytes");
    }

    #[tokio::test]
    async fn photos_outside_exports_or_not_exported_are_not_found() {
        let library = Library::new();
        library.add_export("20260101-090000-000_180_LR.jpg", b"a");
        library.add_export("notes.txt", b"x");
        fs::write(library.root.join("secret_180_LR.jpg"), b"secret").unwrap();

        for uri in [
            "/photos/20260102-090000-000_180_LR.jpg",
            "/photos/notes.txt",
            "/photos/..%2Fsecret_180_LR.jpg",
            "/photos/..%5Csecret_180_LR.jpg",
            "/photos/../secret_180_LR.jpg",
        ] {
            let (status, _, _) = library.get(uri).await;
            assert_eq!(status, StatusCode::NOT_FOUND, "{uri}");
        }
    }

    #[tokio::test]
    async fn root_serves_the_viewer_index() {
        let library = Library::new();

        let (status, content_type, body) = library.get("/").await;

        assert_eq!(status, StatusCode::OK);
        assert_eq!(content_type.as_deref(), Some("text/html"));
        assert_eq!(body, fs::read("test-fixtures/viewer/index.html").unwrap());
    }

    #[tokio::test]
    async fn viewer_assets_are_served_with_their_content_type() {
        let library = Library::new();

        let (status, content_type, _) = library.get("/assets/index.js").await;

        assert_eq!(status, StatusCode::OK);
        assert_eq!(content_type.as_deref(), Some("text/javascript"));
    }

    #[tokio::test]
    async fn missing_viewer_files_are_not_found() {
        let library = Library::new();

        let (status, _, _) = library.get("/missing.html").await;

        assert_eq!(status, StatusCode::NOT_FOUND);
    }

    #[test]
    fn viewer_urls_include_localhost_and_the_local_hostname() {
        assert_eq!(
            viewer_urls(Some("pivr-mac.local"), PORT),
            ["https://localhost:8443/", "https://pivr-mac.local:8443/"]
        );
        assert_eq!(
            viewer_urls(Some("pivr-mac"), PORT),
            ["https://localhost:8443/", "https://pivr-mac.local:8443/"]
        );
    }

    #[test]
    fn viewer_urls_are_only_localhost_without_a_usable_hostname() {
        for hostname in [None, Some(""), Some("localhost")] {
            assert_eq!(viewer_urls(hostname, PORT), ["https://localhost:8443/"]);
        }
    }

    #[tokio::test]
    async fn serving_fails_without_a_certificate() {
        let dir = tempfile::tempdir().unwrap();
        let app = router::<TestAssets>(dir.path().join("settings.json"), PathBuf::from("/"));

        let error = serve(dir.path(), (Ipv4Addr::LOCALHOST, 0).into(), app)
            .await
            .unwrap_err();

        assert!(error.contains("cert.pem"), "{error}");
    }
}
