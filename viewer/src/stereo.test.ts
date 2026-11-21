import { Texture, Vector3, type BufferGeometry } from 'three'
import { describe, expect, it } from 'vitest'
import { createHemisphereGeometry, createStereoScene, HEMISPHERE_RADIUS, type Eye } from './stereo'

function vertices(geometry: BufferGeometry): Vector3[] {
  const position = geometry.getAttribute('position')
  return Array.from({ length: position.count }, (_, i) => new Vector3().fromBufferAttribute(position, i))
}

function uvs(geometry: BufferGeometry): [number, number][] {
  const uv = geometry.getAttribute('uv')
  return Array.from({ length: uv.count }, (_, i) => [uv.getX(i), uv.getY(i)])
}

function vertexAtUv(geometry: BufferGeometry, u: number, v: number): Vector3 {
  const index = uvs(geometry).findIndex(([x, y]) => Math.abs(x - u) < 1e-6 && Math.abs(y - v) < 1e-6)
  expect(index).toBeGreaterThanOrEqual(0)
  return vertices(geometry)[index]
}

const EYES: Eye[] = ['left', 'right']

describe('createHemisphereGeometry', () => {
  it.each(EYES)('places the %s hemisphere in the front (-Z) half at the hemisphere radius', (eye) => {
    for (const p of vertices(createHemisphereGeometry(eye))) {
      expect(p.z).toBeLessThanOrEqual(1e-6)
      expect(p.length()).toBeCloseTo(HEMISPHERE_RADIUS, 3)
    }
  })

  it('maps the left hemisphere to the left half of the side-by-side texture', () => {
    const all = uvs(createHemisphereGeometry('left'))
    expect(Math.min(...all.map(([u]) => u))).toBeCloseTo(0)
    expect(Math.max(...all.map(([u]) => u))).toBeCloseTo(0.5)
  })

  it('maps the right hemisphere to the right half of the side-by-side texture', () => {
    const all = uvs(createHemisphereGeometry('right'))
    expect(Math.min(...all.map(([u]) => u))).toBeCloseTo(0.5)
    expect(Math.max(...all.map(([u]) => u))).toBeCloseTo(1)
  })

  it.each([
    ['left', 0.25],
    ['right', 0.75],
  ] as const)('shows the center of the %s eye image straight ahead', (eye, u) => {
    const p = vertexAtUv(createHemisphereGeometry(eye), u, 0.5).normalize()
    expect(p.x).toBeCloseTo(0)
    expect(p.y).toBeCloseTo(0)
    expect(p.z).toBeCloseTo(-1)
  })

  it.each([
    ['left', 0, 0.5, new Vector3(-1, 0, 0)],
    ['left', 0.5, 0.5, new Vector3(1, 0, 0)],
    ['right', 0.5, 0.5, new Vector3(-1, 0, 0)],
    ['right', 1, 0.5, new Vector3(1, 0, 0)],
    ['left', 0.25, 1, new Vector3(0, 1, 0)],
    ['left', 0.25, 0, new Vector3(0, -1, 0)],
  ] as const)('shows the %s eye texel at uv (%f, %f) towards %o without mirroring', (eye, u, v, expected) => {
    const p = vertexAtUv(createHemisphereGeometry(eye), u, v).normalize()
    expect(p.distanceTo(expected)).toBeLessThan(1e-6)
  })

  it('faces every triangle towards the viewer at the center', () => {
    const geometry = createHemisphereGeometry('left')
    const points = vertices(geometry)
    const index = geometry.getIndex()!.array
    for (let i = 0; i < index.length; i += 3) {
      const [a, b, c] = [points[index[i]], points[index[i + 1]], points[index[i + 2]]]
      const normal = new Vector3().subVectors(b, a).cross(new Vector3().subVectors(c, a))
      if (normal.lengthSq() < 1e-9) continue
      expect(normal.dot(a)).toBeLessThan(0)
    }
  })
})

describe('createStereoScene', () => {
  it('shows the left mesh only on layer 1 and the right mesh only on layer 2', () => {
    const { left, right } = createStereoScene(new Texture())

    expect(left.layers.mask).toBe(1 << 1)
    expect(right.layers.mask).toBe(1 << 2)
  })

  it('shows the left mesh to the right eye and the right mesh to the left eye when swapped', () => {
    const { left, right, setSwapped } = createStereoScene(new Texture())

    setSwapped(true)

    expect(left.layers.mask).toBe(1 << 2)
    expect(right.layers.mask).toBe(1 << 1)
  })

  it('restores each mesh to its own eye when unswapped', () => {
    const { left, right, setSwapped } = createStereoScene(new Texture())

    setSwapped(true)
    setSwapped(false)

    expect(left.layers.mask).toBe(1 << 1)
    expect(right.layers.mask).toBe(1 << 2)
  })

  it('shares one sRGB texture between both eyes', () => {
    const texture = new Texture()
    const { left, right } = createStereoScene(texture)

    expect(left.material).toHaveProperty('map', texture)
    expect(right.material).toHaveProperty('map', texture)
    expect(texture.colorSpace).toBe('srgb')
  })

  it('previews the left eye with the non-XR camera', () => {
    const { camera } = createStereoScene(new Texture())

    expect(camera.layers.mask).toBe(1 << 1)
  })
})
