/**
 * 灵砚 · 流光 — 全局环境光层「月满中天」（中秋版）
 * 所有页面共享的一层 WebGL 月夜氛围：
 *   - 右上一轮满月：月面暗斑、柔光环，薄云缓缓掠过月面；
 *   - 青冥与桂金两缕流光在夜幕底色上缓慢游走；
 *   - 稀疏星子随呼吸明灭。
 * 设计守则：
 *   - 强度压低，只做氛围，不与正文争夺对比度；
 *   - 半分辨率渲染再拉伸，DPR ≤ 1.25；
 *   - 标签页隐藏即暂停；prefers-reduced-motion 只渲一帧静物；
 *   - 网关沉浸页（.gateway-scene）自带 inkflow.js 增强场景，此处自动让位。
 */
import * as THREE from 'three';

const canvas = document.getElementById('ambient-flow');
const el = canvas || document.createElement('canvas');

(function init() {
  // 网关沉浸页有自己的全幅流光场景，环境层退场
  if (document.querySelector('.gateway-scene')) return;

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!canvas) {
    el.id = 'ambient-flow';
    el.setAttribute('aria-hidden', 'true');
    document.body.prepend(el);
  }

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas: el, antialias: false, powerPreference: 'low-power' });
  } catch (e) {
    el.remove(); // WebGL 不可用：保留 .aurora CSS 光斑层即可
    return;
  }

  /* WebGL 生效：CSS 光斑收敛为辅衬 */
  document.querySelectorAll('.aurora').forEach((layer) => (layer.style.opacity = '0.6'));

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

  const uniforms = {
    u_time: { value: 0 },
    u_res:  { value: new THREE.Vector2(1, 1) },
  };

  const material = new THREE.ShaderMaterial({
    uniforms,
    fragmentShader: /* glsl */ `
      precision mediump float;
      uniform float u_time;
      uniform vec2  u_res;

      float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123); }

      float vnoise(vec2 p){
        vec2 i = floor(p), f = fract(p);
        vec2 u = f * f * (3.0 - 2.0 * f);
        return mix(
          mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
          mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x),
          u.y);
      }

      float fbm(vec2 p){
        float v = 0.0, a = 0.5;
        mat2 rot = mat2(0.8, 0.6, -0.6, 0.8);
        for(int k = 0; k < 4; k++){
          v += a * vnoise(p);
          p = rot * p * 2.03 + 7.3;
          a *= 0.5;
        }
        return v;
      }

      void main(){
        vec2 uv = gl_FragCoord.xy / u_res;
        float aspect = u_res.x / u_res.y;
        vec2 p = vec2(uv.x * aspect, uv.y);

        float t = u_time * 0.022;

        /* ---- 夜幕底色 ---- */
        vec3 col = mix(vec3(0.055, 0.033, 0.027), vec3(0.067, 0.040, 0.032), uv.y);

        /* ---- 星子：稀疏、呼吸明灭 ---- */
        vec2 cell = floor(p * 88.0);
        float starSeed = hash(cell);
        float star = step(0.9962, starSeed);
        float tw = 0.5 + 0.5 * sin(u_time * 2.1 + hash(cell + 7.0) * 43.0);
        col += vec3(1.00, 0.92, 0.78) * star * tw * 0.055;

        /* ---- 双层域扭曲 —— 缓慢的夜空水波 ---- */
        vec2 q = vec2(fbm(p * 1.15 + vec2(0.0, t)),
                      fbm(p * 1.15 + vec2(4.7, t * 1.27)));
        vec2 r = vec2(fbm(p * 1.45 + 2.6 * q + vec2(1.3, 6.9) + t * 0.5),
                      fbm(p * 1.45 + 2.6 * q + vec2(7.1, 2.4) - t * 0.34));
        float f = fbm(p * 1.25 + 2.0 * r);

        /* 两缕流光脊线：一青一桂金，错相位游走 */
        float ridgeA = pow(clamp(1.0 - abs(2.0 * f - 1.0), 0.0, 1.0), 8.0);
        float ridgeB = pow(clamp(1.0 - abs(2.0 * r.x - 1.0), 0.0, 1.0), 10.0);

        vec3 cinnabar = vec3(0.937, 0.447, 0.310);  /* 朱砂橘 */
        vec3 osm  = vec3(0.949, 0.812, 0.529);   /* 桂子金 */

        col += cinnabar * ridgeA * 0.050 * (0.55 + 0.45 * q.y);
        col += osm  * ridgeB * 0.044 * (0.50 + 0.50 * q.x);

        /* ---- 满月：右上悬一轮 ---- */
        vec2 mv = p - vec2(aspect * 0.80, 0.80);
        float md = length(mv);
        float mr = 0.098;

        /* 云纱：横向缓移的雾带，掠过月面时遮掩月光 */
        float wispRaw = fbm(vec2(p.x * 1.5 - t * 1.1, p.y * 5.0 + 3.0));
        float wisp = smoothstep(0.30, 0.62, wispRaw);
        float veil = smoothstep(mr + 0.16, mr - 0.02, md) * wisp;

        /* 月面：暖玉白（中秋月色）+ 暗斑纹理 */
        float disc = smoothstep(mr, mr - 0.010, md);
        float mote = fbm(mv * 13.0 + 3.7);
        vec3 moonCol = vec3(0.973, 0.933, 0.812) * (0.82 + 0.18 * mote);

        col = mix(col, moonCol * mix(1.0, 0.30, veil), disc * 0.92);

        /* 月晕：柔光外溢，云过时收敛 */
        float halo = exp(-max(md - mr, 0.0) * 8.5);
        col += vec3(0.93, 0.87, 0.70) * halo * 0.17 * mix(1.0, 0.40, wisp * 0.75);

        /* 暗角，把光收进画面里侧 */
        float vig = 1.0 - 0.42 * pow(length(uv - vec2(0.52, 0.5)) * 1.24, 2.0);
        col *= vig;

        gl_FragColor = vec4(col, 1.0);
      }
    `,
  });

  scene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material));

  /* 半分辨率渲染 —— 氛围层无需像素密度，换取稳定帧率 */
  const RES_SCALE = 0.5;
  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 1.25);
    const w = Math.max(1, Math.floor(window.innerWidth * dpr * RES_SCALE));
    const h = Math.max(1, Math.floor(window.innerHeight * dpr * RES_SCALE));
    renderer.setPixelRatio(1);
    renderer.setSize(w, h, false); // CSS 尺寸由 main.css 固定为全屏
    uniforms.u_res.value.set(w, h);
  };
  resize();
  window.addEventListener('resize', resize);

  let running = true;
  document.addEventListener('visibilitychange', () => {
    running = !document.hidden && !reduceMotion;
    if (running) requestAnimationFrame(loop);
  });

  const clock = new THREE.Clock();
  function loop() {
    if (!running) return;
    uniforms.u_time.value = clock.getElapsedTime();
    renderer.render(scene, camera);
    requestAnimationFrame(loop);
  }

  if (reduceMotion) {
    /* 减弱动效：只渲染一帧静物 */
    renderer.render(scene, camera);
  } else {
    requestAnimationFrame(loop);
  }
})();
