/**
 * 灵砚 · 流光 — 「月光流过砚池」
 * 松烟墨底上，青辉与朱砂两缕光带缓慢游走；鼠标搅动微漾。
 * 原生 WebGL 不可用时自动回退到 CSS 光斑层，页面不受影响。
 */
import * as THREE from 'three';

const canvas = document.getElementById('inkflow');
if (canvas) {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'low-power' });
  } catch (e) {
    canvas.remove(); // 回退：保留 .ink-drop CSS 光斑
  }

  if (renderer) {
    /* WebGL 生效：CSS 光斑回退层退场 */
    document.querySelectorAll('.ink-drop').forEach((el) => (el.style.display = 'none'));

    const scene = new THREE.Scene();
    const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);

    const uniforms = {
      u_time:  { value: 0 },
      u_res:   { value: new THREE.Vector2(1, 1) },
      u_mouse: { value: new THREE.Vector2(0.5, 0.5) },
    };

    const material = new THREE.ShaderMaterial({
      uniforms,
      fragmentShader: /* glsl */ `
        precision highp float;
        uniform float u_time;
        uniform vec2  u_res;
        uniform vec2  u_mouse;

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
          for(int k = 0; k < 5; k++){
            v += a * vnoise(p);
            p = rot * p * 2.03 + 11.7;
            a *= 0.52;
          }
          return v;
        }

        void main(){
          vec2 uv = gl_FragCoord.xy / u_res;
          vec2 p  = uv; p.x *= u_res.x / u_res.y;

          float t = u_time * 0.045;

          /* 鼠标轻搅：局部缓移采样域 */
          vec2 stir = (u_mouse - 0.5) * 0.22;
          p += stir * (0.4 + 0.6 * fbm(uv * 2.0));

          /* 双层域扭曲 —— 水面褶皱 */
          vec2 q = vec2(fbm(p * 1.35 + vec2(0.0, t)),
                        fbm(p * 1.35 + vec2(5.2, t * 1.3)));
          vec2 r = vec2(fbm(p * 1.75 + 3.0 * q + vec2(1.7, 9.2) + t * 0.55),
                        fbm(p * 1.75 + 3.0 * q + vec2(8.3, 2.8) - t * 0.38));
          float f = fbm(p * 1.55 + 2.4 * r);

          /* 青辉：宽域月光 */
          float moon = smoothstep(0.34, 0.88, f);
          /* 流光脊线：f 的山脊处光线最亮，像水面折光 */
          float ridge = pow(clamp(1.0 - abs(2.0 * f - 1.0), 0.0, 1.0), 7.0);

          /* 朱砂余烬：极细一缕，随 r.y 缓慢出没 */
          float ember = pow(max(r.y - 0.58, 0.0) * 2.2, 2.4);

          /* 底色：玄墨纵向微渐变 */
          vec3 col = mix(vec3(0.059, 0.082, 0.071), vec3(0.075, 0.102, 0.088), uv.y);

          vec3 azure   = vec3(0.369, 0.561, 0.639);   /* 石青 */
          vec3 moonHi  = vec3(0.612, 0.769, 0.831);   /* 月白青 */
          vec3 cinnabr = vec3(0.816, 0.286, 0.231);   /* 朱砂 */

          col += azure * moon * 0.20;
          col += moonHi * ridge * (0.16 + 0.38 * q.x) * moon;
          col += cinnabr * ember * 0.42;

          /* 暗角 + 胶片颗粒 */
          float vig = 1.0 - 0.5 * pow(length(uv - 0.5) * 1.28, 2.1);
          col *= vig;
          col += (hash(gl_FragCoord.xy + fract(u_time)) - 0.5) * 0.018;

          gl_FragColor = vec4(col, 1.0);
        }
      `,
    });

    scene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material));

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      renderer.setPixelRatio(dpr);
      renderer.setSize(window.innerWidth, window.innerHeight);
      uniforms.u_res.value.set(
        window.innerWidth * dpr,
        window.innerHeight * dpr,
      );
    };
    resize();
    window.addEventListener('resize', resize);

    /* 鼠标平滑跟随 */
    const target = new THREE.Vector2(0.5, 0.5);
    window.addEventListener('pointermove', (e) => {
      target.set(e.clientX / window.innerWidth, 1 - e.clientY / window.innerHeight);
    });

    let running = true;
    document.addEventListener('visibilitychange', () => {
      running = !document.hidden && !reduceMotion;
      if (running) requestAnimationFrame(loop);
    });

    const clock = new THREE.Clock();
    function loop() {
      if (!running) return;
      uniforms.u_time.value = clock.getElapsedTime();
      uniforms.u_mouse.value.lerp(target, 0.04);
      renderer.render(scene, camera);
      requestAnimationFrame(loop);
    }

    if (reduceMotion) {
      /* 减弱动效：只渲染一帧静物 */
      uniforms.u_mouse.value.copy(target);
      renderer.render(scene, camera);
    } else {
      requestAnimationFrame(loop);
    }
  }
}
