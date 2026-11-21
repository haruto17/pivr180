use serde::{Deserialize, Serialize};
use std::f64::consts::FRAC_PI_2;

pub const FOCAL_LENGTH_UM: f64 = 1450.0;
pub const PIXEL_PITCH_UM: f64 = 1.55;

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct ImageCircle {
    pub center_x_px: f64,
    pub center_y_px: f64,
    pub radius_px: f64,
    pub rotation_deg: f64,
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;

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
