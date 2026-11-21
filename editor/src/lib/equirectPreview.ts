import type { ImageCircle } from "$lib/correction";

export type Angle = { lon: number; lat: number };

export function outputAngle(
  i: number,
  j: number,
  width: number,
  height: number,
): Angle {
  return {
    lon: -Math.PI / 2 + (Math.PI * (i + 0.5)) / width,
    lat: Math.PI / 2 - (Math.PI * (j + 0.5)) / height,
  };
}

export function sourceCoord(
  circle: ImageCircle,
  lon: number,
  lat: number,
): [number, number] {
  const x = Math.cos(lat) * Math.sin(lon);
  const y = Math.sin(lat);
  const z = Math.cos(lat) * Math.cos(lon);
  const theta = Math.acos(Math.min(1, Math.max(-1, z)));
  const alpha = Math.atan2(-y, x) + (circle.rotation_deg * Math.PI) / 180;
  const r = (circle.radius_px * theta) / (Math.PI / 2);
  return [
    circle.center_x_px + r * Math.cos(alpha),
    circle.center_y_px + r * Math.sin(alpha),
  ];
}

const VERTEX_SHADER = `
attribute vec2 position;

void main() {
  gl_Position = vec4(position, 0.0, 1.0);
}
`;

const FRAGMENT_SHADER = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif

uniform sampler2D source;
uniform vec2 sourceSize;
uniform vec2 outputSize;
uniform vec2 center;
uniform float radius;
uniform float rotation;

const float PI = 3.141592653589793;

void main() {
  vec2 pixel = vec2(gl_FragCoord.x - 0.5, outputSize.y - gl_FragCoord.y - 0.5);
  float lon = -PI / 2.0 + PI * (pixel.x + 0.5) / outputSize.x;
  float lat = PI / 2.0 - PI * (pixel.y + 0.5) / outputSize.y;
  vec3 d = vec3(cos(lat) * sin(lon), sin(lat), cos(lat) * cos(lon));
  float theta = acos(clamp(d.z, -1.0, 1.0));
  vec2 coord = center;
  // Not left to atan(0.0, 0.0) on the optical axis: GLSL leaves it undefined.
  if (theta > 0.0) {
    float alpha = atan(-d.y, d.x) + rotation;
    float r = radius * theta / (PI / 2.0);
    coord = center + r * vec2(cos(alpha), sin(alpha));
  }
  if (coord.x < 0.0 || coord.x >= sourceSize.x || coord.y < 0.0 || coord.y >= sourceSize.y) {
    gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0);
  } else {
    gl_FragColor = vec4(texture2D(source, coord / sourceSize).rgb, 1.0);
  }
}
`;

export type EquirectRenderer = {
  setImage(image: TexImageSource): void;
  draw(circle: ImageCircle, sourceWidth: number, sourceHeight: number): void;
  dispose(): void;
};

function compile(
  gl: WebGLRenderingContext,
  type: number,
  source: string,
): WebGLShader {
  const shader = gl.createShader(type)!;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(shader) ?? "shader compile failed");
  }
  return shader;
}

function webgl(canvas: HTMLCanvasElement): WebGLRenderingContext | null {
  try {
    return canvas.getContext("webgl");
  } catch {
    return null;
  }
}

export function createEquirectRenderer(
  canvas: HTMLCanvasElement,
): EquirectRenderer | null {
  const gl = webgl(canvas);
  if (!gl) return null;

  const program = gl.createProgram()!;
  gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX_SHADER));
  gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(program) ?? "shader link failed");
  }
  gl.useProgram(program);

  const buffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
  gl.bufferData(
    gl.ARRAY_BUFFER,
    new Float32Array([-1, -1, 3, -1, -1, 3]),
    gl.STATIC_DRAW,
  );
  const position = gl.getAttribLocation(program, "position");
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);

  const texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.uniform1i(gl.getUniformLocation(program, "source"), 0);

  const uniform = (name: string) => gl.getUniformLocation(program, name);
  const sourceSize = uniform("sourceSize");
  const outputSize = uniform("outputSize");
  const center = uniform("center");
  const radius = uniform("radius");
  const rotation = uniform("rotation");

  return {
    setImage(image) {
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texImage2D(
        gl.TEXTURE_2D,
        0,
        gl.RGB,
        gl.RGB,
        gl.UNSIGNED_BYTE,
        image,
      );
    },
    draw(circle, sourceWidth, sourceHeight) {
      const width = gl.drawingBufferWidth;
      const height = gl.drawingBufferHeight;
      gl.viewport(0, 0, width, height);
      gl.uniform2f(sourceSize, sourceWidth, sourceHeight);
      gl.uniform2f(outputSize, width, height);
      gl.uniform2f(center, circle.center_x_px, circle.center_y_px);
      gl.uniform1f(radius, circle.radius_px);
      gl.uniform1f(rotation, (circle.rotation_deg * Math.PI) / 180);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    },
    dispose() {
      gl.deleteTexture(texture);
      gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
    },
  };
}

export function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("画像を読み込めませんでした"));
    image.src = url;
  });
}
