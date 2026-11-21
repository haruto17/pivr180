use crate::captures;
use serde::de::DeserializeOwned;
use serde::{Deserialize, Deserializer, Serialize};
use std::f64::consts::FRAC_PI_2;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, PoisonError};

pub const FOCAL_LENGTH_UM: f64 = 1450.0;
pub const PIXEL_PITCH_UM: f64 = 1.55;
pub const CAPTURE_WIDTH_PX: u32 = 4056;
pub const CAPTURE_HEIGHT_PX: u32 = 3040;

const SCHEMA_VERSION: u32 = 1;

static WRITE_LOCK: Mutex<()> = Mutex::new(());

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ImageCircle {
    pub center_x_px: f64,
    pub center_y_px: f64,
    pub radius_px: f64,
    pub rotation_deg: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct StereoCorrection {
    pub left: ImageCircle,
    pub right: ImageCircle,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CorrectionOverride {
    #[serde(
        default,
        deserialize_with = "present",
        skip_serializing_if = "Option::is_none"
    )]
    pub left: Option<ImageCircle>,
    #[serde(
        default,
        deserialize_with = "present",
        skip_serializing_if = "Option::is_none"
    )]
    pub right: Option<ImageCircle>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct Overridden {
    pub left: bool,
    pub right: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize)]
pub struct CaptureCorrection {
    pub left: ImageCircle,
    pub right: ImageCircle,
    pub overridden: Overridden,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum Scope {
    DeviceDefault,
    CaptureOverride,
}

impl Scope {
    fn name(self) -> &'static str {
        match self {
            Scope::DeviceDefault => "device_default",
            Scope::CaptureOverride => "capture_override",
        }
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CorrectionFile<C> {
    schema_version: u32,
    scope: Scope,
    cameras: C,
}

trait Cameras: Serialize + DeserializeOwned {
    fn validate(&self) -> io::Result<()>;
}

// Not a plain Option: it would also accept `null`, which the schema rejects.
fn present<'de, D: Deserializer<'de>>(deserializer: D) -> Result<Option<ImageCircle>, D::Error> {
    ImageCircle::deserialize(deserializer).map(Some)
}

fn invalid_input(message: String) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, message)
}

impl ImageCircle {
    fn validate(&self) -> io::Result<()> {
        let valid = self.center_x_px.is_finite()
            && self.center_x_px >= 0.0
            && self.center_y_px.is_finite()
            && self.center_y_px >= 0.0
            && self.radius_px.is_finite()
            && self.radius_px > 0.0
            && self.rotation_deg > -180.0
            && self.rotation_deg <= 180.0;
        if valid {
            Ok(())
        } else {
            Err(invalid_input(format!("補正値が範囲外です: {self:?}")))
        }
    }
}

impl Cameras for StereoCorrection {
    fn validate(&self) -> io::Result<()> {
        self.left.validate()?;
        self.right.validate()
    }
}

impl Cameras for CorrectionOverride {
    fn validate(&self) -> io::Result<()> {
        if self.left.is_none() && self.right.is_none() {
            return Err(invalid_input(
                "上書きするカメラが指定されていません".to_string(),
            ));
        }
        self.left
            .iter()
            .chain(&self.right)
            .try_for_each(ImageCircle::validate)
    }
}

pub fn equidistant_radius_px(theta_rad: f64) -> f64 {
    FOCAL_LENGTH_UM * theta_rad / PIXEL_PITCH_UM
}

pub fn initial_image_circle(width: u32, height: u32) -> ImageCircle {
    ImageCircle {
        center_x_px: f64::from(width) / 2.0,
        center_y_px: f64::from(height) / 2.0,
        radius_px: equidistant_radius_px(FRAC_PI_2),
        rotation_deg: 0.0,
    }
}

pub fn initial_correction() -> StereoCorrection {
    let circle = initial_image_circle(CAPTURE_WIDTH_PX, CAPTURE_HEIGHT_PX);
    StereoCorrection {
        left: circle,
        right: circle,
    }
}

fn device_default_path(corrections_dir: &Path) -> PathBuf {
    corrections_dir.join("device_default.json")
}

fn capture_override_path(corrections_dir: &Path, id: &str) -> io::Result<PathBuf> {
    captures::validate_id(id)?;
    Ok(corrections_dir.join("captures").join(format!("{id}.json")))
}

fn read_cameras<C: Cameras>(path: &Path, scope: Scope) -> io::Result<Option<C>> {
    let content = match fs::read_to_string(path) {
        Ok(content) => content,
        Err(e) if e.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(e) => return Err(e),
    };
    let invalid = |reason: String| {
        io::Error::new(
            io::ErrorKind::InvalidData,
            format!("補正値のファイルが不正です: {}: {reason}", path.display()),
        )
    };
    let file: CorrectionFile<C> =
        serde_json::from_str(&content).map_err(|e| invalid(e.to_string()))?;
    if file.schema_version != SCHEMA_VERSION {
        return Err(invalid(format!(
            "schema_version {} には対応していません",
            file.schema_version
        )));
    }
    if file.scope != scope {
        return Err(invalid(format!("scope が {} ではありません", scope.name())));
    }
    file.cameras
        .validate()
        .map_err(|e| invalid(e.to_string()))?;
    Ok(Some(file.cameras))
}

fn write_cameras<C: Cameras>(path: &Path, scope: Scope, cameras: C) -> io::Result<()> {
    cameras.validate()?;
    let content = serde_json::to_string_pretty(&CorrectionFile {
        schema_version: SCHEMA_VERSION,
        scope,
        cameras,
    })
    .map_err(io::Error::other)?;
    let _guard = WRITE_LOCK.lock().unwrap_or_else(PoisonError::into_inner);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    // Not fs::write(path): it truncates first, so a failed write would destroy the previous values.
    let tmp = path.with_extension("json.tmp");
    fs::write(&tmp, content)?;
    fs::rename(&tmp, path)
}

pub fn load_device_default(corrections_dir: &Path) -> io::Result<StereoCorrection> {
    Ok(
        read_cameras(&device_default_path(corrections_dir), Scope::DeviceDefault)?
            .unwrap_or_else(initial_correction),
    )
}

pub fn save_device_default(corrections_dir: &Path, correction: StereoCorrection) -> io::Result<()> {
    write_cameras(
        &device_default_path(corrections_dir),
        Scope::DeviceDefault,
        correction,
    )
}

pub fn load_capture_correction(corrections_dir: &Path, id: &str) -> io::Result<CaptureCorrection> {
    let path = capture_override_path(corrections_dir, id)?;
    let default = load_device_default(corrections_dir)?;
    let overrides: CorrectionOverride =
        read_cameras(&path, Scope::CaptureOverride)?.unwrap_or_default();
    Ok(CaptureCorrection {
        left: overrides.left.unwrap_or(default.left),
        right: overrides.right.unwrap_or(default.right),
        overridden: Overridden {
            left: overrides.left.is_some(),
            right: overrides.right.is_some(),
        },
    })
}

pub fn save_capture_override(
    corrections_dir: &Path,
    id: &str,
    overrides: CorrectionOverride,
) -> io::Result<()> {
    write_cameras(
        &capture_override_path(corrections_dir, id)?,
        Scope::CaptureOverride,
        overrides,
    )
}

pub fn clear_capture_override(corrections_dir: &Path, id: &str) -> io::Result<()> {
    let path = capture_override_path(corrections_dir, id)?;
    let _guard = WRITE_LOCK.lock().unwrap_or_else(PoisonError::into_inner);
    match fs::remove_file(path) {
        Err(e) if e.kind() != io::ErrorKind::NotFound => Err(e),
        _ => Ok(()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;
    use tempfile::tempdir;

    const ID: &str = "20260101-090000-000";
    const DEVICE_DEFAULT_EXAMPLE: &str =
        include_str!("../../../schema/examples/correction/device_default.json");
    const CAPTURE_OVERRIDE_EXAMPLE: &str =
        include_str!("../../../schema/examples/correction/capture_override.json");
    const RIGHT_ONLY_EXAMPLE: &str =
        include_str!("../../../schema/examples/correction/capture_override_right_only.json");

    fn circle(center_x_px: f64, rotation_deg: f64) -> ImageCircle {
        ImageCircle {
            center_x_px,
            center_y_px: 1500.0,
            radius_px: 1450.0,
            rotation_deg,
        }
    }

    fn device_default() -> StereoCorrection {
        StereoCorrection {
            left: circle(2000.0, 1.0),
            right: circle(2050.0, -1.0),
        }
    }

    fn override_file(dir: &Path, id: &str) -> PathBuf {
        dir.join("captures").join(format!("{id}.json"))
    }

    fn assert_same_json(actual: &serde_json::Value, expected: &serde_json::Value) {
        match (actual, expected) {
            (serde_json::Value::Object(a), serde_json::Value::Object(e)) => {
                assert_eq!(
                    a.keys().collect::<BTreeSet<_>>(),
                    e.keys().collect::<BTreeSet<_>>()
                );
                for (key, value) in a {
                    assert_same_json(value, &e[key]);
                }
            }
            (serde_json::Value::Number(a), serde_json::Value::Number(e)) => {
                assert_eq!(a.as_f64(), e.as_f64());
            }
            _ => assert_eq!(actual, expected),
        }
    }

    fn read_json(path: &Path) -> serde_json::Value {
        serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
    }

    #[test]
    fn device_default_is_initial_image_circle_on_both_sides_without_a_file() {
        let dir = tempdir().unwrap();
        let initial = initial_image_circle(4056, 3040);
        assert_eq!(
            load_device_default(dir.path()).unwrap(),
            StereoCorrection {
                left: initial,
                right: initial,
            }
        );
    }

    #[test]
    fn saved_device_default_is_loaded_back() {
        let dir = tempdir().unwrap();
        save_device_default(dir.path(), device_default()).unwrap();
        assert_eq!(load_device_default(dir.path()).unwrap(), device_default());
    }

    #[test]
    fn device_default_is_saved_under_corrections_without_leaving_temp_file() {
        let dir = tempdir().unwrap();
        save_device_default(dir.path(), initial_correction()).unwrap();
        save_device_default(dir.path(), device_default()).unwrap();
        let entries: Vec<_> = fs::read_dir(dir.path())
            .unwrap()
            .map(|entry| entry.unwrap().file_name())
            .collect();
        assert_eq!(entries, vec!["device_default.json"]);
        assert_eq!(load_device_default(dir.path()).unwrap(), device_default());
    }

    #[test]
    fn saved_device_default_has_the_shape_of_the_schema_example() {
        let dir = tempdir().unwrap();
        let example: serde_json::Value = serde_json::from_str(DEVICE_DEFAULT_EXAMPLE).unwrap();
        let left: ImageCircle = serde_json::from_value(example["cameras"]["left"].clone()).unwrap();
        let right: ImageCircle =
            serde_json::from_value(example["cameras"]["right"].clone()).unwrap();
        save_device_default(dir.path(), StereoCorrection { left, right }).unwrap();
        assert_same_json(
            &read_json(&dir.path().join("device_default.json")),
            &example,
        );
    }

    #[test]
    fn saved_capture_override_has_the_shape_of_the_schema_examples() {
        for example in [CAPTURE_OVERRIDE_EXAMPLE, RIGHT_ONLY_EXAMPLE] {
            let dir = tempdir().unwrap();
            let example: serde_json::Value = serde_json::from_str(example).unwrap();
            let overrides: CorrectionOverride =
                serde_json::from_value(example["cameras"].clone()).unwrap();
            save_capture_override(dir.path(), ID, overrides).unwrap();
            assert_same_json(&read_json(&override_file(dir.path(), ID)), &example);
        }
    }

    #[test]
    fn schema_example_files_are_loaded() {
        let dir = tempdir().unwrap();
        fs::write(
            dir.path().join("device_default.json"),
            DEVICE_DEFAULT_EXAMPLE,
        )
        .unwrap();
        fs::create_dir_all(dir.path().join("captures")).unwrap();
        fs::write(override_file(dir.path(), ID), RIGHT_ONLY_EXAMPLE).unwrap();

        let correction = load_capture_correction(dir.path(), ID).unwrap();

        assert_eq!(
            correction.left,
            ImageCircle {
                center_x_px: 2028.0,
                center_y_px: 1520.0,
                radius_px: 1469.5,
                rotation_deg: 0.0,
            }
        );
        assert_eq!(
            correction.right,
            ImageCircle {
                center_x_px: 2019.0,
                center_y_px: 1527.75,
                radius_px: 1466.5,
                rotation_deg: 1.2,
            }
        );
        assert_eq!(
            correction.overridden,
            Overridden {
                left: false,
                right: true,
            }
        );
    }

    #[test]
    fn device_default_applies_to_any_capture_without_override() {
        let dir = tempdir().unwrap();
        save_device_default(dir.path(), device_default()).unwrap();
        for id in [ID, "20260202-100000-123"] {
            assert_eq!(
                load_capture_correction(dir.path(), id).unwrap(),
                CaptureCorrection {
                    left: device_default().left,
                    right: device_default().right,
                    overridden: Overridden {
                        left: false,
                        right: false,
                    },
                }
            );
        }
    }

    #[test]
    fn capture_without_any_file_uses_initial_image_circle() {
        let dir = tempdir().unwrap();
        let correction = load_capture_correction(dir.path(), ID).unwrap();
        assert_eq!(correction.left, initial_image_circle(4056, 3040));
        assert_eq!(correction.right, initial_image_circle(4056, 3040));
    }

    #[test]
    fn override_replaces_only_the_cameras_it_has() {
        let dir = tempdir().unwrap();
        save_device_default(dir.path(), device_default()).unwrap();
        save_capture_override(
            dir.path(),
            ID,
            CorrectionOverride {
                left: Some(circle(2100.0, 3.0)),
                right: None,
            },
        )
        .unwrap();

        assert_eq!(
            load_capture_correction(dir.path(), ID).unwrap(),
            CaptureCorrection {
                left: circle(2100.0, 3.0),
                right: device_default().right,
                overridden: Overridden {
                    left: true,
                    right: false,
                },
            }
        );
        assert_eq!(
            load_capture_correction(dir.path(), "20260202-100000-123")
                .unwrap()
                .left,
            device_default().left
        );
    }

    #[test]
    fn override_follows_later_changes_to_device_default_for_cameras_it_lacks() {
        let dir = tempdir().unwrap();
        save_capture_override(
            dir.path(),
            ID,
            CorrectionOverride {
                left: None,
                right: Some(circle(2100.0, 3.0)),
            },
        )
        .unwrap();
        save_device_default(dir.path(), device_default()).unwrap();

        let correction = load_capture_correction(dir.path(), ID).unwrap();

        assert_eq!(correction.left, device_default().left);
        assert_eq!(correction.right, circle(2100.0, 3.0));
    }

    #[test]
    fn override_is_saved_per_capture_under_corrections_captures() {
        let dir = tempdir().unwrap();
        save_capture_override(
            dir.path(),
            ID,
            CorrectionOverride {
                left: Some(circle(2100.0, 3.0)),
                right: Some(circle(2000.0, 0.0)),
            },
        )
        .unwrap();
        let entries: Vec<_> = fs::read_dir(dir.path().join("captures"))
            .unwrap()
            .map(|entry| entry.unwrap().file_name())
            .collect();
        assert_eq!(entries, vec!["20260101-090000-000.json"]);
    }

    #[test]
    fn clearing_override_reverts_to_device_default() {
        let dir = tempdir().unwrap();
        save_device_default(dir.path(), device_default()).unwrap();
        save_capture_override(
            dir.path(),
            ID,
            CorrectionOverride {
                left: Some(circle(2100.0, 3.0)),
                right: Some(circle(2000.0, 0.0)),
            },
        )
        .unwrap();

        clear_capture_override(dir.path(), ID).unwrap();

        assert!(!override_file(dir.path(), ID).exists());
        assert_eq!(
            load_capture_correction(dir.path(), ID).unwrap(),
            CaptureCorrection {
                left: device_default().left,
                right: device_default().right,
                overridden: Overridden {
                    left: false,
                    right: false,
                },
            }
        );
    }

    #[test]
    fn clearing_missing_override_succeeds() {
        let dir = tempdir().unwrap();
        clear_capture_override(dir.path(), ID).unwrap();
    }

    #[test]
    fn empty_override_is_rejected_and_keeps_the_previous_one() {
        let dir = tempdir().unwrap();
        let previous = CorrectionOverride {
            left: Some(circle(2100.0, 3.0)),
            right: None,
        };
        save_capture_override(dir.path(), ID, previous).unwrap();

        let err = save_capture_override(dir.path(), ID, CorrectionOverride::default()).unwrap_err();

        assert_eq!(err.kind(), io::ErrorKind::InvalidInput);
        assert!(
            load_capture_correction(dir.path(), ID)
                .unwrap()
                .overridden
                .left
        );
    }

    #[test]
    fn invalid_capture_ids_are_rejected() {
        let dir = tempdir().unwrap();
        let overrides = CorrectionOverride {
            left: Some(circle(2100.0, 3.0)),
            right: None,
        };
        for id in ["", ".", "..", "../device_default", "a/b", "a\\b", "/etc"] {
            assert_eq!(
                load_capture_correction(dir.path(), id).unwrap_err().kind(),
                io::ErrorKind::InvalidInput,
                "{id:?}"
            );
            assert_eq!(
                save_capture_override(dir.path(), id, overrides)
                    .unwrap_err()
                    .kind(),
                io::ErrorKind::InvalidInput,
                "{id:?}"
            );
            assert_eq!(
                clear_capture_override(dir.path(), id).unwrap_err().kind(),
                io::ErrorKind::InvalidInput,
                "{id:?}"
            );
        }
        assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 0);
    }

    #[test]
    fn out_of_range_values_are_rejected_on_save() {
        let dir = tempdir().unwrap();
        let valid = circle(2000.0, 0.0);
        let invalid = [
            ImageCircle {
                center_x_px: -0.5,
                ..valid
            },
            ImageCircle {
                center_y_px: -1.0,
                ..valid
            },
            ImageCircle {
                radius_px: 0.0,
                ..valid
            },
            ImageCircle {
                radius_px: f64::INFINITY,
                ..valid
            },
            ImageCircle {
                rotation_deg: -180.0,
                ..valid
            },
            ImageCircle {
                rotation_deg: 180.5,
                ..valid
            },
            ImageCircle {
                rotation_deg: f64::NAN,
                ..valid
            },
        ];
        for circle in invalid {
            let err = save_device_default(
                dir.path(),
                StereoCorrection {
                    left: valid,
                    right: circle,
                },
            )
            .unwrap_err();
            assert_eq!(err.kind(), io::ErrorKind::InvalidInput, "{circle:?}");
            let err = save_capture_override(
                dir.path(),
                ID,
                CorrectionOverride {
                    left: Some(circle),
                    right: None,
                },
            )
            .unwrap_err();
            assert_eq!(err.kind(), io::ErrorKind::InvalidInput, "{circle:?}");
        }
        assert_eq!(fs::read_dir(dir.path()).unwrap().count(), 0);
    }

    #[test]
    fn boundary_values_allowed_by_the_schema_are_saved() {
        let dir = tempdir().unwrap();
        let edge = ImageCircle {
            center_x_px: 0.0,
            center_y_px: 0.0,
            radius_px: 0.001,
            rotation_deg: 180.0,
        };
        let correction = StereoCorrection {
            left: edge,
            right: edge,
        };
        save_device_default(dir.path(), correction).unwrap();
        assert_eq!(load_device_default(dir.path()).unwrap(), correction);
    }

    #[test]
    fn invalid_device_default_files_are_rejected_on_load() {
        let example: serde_json::Value = serde_json::from_str(DEVICE_DEFAULT_EXAMPLE).unwrap();
        let mutate = |f: &dyn Fn(&mut serde_json::Value)| {
            let mut value = example.clone();
            f(&mut value);
            value.to_string()
        };
        let cases = [
            "{".to_string(),
            "".to_string(),
            mutate(&|v| v["schema_version"] = 2.into()),
            mutate(&|v| v["scope"] = "capture_override".into()),
            mutate(&|v| v["scope"] = "other".into()),
            mutate(&|v| {
                v["cameras"].as_object_mut().unwrap().remove("right");
            }),
            mutate(&|v| v["cameras"]["left"]["radius_px"] = 0.into()),
            mutate(&|v| v["cameras"]["left"]["rotation_deg"] = (-180).into()),
            mutate(&|v| v["cameras"]["left"]["extra"] = 1.into()),
            mutate(&|v| v["cameras"]["center"] = v["cameras"]["left"].clone()),
            mutate(&|v| v["extra"] = 1.into()),
            mutate(&|v| {
                v.as_object_mut().unwrap().remove("schema_version");
            }),
        ];
        for content in cases {
            let dir = tempdir().unwrap();
            fs::write(dir.path().join("device_default.json"), &content).unwrap();
            assert_eq!(
                load_device_default(dir.path()).unwrap_err().kind(),
                io::ErrorKind::InvalidData,
                "{content}"
            );
            assert_eq!(
                load_capture_correction(dir.path(), ID).unwrap_err().kind(),
                io::ErrorKind::InvalidData,
                "{content}"
            );
        }
    }

    #[test]
    fn invalid_capture_override_files_are_rejected_on_load() {
        let example: serde_json::Value = serde_json::from_str(CAPTURE_OVERRIDE_EXAMPLE).unwrap();
        let mutate = |f: &dyn Fn(&mut serde_json::Value)| {
            let mut value = example.clone();
            f(&mut value);
            value.to_string()
        };
        let cases = [
            "not json".to_string(),
            mutate(&|v| v["schema_version"] = 0.into()),
            mutate(&|v| v["scope"] = "device_default".into()),
            mutate(&|v| v["cameras"] = serde_json::json!({})),
            mutate(&|v| v["cameras"]["left"] = serde_json::Value::Null),
            mutate(&|v| v["cameras"]["right"]["center_x_px"] = (-1).into()),
        ];
        for content in cases {
            let dir = tempdir().unwrap();
            fs::create_dir_all(dir.path().join("captures")).unwrap();
            fs::write(override_file(dir.path(), ID), &content).unwrap();
            assert_eq!(
                load_capture_correction(dir.path(), ID).unwrap_err().kind(),
                io::ErrorKind::InvalidData,
                "{content}"
            );
        }
    }

    #[test]
    fn full_resolution_capture_matches_device_default_example() {
        let circle = initial_image_circle(4056, 3040);
        assert_eq!(circle.center_x_px, 2028.0);
        assert_eq!(circle.center_y_px, 1520.0);
        assert!((circle.radius_px - 1469.5).abs() < 0.1);
        assert_eq!(circle.rotation_deg, 0.0);
    }

    #[test]
    fn radius_is_focal_length_times_quarter_turn_over_pixel_pitch() {
        let circle = initial_image_circle(4056, 3040);
        let expected = 1.45e-3 * (std::f64::consts::PI / 2.0) / 1.55e-6;
        assert!((circle.radius_px - expected).abs() < 1e-6);
    }

    #[test]
    fn equidistant_radius_is_proportional_to_angle() {
        assert!(
            (equidistant_radius_px(FRAC_PI_2 / 2.0) * 2.0 - equidistant_radius_px(FRAC_PI_2)).abs()
                < 1e-9
        );
    }

    #[test]
    fn radius_does_not_depend_on_image_size() {
        assert_eq!(
            initial_image_circle(2028, 1520).radius_px,
            initial_image_circle(4056, 3040).radius_px
        );
    }

    #[test]
    fn image_circle_fits_inside_full_resolution_capture() {
        let circle = initial_image_circle(4056, 3040);
        assert!(circle.radius_px * 2.0 <= 3040.0);
    }

    #[test]
    fn serializes_with_schema_image_circle_keys() {
        let value = serde_json::to_value(initial_image_circle(4056, 3040)).unwrap();
        let keys: BTreeSet<&str> = value
            .as_object()
            .unwrap()
            .keys()
            .map(String::as_str)
            .collect();

        let schema: serde_json::Value =
            serde_json::from_str(include_str!("../../../schema/correction.schema.json")).unwrap();
        let image_circle = &schema["$defs"]["image_circle"];
        let required: BTreeSet<&str> = image_circle["required"]
            .as_array()
            .unwrap()
            .iter()
            .map(|key| key.as_str().unwrap())
            .collect();
        let properties: BTreeSet<&str> = image_circle["properties"]
            .as_object()
            .unwrap()
            .keys()
            .map(String::as_str)
            .collect();

        assert_eq!(
            keys,
            BTreeSet::from(["center_x_px", "center_y_px", "radius_px", "rotation_deg"])
        );
        assert_eq!(keys, required);
        assert_eq!(keys, properties);
    }

    #[test]
    fn deserializes_device_default_example_camera() {
        let example: serde_json::Value = serde_json::from_str(include_str!(
            "../../../schema/examples/correction/device_default.json"
        ))
        .unwrap();
        let left: ImageCircle = serde_json::from_value(example["cameras"]["left"].clone()).unwrap();
        assert_eq!(
            left,
            ImageCircle {
                center_x_px: 2028.0,
                center_y_px: 1520.0,
                radius_px: 1469.5,
                rotation_deg: 0.0,
            }
        );
    }
}
