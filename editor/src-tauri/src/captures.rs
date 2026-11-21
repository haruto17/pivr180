use image::codecs::jpeg::JpegEncoder;
use serde::Deserialize;
use std::fs::{self, File};
use std::io::{self, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Condvar, Mutex, PoisonError};
use std::thread;

pub const THUMBNAIL_MAX_SIDE: u32 = 320;
const THUMBNAIL_QUALITY: u8 = 85;

static TEMP_COUNTER: AtomicU64 = AtomicU64::new(0);
static GENERATING: (Mutex<usize>, Condvar) = (Mutex::new(0), Condvar::new());

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Side {
    Left,
    Right,
}

impl Side {
    fn name(self) -> &'static str {
        match self {
            Side::Left => "left",
            Side::Right => "right",
        }
    }

    fn image_file(self) -> String {
        format!("{}.jpg", self.name())
    }
}

fn is_valid_id(id: &str) -> bool {
    !id.is_empty()
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
}

pub(crate) fn validate_id(id: &str) -> io::Result<()> {
    if is_valid_id(id) {
        Ok(())
    } else {
        Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("撮影 ID が不正です: {id}"),
        ))
    }
}

pub fn list_captures(captures_dir: &Path) -> io::Result<Vec<String>> {
    let entries = match fs::read_dir(captures_dir) {
        Ok(entries) => entries,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(e) => return Err(e),
    };
    let mut ids = Vec::new();
    for entry in entries {
        let entry = entry?;
        let Ok(id) = entry.file_name().into_string() else {
            continue;
        };
        let dir = entry.path();
        if is_valid_id(&id)
            && dir.is_dir()
            && [Side::Left, Side::Right]
                .iter()
                .all(|side| dir.join(side.image_file()).is_file())
        {
            ids.push(id);
        }
    }
    ids.sort_unstable_by(|a, b| b.cmp(a));
    Ok(ids)
}

pub fn thumbnail(
    captures_dir: &Path,
    cache_dir: &Path,
    id: &str,
    side: Side,
) -> io::Result<PathBuf> {
    validate_id(id)?;
    let source = captures_dir.join(id).join(side.image_file());
    let source_modified = fs::metadata(&source)?.modified()?;
    let cached = cache_dir
        .join("thumbnails")
        .join(id)
        .join(side.image_file());
    match fs::metadata(&cached) {
        Ok(meta) if meta.modified()? >= source_modified => return Ok(cached),
        Ok(_) => {}
        Err(e) if e.kind() == io::ErrorKind::NotFound => {}
        Err(e) => return Err(e),
    }
    let _slot = GenerationSlot::acquire();
    generate(&source, &cached)?;
    Ok(cached)
}

fn generate(source: &Path, cached: &Path) -> io::Result<()> {
    let image = image::open(source).map_err(io::Error::other)?;
    let thumbnail = image
        .thumbnail(THUMBNAIL_MAX_SIDE, THUMBNAIL_MAX_SIDE)
        .into_rgb8();
    let dir = cached.parent().expect("cached thumbnail path has a parent");
    fs::create_dir_all(dir)?;
    // Not written to `cached` directly: a concurrent reader could be served a half-written file.
    let tmp = dir.join(format!(
        ".{}.{}.tmp",
        std::process::id(),
        TEMP_COUNTER.fetch_add(1, Ordering::Relaxed)
    ));
    let result = File::create(&tmp)
        .and_then(|file| {
            let mut writer = BufWriter::new(file);
            JpegEncoder::new_with_quality(&mut writer, THUMBNAIL_QUALITY)
                .encode_image(&thumbnail)
                .map_err(io::Error::other)?;
            writer.flush()
        })
        .and_then(|()| fs::rename(&tmp, cached));
    if result.is_err() {
        let _ = fs::remove_file(&tmp);
    }
    result
}

// Not left to spawn_blocking alone: it would decode every requested image at once, ~37MB of pixels each.
struct GenerationSlot;

impl GenerationSlot {
    fn acquire() -> Self {
        let limit = thread::available_parallelism().map_or(2, |n| n.get());
        let (count, released) = &GENERATING;
        let mut count = count.lock().unwrap_or_else(PoisonError::into_inner);
        while *count >= limit {
            count = released.wait(count).unwrap_or_else(PoisonError::into_inner);
        }
        *count += 1;
        Self
    }
}

impl Drop for GenerationSlot {
    fn drop(&mut self) {
        let (count, released) = &GENERATING;
        *count.lock().unwrap_or_else(PoisonError::into_inner) -= 1;
        released.notify_one();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::{GenericImageView, RgbImage};
    use std::time::{Duration, SystemTime};
    use tempfile::tempdir;

    fn write_jpeg(path: &Path, width: u32, height: u32) {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        RgbImage::from_pixel(width, height, image::Rgb([200, 100, 50]))
            .save(path)
            .unwrap();
    }

    fn add_capture(captures: &Path, id: &str) {
        write_jpeg(&captures.join(id).join("left.jpg"), 640, 480);
        write_jpeg(&captures.join(id).join("right.jpg"), 640, 480);
    }

    fn dimensions(path: &Path) -> (u32, u32) {
        image::open(path).unwrap().dimensions()
    }

    fn set_modified(path: &Path, time: SystemTime) {
        File::options()
            .write(true)
            .open(path)
            .unwrap()
            .set_modified(time)
            .unwrap();
    }

    #[test]
    fn missing_captures_dir_lists_nothing() {
        let dir = tempdir().unwrap();
        assert_eq!(
            list_captures(&dir.path().join("captures")).unwrap(),
            Vec::<String>::new()
        );
    }

    #[test]
    fn lists_complete_captures_newest_first() {
        let dir = tempdir().unwrap();
        let captures = dir.path().join("captures");
        add_capture(&captures, "20260101-090000-000");
        add_capture(&captures, "20260301-120000-500");
        add_capture(&captures, "20260201-100000-000");
        assert_eq!(
            list_captures(&captures).unwrap(),
            vec![
                "20260301-120000-500",
                "20260201-100000-000",
                "20260101-090000-000"
            ]
        );
    }

    #[test]
    fn listing_skips_incomplete_folders_files_and_unexpected_names() {
        let dir = tempdir().unwrap();
        let captures = dir.path().join("captures");
        add_capture(&captures, "20260101-090000-000");
        write_jpeg(&captures.join("20260102-090000-000").join("left.jpg"), 8, 8);
        write_jpeg(
            &captures.join("20260103-090000-000").join("right.jpg"),
            8,
            8,
        );
        fs::write(captures.join("20260104-090000-000"), "not a folder").unwrap();
        add_capture(&captures, ".hidden");
        assert_eq!(
            list_captures(&captures).unwrap(),
            vec!["20260101-090000-000"]
        );
    }

    #[test]
    fn side_accepts_only_left_and_right() {
        assert_eq!(
            serde_json::from_str::<Side>("\"left\"").unwrap(),
            Side::Left
        );
        assert_eq!(
            serde_json::from_str::<Side>("\"right\"").unwrap(),
            Side::Right
        );
        assert!(serde_json::from_str::<Side>("\"meta\"").is_err());
        assert!(serde_json::from_str::<Side>("\"../left\"").is_err());
    }

    #[test]
    fn thumbnail_rejects_ids_that_could_escape_captures_dir() {
        let dir = tempdir().unwrap();
        let captures = dir.path().join("library").join("captures");
        let cache = dir.path().join("cache");
        write_jpeg(&dir.path().join("library").join("left.jpg"), 8, 8);
        for id in ["", ".", "..", "../captures", "a/b", "a\\b", "/etc"] {
            let err = thumbnail(&captures, &cache, id, Side::Left).unwrap_err();
            assert_eq!(err.kind(), io::ErrorKind::InvalidInput, "id {id:?}");
        }
        assert!(!cache.exists());
    }

    #[test]
    fn thumbnail_of_missing_capture_is_not_found() {
        let dir = tempdir().unwrap();
        let cache = dir.path().join("cache");
        let err = thumbnail(
            &dir.path().join("captures"),
            &cache,
            "20260101-090000-000",
            Side::Left,
        )
        .unwrap_err();
        assert_eq!(err.kind(), io::ErrorKind::NotFound);
        assert!(!cache.exists());
    }

    #[test]
    fn thumbnail_is_downscaled_into_cache_without_touching_captures() {
        let dir = tempdir().unwrap();
        let captures = dir.path().join("captures");
        let cache = dir.path().join("cache");
        let id = "20260101-090000-000";
        add_capture(&captures, id);

        let cached = thumbnail(&captures, &cache, id, Side::Right).unwrap();

        assert_eq!(cached, cache.join("thumbnails").join(id).join("right.jpg"));
        assert_eq!(dimensions(&cached), (320, 240));
        let mut capture_files: Vec<_> = fs::read_dir(captures.join(id))
            .unwrap()
            .map(|entry| entry.unwrap().file_name())
            .collect();
        capture_files.sort();
        assert_eq!(capture_files, vec!["left.jpg", "right.jpg"]);
        let cache_files: Vec<_> = fs::read_dir(cached.parent().unwrap())
            .unwrap()
            .map(|entry| entry.unwrap().file_name())
            .collect();
        assert_eq!(cache_files, vec!["right.jpg"]);
    }

    #[test]
    fn cached_thumbnail_is_reused_while_source_is_unchanged() {
        let dir = tempdir().unwrap();
        let captures = dir.path().join("captures");
        let cache = dir.path().join("cache");
        let id = "20260101-090000-000";
        add_capture(&captures, id);
        let cached = thumbnail(&captures, &cache, id, Side::Left).unwrap();
        let marker = b"cached thumbnail".to_vec();
        fs::write(&cached, &marker).unwrap();
        let modified = fs::metadata(&cached).unwrap().modified().unwrap();

        assert_eq!(
            thumbnail(&captures, &cache, id, Side::Left).unwrap(),
            cached
        );

        assert_eq!(fs::read(&cached).unwrap(), marker);
        assert_eq!(fs::metadata(&cached).unwrap().modified().unwrap(), modified);
    }

    #[test]
    fn thumbnail_is_regenerated_when_source_is_newer_than_cache() {
        let dir = tempdir().unwrap();
        let captures = dir.path().join("captures");
        let cache = dir.path().join("cache");
        let id = "20260101-090000-000";
        add_capture(&captures, id);
        let cached = thumbnail(&captures, &cache, id, Side::Left).unwrap();
        let source = captures.join(id).join("left.jpg");
        write_jpeg(&source, 480, 640);
        set_modified(
            &source,
            fs::metadata(&cached).unwrap().modified().unwrap() + Duration::from_secs(10),
        );

        thumbnail(&captures, &cache, id, Side::Left).unwrap();

        assert_eq!(dimensions(&cached), (240, 320));
    }
}
