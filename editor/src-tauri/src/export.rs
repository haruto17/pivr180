use crate::captures;
use crate::correction::{self, ImageCircle};
use crate::equirect::Lut;
use crate::storage;
use image::codecs::jpeg::JpegEncoder;
use image::{DynamicImage, ImageError, RgbImage};
use std::fs::{self, File};
use std::io::{self, BufWriter, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, PoisonError};

pub const JPEG_QUALITY: u8 = 95;

static TEMP_COUNTER: AtomicU64 = AtomicU64::new(0);
// Not run concurrently: each export already uses every core, and holds ~400MB at 2880px per eye.
static EXPORT_LOCK: Mutex<()> = Mutex::new(());

pub fn export_capture(
    captures_dir: &Path,
    corrections_dir: &Path,
    exports_dir: &Path,
    id: &str,
    eye_size: u32,
) -> io::Result<PathBuf> {
    captures::validate_id(id)?;
    storage::validate_export_eye_size(eye_size)?;
    let correction = correction::load_capture_correction(corrections_dir, id)?;
    let _guard = EXPORT_LOCK.lock().unwrap_or_else(PoisonError::into_inner);
    let dir = captures_dir.join(id);
    let (left, right) = rayon::join(
        || decode(&dir.join("left.jpg")),
        || decode(&dir.join("right.jpg")),
    );
    let (left, right) = (left?, right?);
    let mut sbs = RgbImage::new(eye_size * 2, eye_size);
    for (x, circle, src) in [
        (0, &correction.left, &left),
        (eye_size, &correction.right, &right),
    ] {
        let eye = to_equirect(circle, src, eye_size)?;
        image::imageops::replace(&mut sbs, &eye, i64::from(x), 0);
    }
    fs::create_dir_all(exports_dir)?;
    let output = exports_dir.join(format!("{id}_180_LR.jpg"));
    write_jpeg(&sbs, &output)?;
    Ok(output)
}

fn decode(path: &Path) -> io::Result<RgbImage> {
    image::open(path).map(DynamicImage::into_rgb8).map_err(|e| {
        let kind = match &e {
            ImageError::IoError(e) => e.kind(),
            _ => io::ErrorKind::InvalidData,
        };
        io::Error::new(kind, format!("{}: {e}", path.display()))
    })
}

fn to_equirect(circle: &ImageCircle, src: &RgbImage, eye_size: u32) -> io::Result<RgbImage> {
    let (w, h) = src.dimensions();
    Lut::new(circle, w, h, eye_size, eye_size)
        .remap(src)
        .map_err(io::Error::other)
}

fn write_jpeg(image: &RgbImage, output: &Path) -> io::Result<()> {
    let dir = output.parent().expect("export path has a parent");
    // Not written to `output` directly: a failed export would destroy the previous one.
    let tmp = dir.join(format!(
        ".{}.{}.tmp",
        std::process::id(),
        TEMP_COUNTER.fetch_add(1, Ordering::Relaxed)
    ));
    let result = File::create(&tmp)
        .and_then(|file| {
            let mut writer = BufWriter::new(file);
            JpegEncoder::new_with_quality(&mut writer, JPEG_QUALITY)
                .encode_image(image)
                .map_err(io::Error::other)?;
            writer.flush()
        })
        .and_then(|()| fs::rename(&tmp, output));
    if result.is_err() {
        let _ = fs::remove_file(&tmp);
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::correction::{CorrectionOverride, StereoCorrection};
    use image::Rgb;
    use tempfile::{TempDir, tempdir};

    const ID: &str = "20260101-090000-000";
    const N: u32 = 256;
    const RED: Rgb<u8> = Rgb([220, 30, 30]);
    const BLUE: Rgb<u8> = Rgb([30, 30, 220]);
    const GREEN: Rgb<u8> = Rgb([30, 200, 30]);

    struct Library {
        _dir: TempDir,
        captures: PathBuf,
        corrections: PathBuf,
        exports: PathBuf,
    }

    impl Library {
        fn new() -> Self {
            let dir = tempdir().unwrap();
            let library = Self {
                captures: dir.path().join("captures"),
                corrections: dir.path().join("corrections"),
                exports: dir.path().join("exports"),
                _dir: dir,
            };
            let circle = ImageCircle {
                center_x_px: 32.0,
                center_y_px: 24.0,
                radius_px: 20.0,
                rotation_deg: 0.0,
            };
            correction::save_device_default(
                &library.corrections,
                StereoCorrection {
                    left: circle,
                    right: circle,
                },
            )
            .unwrap();
            library
        }

        fn add_image(&self, id: &str, file: &str, image: &RgbImage) {
            let dir = self.captures.join(id);
            fs::create_dir_all(&dir).unwrap();
            image.save(dir.join(file)).unwrap();
        }

        fn add_capture(&self, id: &str, left: Rgb<u8>, right: Rgb<u8>) {
            self.add_image(id, "left.jpg", &RgbImage::from_pixel(64, 48, left));
            self.add_image(id, "right.jpg", &RgbImage::from_pixel(64, 48, right));
        }

        fn export(&self, id: &str) -> io::Result<PathBuf> {
            export_capture(&self.captures, &self.corrections, &self.exports, id, N)
        }

        fn export_files(&self) -> Vec<String> {
            let Ok(entries) = fs::read_dir(&self.exports) else {
                return Vec::new();
            };
            let mut names: Vec<_> = entries
                .map(|entry| entry.unwrap().file_name().into_string().unwrap())
                .collect();
            names.sort();
            names
        }
    }

    fn assert_color_near(actual: Rgb<u8>, expected: Rgb<u8>) {
        assert!(
            actual
                .0
                .iter()
                .zip(expected.0)
                .all(|(&a, e)| a.abs_diff(e) <= 12),
            "{actual:?} is not near {expected:?}"
        );
    }

    #[test]
    fn writes_side_by_side_jpeg_named_after_the_capture_into_exports() {
        let library = Library::new();
        library.add_capture(ID, RED, BLUE);

        let output = library.export(ID).unwrap();

        assert_eq!(output, library.exports.join(format!("{ID}_180_LR.jpg")));
        assert_eq!(library.export_files(), vec![format!("{ID}_180_LR.jpg")]);
        assert_eq!(
            image::ImageReader::open(&output)
                .unwrap()
                .with_guessed_format()
                .unwrap()
                .format(),
            Some(image::ImageFormat::Jpeg)
        );
        assert_eq!(image::image_dimensions(&output).unwrap(), (2 * N, N));
    }

    #[test]
    fn left_eye_is_on_the_left_half_and_right_eye_on_the_right_half() {
        let library = Library::new();
        library.add_capture(ID, RED, BLUE);

        let out = image::open(library.export(ID).unwrap())
            .unwrap()
            .into_rgb8();

        assert_color_near(*out.get_pixel(N / 2, N / 2), RED);
        assert_color_near(*out.get_pixel(N + N / 2, N / 2), BLUE);
    }

    #[test]
    fn capture_override_is_used_instead_of_the_device_default() {
        let library = Library::new();
        let split = RgbImage::from_fn(64, 48, |x, _| if x < 32 { GREEN } else { BLUE });
        library.add_image(ID, "left.jpg", &split);
        library.add_image(ID, "right.jpg", &split);
        let circle = |center_x_px| ImageCircle {
            center_x_px,
            center_y_px: 24.0,
            radius_px: 20.0,
            rotation_deg: 0.0,
        };
        correction::save_device_default(
            &library.corrections,
            StereoCorrection {
                left: circle(44.0),
                right: circle(44.0),
            },
        )
        .unwrap();
        correction::save_capture_override(
            &library.corrections,
            ID,
            CorrectionOverride {
                left: None,
                right: Some(circle(20.0)),
            },
        )
        .unwrap();

        let out = image::open(library.export(ID).unwrap())
            .unwrap()
            .into_rgb8();

        assert_color_near(*out.get_pixel(N / 2, N / 2), BLUE);
        assert_color_near(*out.get_pixel(N + N / 2, N / 2), GREEN);
    }

    #[test]
    fn exporting_again_overwrites_the_previous_file() {
        let library = Library::new();
        library.add_capture(ID, RED, BLUE);
        library.export(ID).unwrap();
        library.add_capture(ID, GREEN, GREEN);

        let out = image::open(library.export(ID).unwrap())
            .unwrap()
            .into_rgb8();

        assert_color_near(*out.get_pixel(N / 2, N / 2), GREEN);
        assert_eq!(library.export_files(), vec![format!("{ID}_180_LR.jpg")]);
    }

    #[test]
    fn invalid_ids_are_rejected_without_writing_anything() {
        let library = Library::new();
        library.add_capture(ID, RED, BLUE);
        for id in ["", ".", "..", "../captures", "a/b", "/etc"] {
            let err = library.export(id).unwrap_err();
            assert_eq!(err.kind(), io::ErrorKind::InvalidInput, "id {id:?}");
        }
        assert!(library.export_files().is_empty());
    }

    #[test]
    fn missing_image_is_not_found_and_leaves_no_file() {
        let library = Library::new();
        library.add_image(ID, "left.jpg", &RgbImage::from_pixel(64, 48, RED));

        let err = library.export(ID).unwrap_err();

        assert_eq!(err.kind(), io::ErrorKind::NotFound);
        assert!(library.export_files().is_empty());
    }

    #[test]
    fn broken_image_is_invalid_data_and_keeps_the_previous_export() {
        let library = Library::new();
        library.add_capture(ID, RED, BLUE);
        let output = library.export(ID).unwrap();
        let previous = fs::read(&output).unwrap();
        fs::write(library.captures.join(ID).join("right.jpg"), "not a jpeg").unwrap();

        let err = library.export(ID).unwrap_err();

        assert_eq!(err.kind(), io::ErrorKind::InvalidData);
        assert_eq!(fs::read(&output).unwrap(), previous);
        assert_eq!(library.export_files(), vec![format!("{ID}_180_LR.jpg")]);
    }

    #[test]
    fn eye_size_out_of_range_is_rejected() {
        let library = Library::new();
        library.add_capture(ID, RED, BLUE);
        let err = export_capture(
            &library.captures,
            &library.corrections,
            &library.exports,
            ID,
            8193,
        )
        .unwrap_err();
        assert_eq!(err.kind(), io::ErrorKind::InvalidInput);
        assert!(library.export_files().is_empty());
    }
}
