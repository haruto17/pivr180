import { describe, expect, it } from "vitest";
import {
  createEquirectRenderer,
  outputAngle,
  sourceCoord,
} from "./equirectPreview";

const CIRCLE = {
  center_x_px: 205.3,
  center_y_px: 147.8,
  radius_px: 140,
  rotation_deg: 17,
};

function coord(
  circle: typeof CIRCLE,
  i: number,
  j: number,
  width: number,
  height: number,
) {
  const { lon, lat } = outputAngle(i, j, width, height);
  return sourceCoord(circle, lon, lat);
}

function expectClose(actual: [number, number], expected: [number, number]) {
  expect(actual[0]).toBeCloseTo(expected[0], 6);
  expect(actual[1]).toBeCloseTo(expected[1], 6);
}

describe("equirectPreview", () => {
  it("uses the angle at the center of each output pixel", () => {
    const first = outputAngle(0, 0, 4, 2);
    expect(first.lon).toBeCloseTo((-90 + 22.5) * (Math.PI / 180), 12);
    expect(first.lat).toBeCloseTo(45 * (Math.PI / 180), 12);
    const last = outputAngle(3, 1, 4, 2);
    expect(last.lon).toBeCloseTo((90 - 22.5) * (Math.PI / 180), 12);
    expect(last.lat).toBeCloseTo(-45 * (Math.PI / 180), 12);
  });

  it("maps the optical axis to the circle center", () => {
    expectClose(coord(CIRCLE, 64, 64, 129, 129), [205.3, 147.8]);
  });

  it("maps up, down, left and right to the edges of the circle", () => {
    const circle = { ...CIRCLE, rotation_deg: 0 };
    const r = (140 * 128) / 129;
    expectClose(coord(circle, 64, 0, 129, 129), [205.3, 147.8 - r]);
    expectClose(coord(circle, 64, 128, 129, 129), [205.3, 147.8 + r]);
    expectClose(coord(circle, 0, 64, 129, 129), [205.3 - r, 147.8]);
    expectClose(coord(circle, 128, 64, 129, 129), [205.3 + r, 147.8]);
  });

  it("sends up to the right of the circle when the image is rotated 90 degrees clockwise", () => {
    const circle = { ...CIRCLE, rotation_deg: 90 };
    expectClose(coord(circle, 64, 0, 129, 129), [205.3 + (140 * 128) / 129, 147.8]);
  });

  it("shifts every source coordinate by the center offset", () => {
    const shifted = { ...CIRCLE, center_x_px: 215.7, center_y_px: 141.1 };
    for (const [i, j] of [
      [10, 20],
      [64, 0],
      [100, 90],
    ]) {
      const [x, y] = coord(CIRCLE, i, j, 129, 129);
      expectClose(coord(shifted, i, j, 129, 129), [
        x + 215.7 - 205.3,
        y + 141.1 - 147.8,
      ]);
    }
  });

  it("returns no renderer when WebGL is unavailable", () => {
    const canvas = { getContext: () => null } as unknown as HTMLCanvasElement;
    expect(createEquirectRenderer(canvas)).toBeNull();
    const throwing = {
      getContext: () => {
        throw new Error("not implemented");
      },
    } as unknown as HTMLCanvasElement;
    expect(createEquirectRenderer(throwing)).toBeNull();
  });
});
