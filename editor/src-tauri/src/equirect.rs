use crate::correction::ImageCircle;
use image::RgbImage;
use rayon::prelude::*;
use std::f64::consts::{FRAC_PI_2, PI};
use std::fmt;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SizeMismatch {
    pub expected: (u32, u32),
    pub actual: (u32, u32),
}

impl fmt::Display for SizeMismatch {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "source image is {}x{}, but the conversion table was built for {}x{}",
            self.actual.0, self.actual.1, self.expected.0, self.expected.1
        )
    }
}

impl std::error::Error for SizeMismatch {}

pub struct Lut {
    src_w: u32,
    src_h: u32,
    out_w: u32,
    out_h: u32,
    // f32, not f64: halves the table (~66MB at 2880x2880) and still resolves ~1/4000 px at 4056 px.
    coords: Vec<[f32; 2]>,
}

impl Lut {
    pub fn new(circle: &ImageCircle, src_w: u32, src_h: u32, out_w: u32, out_h: u32) -> Self {
        let mut coords = vec![[0.0; 2]; out_w as usize * out_h as usize];
        coords
            .par_chunks_mut(out_w.max(1) as usize)
            .enumerate()
            .for_each(|(j, row)| {
                let lat = FRAC_PI_2 - PI * (j as f64 + 0.5) / f64::from(out_h);
                for (i, coord) in row.iter_mut().enumerate() {
                    let lon = -FRAC_PI_2 + PI * (i as f64 + 0.5) / f64::from(out_w);
                    let (x, y) = source_coord(circle, lon, lat);
                    *coord = [x as f32, y as f32];
                }
            });
        Self {
            src_w,
            src_h,
            out_w,
            out_h,
            coords,
        }
    }

    pub fn remap(&self, src: &RgbImage) -> Result<RgbImage, SizeMismatch> {
        if src.dimensions() != (self.src_w, self.src_h) {
            return Err(SizeMismatch {
                expected: (self.src_w, self.src_h),
                actual: src.dimensions(),
            });
        }
        let mut out = RgbImage::new(self.out_w, self.out_h);
        let row_len = self.out_w.max(1) as usize;
        out.par_chunks_mut(row_len * 3)
            .zip(self.coords.par_chunks(row_len))
            .for_each(|(row, coords)| {
                for (pixel, &[x, y]) in row.as_chunks_mut::<3>().0.iter_mut().zip(coords) {
                    if let Some(rgb) = sample(src, x, y) {
                        *pixel = rgb;
                    }
                }
            });
        Ok(out)
    }
}

fn source_coord(circle: &ImageCircle, lon: f64, lat: f64) -> (f64, f64) {
    let x = lat.cos() * lon.sin();
    let y = lat.sin();
    let z = lat.cos() * lon.cos();
    let theta = z.clamp(-1.0, 1.0).acos();
    let alpha = (-y).atan2(x) + circle.rotation_deg.to_radians();
    let r = circle.radius_px * theta / FRAC_PI_2;
    (
        circle.center_x_px + r * alpha.cos(),
        circle.center_y_px + r * alpha.sin(),
    )
}

fn sample(src: &RgbImage, x: f32, y: f32) -> Option<[u8; 3]> {
    let (w, h) = src.dimensions();
    if !(x >= 0.0 && x < w as f32 && y >= 0.0 && y < h as f32) {
        return None;
    }
    // Neighbors are clamped rather than treated as black, so the image edge gets no dark fringe.
    let u = (x - 0.5).max(0.0);
    let v = (y - 0.5).max(0.0);
    let x0 = (u as u32).min(w - 1);
    let y0 = (v as u32).min(h - 1);
    let x1 = (x0 + 1).min(w - 1);
    let y1 = (y0 + 1).min(h - 1);
    let fx = (u - x0 as f32).min(1.0);
    let fy = (v - y0 as f32).min(1.0);
    let raw = src.as_raw();
    let at = |px: u32, py: u32, c: usize| {
        f32::from(raw[(py as usize * w as usize + px as usize) * 3 + c])
    };
    let mut rgb = [0; 3];
    for (c, value) in rgb.iter_mut().enumerate() {
        let top = at(x0, y0, c) * (1.0 - fx) + at(x1, y0, c) * fx;
        let bottom = at(x0, y1, c) * (1.0 - fx) + at(x1, y1, c) * fx;
        *value = (top * (1.0 - fy) + bottom * fy).round() as u8;
    }
    Some(rgb)
}

#[cfg(test)]
mod tests {
    use super::*;

    const CIRCLE: ImageCircle = ImageCircle {
        center_x_px: 205.3,
        center_y_px: 147.8,
        radius_px: 140.0,
        rotation_deg: 17.0,
    };

    fn direction(lon: f64, lat: f64) -> [f64; 3] {
        [lat.cos() * lon.sin(), lat.sin(), lat.cos() * lon.cos()]
    }

    fn output_direction(out_w: u32, out_h: u32, i: u32, j: u32) -> [f64; 3] {
        let lon = -FRAC_PI_2 + PI * (f64::from(i) + 0.5) / f64::from(out_w);
        let lat = FRAC_PI_2 - PI * (f64::from(j) + 0.5) / f64::from(out_h);
        direction(lon, lat)
    }

    fn render_fisheye(
        circle: &ImageCircle,
        w: u32,
        h: u32,
        pattern: impl Fn([f64; 3]) -> [f64; 3],
    ) -> RgbImage {
        RgbImage::from_fn(w, h, |x, y| {
            let dx = f64::from(x) + 0.5 - circle.center_x_px;
            let dy = f64::from(y) + 0.5 - circle.center_y_px;
            let theta = dx.hypot(dy) / circle.radius_px * FRAC_PI_2;
            let alpha = dy.atan2(dx) - circle.rotation_deg.to_radians();
            let d = [
                theta.sin() * alpha.cos(),
                -theta.sin() * alpha.sin(),
                theta.cos(),
            ];
            image::Rgb(pattern(d).map(|v| v.round().clamp(0.0, 255.0) as u8))
        })
    }

    fn smooth_pattern(d: [f64; 3]) -> [f64; 3] {
        [
            127.5 + 100.0 * d[0],
            127.5 + 100.0 * d[1],
            127.5 + 100.0 * (2.0 * d[0] * d[1] + 0.2 * d[2]),
        ]
    }

    fn coord(lut: &Lut, i: u32, j: u32) -> (f64, f64) {
        let [x, y] = lut.coords[(j * lut.out_w + i) as usize];
        (f64::from(x), f64::from(y))
    }

    fn assert_close(actual: (f64, f64), expected: (f64, f64)) {
        assert!(
            (actual.0 - expected.0).abs() < 1e-3 && (actual.1 - expected.1).abs() < 1e-3,
            "{actual:?} != {expected:?}"
        );
    }

    #[test]
    fn synthetic_fisheye_converts_within_mean_error_0_5_and_max_error_2() {
        let src = render_fisheye(&CIRCLE, 400, 300, smooth_pattern);
        let lut = Lut::new(&CIRCLE, 400, 300, 128, 128);
        let out = lut.remap(&src).unwrap();

        let mut sum = 0.0;
        let mut max: f64 = 0.0;
        for (i, j, pixel) in out.enumerate_pixels() {
            let expected = smooth_pattern(output_direction(128, 128, i, j));
            for (&actual, expected) in pixel.0.iter().zip(expected) {
                let error = (f64::from(actual) - expected).abs();
                sum += error;
                max = max.max(error);
            }
        }
        let mean = sum / (128.0 * 128.0 * 3.0);
        assert!(mean < 0.5, "mean abs error {mean}");
        assert!(max < 2.0, "max abs error {max}");
    }

    #[test]
    fn optical_axis_maps_to_output_center() {
        let lut = Lut::new(&CIRCLE, 400, 300, 129, 129);
        assert_close(coord(&lut, 64, 64), (205.3, 147.8));
    }

    #[test]
    fn up_left_right_and_down_map_to_output_edges() {
        let circle = ImageCircle {
            rotation_deg: 0.0,
            ..CIRCLE
        };
        let lut = Lut::new(&circle, 400, 300, 129, 129);
        let r = 140.0 * 128.0 / 129.0;
        assert_close(coord(&lut, 64, 0), (205.3, 147.8 - r));
        assert_close(coord(&lut, 64, 128), (205.3, 147.8 + r));
        assert_close(coord(&lut, 0, 64), (205.3 - r, 147.8));
        assert_close(coord(&lut, 128, 64), (205.3 + r, 147.8));
    }

    #[test]
    fn clockwise_rotation_moves_up_to_the_right_of_the_fisheye_image() {
        let circle = ImageCircle {
            rotation_deg: 90.0,
            ..CIRCLE
        };
        let lut = Lut::new(&circle, 400, 300, 129, 129);
        assert_close(coord(&lut, 64, 0), (205.3 + 140.0 * 128.0 / 129.0, 147.8));
    }

    #[test]
    fn marker_lands_within_quarter_pixel_of_its_direction_regardless_of_center_offset_and_rotation()
    {
        let (lon, lat) = (30f64.to_radians(), 20f64.to_radians());
        let marker = direction(lon, lat);
        let sigma = 3f64.to_radians();
        let pattern = |d: [f64; 3]| {
            let cos = (d[0] * marker[0] + d[1] * marker[1] + d[2] * marker[2]).clamp(-1.0, 1.0);
            let angle = cos.acos();
            [
                255.0 * (-angle * angle / (2.0 * sigma * sigma)).exp(),
                0.0,
                0.0,
            ]
        };
        let expected_i = (lon + FRAC_PI_2) / PI * 129.0 - 0.5;
        let expected_j = (FRAC_PI_2 - lat) / PI * 129.0 - 0.5;

        for (center_x_px, center_y_px, rotation_deg) in [
            (200.0, 150.0, 0.0),
            (190.4, 160.2, 90.0),
            (215.7, 141.1, -35.0),
        ] {
            let circle = ImageCircle {
                center_x_px,
                center_y_px,
                radius_px: 140.0,
                rotation_deg,
            };
            let src = render_fisheye(&circle, 400, 300, pattern);
            let out = Lut::new(&circle, 400, 300, 129, 129).remap(&src).unwrap();

            let (mut weight, mut sum_i, mut sum_j) = (0.0, 0.0, 0.0);
            for (i, j, pixel) in out.enumerate_pixels() {
                let w = f64::from(pixel.0[0]);
                weight += w;
                sum_i += w * f64::from(i);
                sum_j += w * f64::from(j);
            }
            let (i, j) = (sum_i / weight, sum_j / weight);
            assert!(
                (i - expected_i).abs() < 0.25 && (j - expected_j).abs() < 0.25,
                "circle {circle:?}: marker at ({i}, {j}), expected ({expected_i}, {expected_j})"
            );
        }
    }

    #[test]
    fn output_has_requested_size() {
        let src = RgbImage::new(400, 300);
        let out = Lut::new(&CIRCLE, 400, 300, 96, 64).remap(&src).unwrap();
        assert_eq!(out.dimensions(), (96, 64));
    }

    #[test]
    fn samples_outside_source_image_are_black() {
        let circle = ImageCircle {
            center_x_px: 10.0,
            center_y_px: 50.0,
            radius_px: 80.0,
            rotation_deg: 0.0,
        };
        let src = RgbImage::from_pixel(100, 100, image::Rgb([255; 3]));
        let out = Lut::new(&circle, 100, 100, 65, 65).remap(&src).unwrap();
        assert_eq!(out.get_pixel(0, 32).0, [0; 3]);
        assert_eq!(out.get_pixel(32, 32).0, [255; 3]);
        assert_eq!(out.get_pixel(64, 32).0, [255; 3]);
    }

    #[test]
    fn sample_inside_the_edge_pixels_is_not_darkened() {
        let src = RgbImage::from_pixel(4, 3, image::Rgb([200; 3]));
        assert_eq!(sample(&src, 0.1, 0.1), Some([200; 3]));
        assert_eq!(sample(&src, 3.9, 2.9), Some([200; 3]));
        assert_eq!(sample(&src, -0.1, 1.0), None);
        assert_eq!(sample(&src, 1.0, 3.0), None);
    }

    #[test]
    fn source_of_another_size_is_rejected() {
        let lut = Lut::new(&CIRCLE, 400, 300, 64, 64);
        assert_eq!(
            lut.remap(&RgbImage::new(300, 400)).unwrap_err(),
            SizeMismatch {
                expected: (400, 300),
                actual: (300, 400),
            }
        );
    }
}
