import {
  BufferGeometry,
  Float32BufferAttribute,
  Mesh,
  MeshBasicMaterial,
  PerspectiveCamera,
  Scene,
  SRGBColorSpace,
  TextureLoader,
  WebGLRenderer,
  type Texture,
} from 'three'

export type Eye = 'left' | 'right'

export const EYE_LAYER: Record<Eye, number> = { left: 1, right: 2 }

export const HEMISPHERE_RADIUS = 500

const SEGMENTS = 64

export function createHemisphereGeometry(eye: Eye, radius = HEMISPHERE_RADIUS): BufferGeometry {
  const uOffset = eye === 'left' ? 0 : 0.5
  const positions: number[] = []
  const uvs: number[] = []
  for (let row = 0; row <= SEGMENTS; row++) {
    const v = row / SEGMENTS
    const lat = Math.PI * (v - 0.5)
    for (let col = 0; col <= SEGMENTS; col++) {
      const u = col / SEGMENTS
      const lon = Math.PI * (u - 0.5)
      positions.push(
        radius * Math.cos(lat) * Math.sin(lon),
        radius * Math.sin(lat),
        -radius * Math.cos(lat) * Math.cos(lon),
      )
      uvs.push(uOffset + u / 2, v)
    }
  }
  const indices: number[] = []
  const stride = SEGMENTS + 1
  for (let row = 0; row < SEGMENTS; row++) {
    for (let col = 0; col < SEGMENTS; col++) {
      const a = row * stride + col
      const b = a + 1
      const c = a + stride
      const d = c + 1
      indices.push(a, b, d, a, d, c)
    }
  }
  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new Float32BufferAttribute(positions, 3))
  geometry.setAttribute('uv', new Float32BufferAttribute(uvs, 2))
  geometry.setIndex(indices)
  return geometry
}

export function createEyeMesh(eye: Eye, texture: Texture): Mesh {
  const mesh = new Mesh(createHemisphereGeometry(eye), new MeshBasicMaterial({ map: texture }))
  mesh.layers.set(EYE_LAYER[eye])
  return mesh
}

export interface StereoScene {
  scene: Scene
  camera: PerspectiveCamera
  left: Mesh
  right: Mesh
  dispose(): void
}

export function createStereoScene(texture: Texture, aspect = 1): StereoScene {
  texture.colorSpace = SRGBColorSpace
  const left = createEyeMesh('left', texture)
  const right = createEyeMesh('right', texture)
  const scene = new Scene()
  scene.add(left, right)
  const camera = new PerspectiveCamera(70, aspect, 0.1, HEMISPHERE_RADIUS * 2)
  camera.layers.set(EYE_LAYER.left)
  return {
    scene,
    camera,
    left,
    right,
    dispose() {
      for (const mesh of [left, right]) {
        mesh.geometry.dispose()
        ;(mesh.material as MeshBasicMaterial).dispose()
      }
      texture.dispose()
    },
  }
}

export function createRenderer(canvas: HTMLCanvasElement): WebGLRenderer {
  const renderer = new WebGLRenderer({ canvas, antialias: true })
  renderer.xr.enabled = true
  return renderer
}

export function loadTexture(url: string): Promise<Texture> {
  return new TextureLoader().loadAsync(url)
}
