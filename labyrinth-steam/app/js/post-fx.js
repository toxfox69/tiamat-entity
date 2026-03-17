// LABYRINTH 3D — Post-Processing Pipeline (Bloom + Color Grading)
// Self-contained, no Three.js addon dependencies
import * as THREE from 'three';

const FULLSCREEN_VS = `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const BRIGHT_EXTRACT_FS = `
uniform sampler2D tDiffuse;
uniform float threshold;
varying vec2 vUv;
void main() {
  vec4 c = texture2D(tDiffuse, vUv);
  float luma = dot(c.rgb, vec3(0.2126, 0.7152, 0.0722));
  float contrib = smoothstep(threshold - 0.1, threshold + 0.2, luma);
  gl_FragColor = vec4(c.rgb * contrib, 1.0);
}
`;

const BLUR_FS = `
uniform sampler2D tDiffuse;
uniform vec2 direction;
uniform vec2 resolution;
varying vec2 vUv;
void main() {
  vec2 texel = direction / resolution;
  vec3 r = vec3(0.0);
  r += texture2D(tDiffuse, vUv - 4.0 * texel).rgb * 0.0162;
  r += texture2D(tDiffuse, vUv - 3.0 * texel).rgb * 0.0540;
  r += texture2D(tDiffuse, vUv - 2.0 * texel).rgb * 0.1216;
  r += texture2D(tDiffuse, vUv - 1.0 * texel).rgb * 0.1945;
  r += texture2D(tDiffuse, vUv).rgb * 0.2270;
  r += texture2D(tDiffuse, vUv + 1.0 * texel).rgb * 0.1945;
  r += texture2D(tDiffuse, vUv + 2.0 * texel).rgb * 0.1216;
  r += texture2D(tDiffuse, vUv + 3.0 * texel).rgb * 0.0540;
  r += texture2D(tDiffuse, vUv + 4.0 * texel).rgb * 0.0162;
  gl_FragColor = vec4(r, 1.0);
}
`;

const COMPOSITE_FS = `
uniform sampler2D tScene;
uniform sampler2D tBloom;
uniform float bloomStrength;
uniform float exposure;
uniform float contrast;
uniform float saturation;
uniform float vignetteStrength;
uniform float time;
varying vec2 vUv;

vec3 ACESFilmic(vec3 x) {
  float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
  return clamp((x*(a*x+b))/(x*(c*x+d)+e), 0.0, 1.0);
}

void main() {
  vec3 scene = texture2D(tScene, vUv).rgb;
  vec3 bloom = texture2D(tBloom, vUv).rgb;

  vec3 color = scene + bloom * bloomStrength;

  // ACES tone mapping
  color = ACESFilmic(color * exposure);

  // Contrast
  color = (color - 0.5) * contrast + 0.5;

  // Saturation
  float luma = dot(color, vec3(0.2126, 0.7152, 0.0722));
  color = mix(vec3(luma), color, saturation);

  // Vignette
  vec2 uv = vUv * 2.0 - 1.0;
  float vig = 1.0 - dot(uv, uv) * vignetteStrength;
  vig = smoothstep(0.0, 1.0, vig);
  color *= vig;

  // Chromatic aberration (subtle)
  float aberr = 0.002;
  float rShift = texture2D(tScene, vUv + vec2(aberr, 0.0)).r;
  float bShift = texture2D(tScene, vUv - vec2(aberr, 0.0)).b;
  color.r = mix(color.r, rShift, 0.3);
  color.b = mix(color.b, bShift, 0.3);

  // Film grain
  float grain = (fract(sin(dot(vUv + time * 0.013, vec2(12.9898, 78.233))) * 43758.5453) - 0.5) * 0.025;
  color += grain;

  gl_FragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
}
`;

function makeRT(w, h) {
  return new THREE.WebGLRenderTarget(w, h, {
    minFilter: THREE.LinearFilter,
    magFilter: THREE.LinearFilter,
    format: THREE.RGBAFormat,
  });
}

function makeMat(fs, uniforms) {
  return new THREE.ShaderMaterial({
    vertexShader: FULLSCREEN_VS,
    fragmentShader: fs,
    uniforms,
    depthTest: false,
    depthWrite: false,
  });
}

export class PostFX {
  constructor(renderer, scene, camera) {
    this.renderer = renderer;
    this.scene = scene;
    this.camera = camera;
    this.enabled = true;

    const w = renderer.domElement.width;
    const h = renderer.domElement.height;
    const bw = Math.max(1, Math.floor(w / 4));
    const bh = Math.max(1, Math.floor(h / 4));

    this.sceneRT = makeRT(w, h);
    this.bloomRT1 = makeRT(bw, bh);
    this.bloomRT2 = makeRT(bw, bh);

    // Fullscreen quad
    this.quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2));
    this.quadScene = new THREE.Scene();
    this.quadCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    this.quadScene.add(this.quad);

    // Bright extract — low threshold to catch torches, trim, emissive surfaces
    this.brightMat = makeMat(BRIGHT_EXTRACT_FS, {
      tDiffuse: { value: null },
      threshold: { value: 0.45 },
    });

    // Blur passes
    this.hBlurMat = makeMat(BLUR_FS, {
      tDiffuse: { value: null },
      direction: { value: new THREE.Vector2(1.0, 0.0) },
      resolution: { value: new THREE.Vector2(bw, bh) },
    });
    this.vBlurMat = makeMat(BLUR_FS, {
      tDiffuse: { value: null },
      direction: { value: new THREE.Vector2(0.0, 1.0) },
      resolution: { value: new THREE.Vector2(bw, bh) },
    });

    // Composite
    this.compositeMat = makeMat(COMPOSITE_FS, {
      tScene: { value: null },
      tBloom: { value: null },
      bloomStrength: { value: 0.35 },
      exposure: { value: 1.0 },
      contrast: { value: 1.12 },
      saturation: { value: 1.15 },
      vignetteStrength: { value: 0.25 },
      time: { value: 0 },
    });
  }

  resize(w, h) {
    this.sceneRT.setSize(w, h);
    const bw = Math.max(1, Math.floor(w / 4));
    const bh = Math.max(1, Math.floor(h / 4));
    this.bloomRT1.setSize(bw, bh);
    this.bloomRT2.setSize(bw, bh);
    this.hBlurMat.uniforms.resolution.value.set(bw, bh);
    this.vBlurMat.uniforms.resolution.value.set(bw, bh);
  }

  render(time) {
    // Skip post-fx during XR
    if (!this.enabled || this.renderer.xr.isPresenting) {
      this.renderer.render(this.scene, this.camera);
      return;
    }

    const r = this.renderer;

    // 1. Render scene to RT
    r.setRenderTarget(this.sceneRT);
    r.render(this.scene, this.camera);

    // 2. Extract bright pixels → bloomRT1
    this.quad.material = this.brightMat;
    this.brightMat.uniforms.tDiffuse.value = this.sceneRT.texture;
    r.setRenderTarget(this.bloomRT1);
    r.render(this.quadScene, this.quadCamera);

    // 3. Blur pass 1: H → bloomRT2
    this.quad.material = this.hBlurMat;
    this.hBlurMat.uniforms.tDiffuse.value = this.bloomRT1.texture;
    r.setRenderTarget(this.bloomRT2);
    r.render(this.quadScene, this.quadCamera);

    // 4. Blur pass 1: V → bloomRT1
    this.quad.material = this.vBlurMat;
    this.vBlurMat.uniforms.tDiffuse.value = this.bloomRT2.texture;
    r.setRenderTarget(this.bloomRT1);
    r.render(this.quadScene, this.quadCamera);

    // 5. Blur pass 2: H → bloomRT2 (wider spread)
    this.hBlurMat.uniforms.tDiffuse.value = this.bloomRT1.texture;
    this.quad.material = this.hBlurMat;
    r.setRenderTarget(this.bloomRT2);
    r.render(this.quadScene, this.quadCamera);

    // 6. Blur pass 2: V → bloomRT1
    this.vBlurMat.uniforms.tDiffuse.value = this.bloomRT2.texture;
    this.quad.material = this.vBlurMat;
    r.setRenderTarget(this.bloomRT1);
    r.render(this.quadScene, this.quadCamera);

    // 7. Composite → screen
    this.quad.material = this.compositeMat;
    this.compositeMat.uniforms.tScene.value = this.sceneRT.texture;
    this.compositeMat.uniforms.tBloom.value = this.bloomRT1.texture;
    this.compositeMat.uniforms.time.value = time || 0;
    r.setRenderTarget(null);
    r.render(this.quadScene, this.quadCamera);
  }

  dispose() {
    this.sceneRT.dispose();
    this.bloomRT1.dispose();
    this.bloomRT2.dispose();
    this.brightMat.dispose();
    this.hBlurMat.dispose();
    this.vBlurMat.dispose();
    this.compositeMat.dispose();
    this.quad.geometry.dispose();
  }
}
