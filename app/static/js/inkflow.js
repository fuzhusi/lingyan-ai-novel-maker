/**
 * 灵砚 · 流光 — 网关沉浸场景「月满中天 · 桂香盈砚」（中秋版）
 * 光效分层：
 *   1. 夜幕底色 + 星子呼吸明灭；
 *   2. 一轮满月悬于右上天际：月面暗斑、柔光环，薄云缓缓掠过；
 *   3. 青冥与桂金两缕流光脊线在水面游走，霞金余烬点睛；
 *   4. 光尘自下而上漂浮闪烁；一场桂花金的细雨自上而下飘落。
 * 鼠标轻搅微漾。WebGL 不可用时自动回退到 CSS 光斑层。
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

    /* ---- 流光场（全屏片元着色） ---- */
    const flowMaterial = new THREE.ShaderMaterial({
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
          float aspect = u_res.x / u_res.y;
          vec2 p = uv; p.x *= aspect;

          float t = u_time * 0.045;

          /* ---- 夜幕底色 ---- */
          vec3 col = mix(vec3(0.022, 0.036, 0.078), vec3(0.030, 0.049, 0.098), uv.y);

          /* ---- 星子 ---- */
          vec2 cell = floor(p * 95.0);
          float starSeed = hash(cell);
          float star = step(0.9960, starSeed);
          float tw = 0.5 + 0.5 * sin(u_time * 2.0 + hash(cell + 7.0) * 47.0);
          col += vec3(0.90, 0.94, 1.00) * star * tw * 0.06;

          /* 鼠标轻搅：局部缓移采样域 */
          vec2 stir = (u_mouse - 0.5) * 0.22;
          vec2 ps = p + stir * (0.4 + 0.6 * fbm(uv * 2.0));

          /* 双层域扭曲 —— 水面褶皱 */
          vec2 q = vec2(fbm(ps * 1.35 + vec2(0.0, t)),
                        fbm(ps * 1.35 + vec2(5.2, t * 1.3)));
          vec2 r = vec2(fbm(ps * 1.75 + 3.0 * q + vec2(1.7, 9.2) + t * 0.55),
                        fbm(ps * 1.75 + 3.0 * q + vec2(8.3, 2.8) - t * 0.38));
          float f = fbm(ps * 1.55 + 2.4 * r);

          float moon = smoothstep(0.34, 0.88, f);
          float ridge = pow(clamp(1.0 - abs(2.0 * f - 1.0), 0.0, 1.0), 7.0);
          float ridgeG = pow(clamp(1.0 - abs(2.0 * r.x - 1.0), 0.0, 1.0), 10.0);

          /* 桂金余烬：极细一缕，随 r.y 缓慢出没 */
          float ember = pow(max(r.y - 0.58, 0.0) * 2.2, 2.4);

          vec3 cyan   = vec3(0.365, 0.827, 0.945);   /* 流光青 */
          vec3 moonHi = vec3(0.769, 0.902, 0.973);   /* 月白青 */
          vec3 osm    = vec3(0.949, 0.812, 0.529);   /* 桂子金 */
          vec3 emberC = vec3(0.949, 0.788, 0.475);   /* 霞金   */

          col += cyan   * moon * 0.20;
          col += moonHi * ridge * (0.16 + 0.38 * q.x) * moon;
          col += osm    * ridgeG * (0.11 + 0.20 * q.y);
          col += emberC * ember * 0.34;

          /* ---- 满月：右上天际悬一轮 ---- */
          vec2 mv = p - vec2(aspect * 0.76, 0.82);
          float md = length(mv);
          float mr = 0.125;

          /* 云纱掠月 */
          float wispRaw = fbm(vec2(p.x * 1.4 - t * 0.9, p.y * 4.6 + 3.0));
          float wisp = smoothstep(0.30, 0.64, wispRaw);
          float veil = smoothstep(mr + 0.20, mr - 0.02, md) * wisp;

          /* 月面：暖玉白（中秋月色）+ 暗斑（环山桂影） */
          float disc = smoothstep(mr, mr - 0.012, md);
          float mote = fbm(mv * 11.0 + 3.7) * 0.7 + fbm(mv * 23.0 + 9.1) * 0.3;
          vec3 moonCol = vec3(0.976, 0.936, 0.816) * (0.80 + 0.20 * mote);

          /* 月缘一圈更亮的边，像月光透出云层 */
          float rim = smoothstep(mr - 0.05, mr - 0.004, md) * smoothstep(mr + 0.012, mr - 0.002, md);

          col = mix(col, moonCol * mix(1.0, 0.28, veil), disc * 0.94);
          col += vec3(0.99, 0.94, 0.78) * rim * 0.16 * mix(1.0, 0.35, veil);

          /* 月晕 */
          float halo = exp(-max(md - mr, 0.0) * 7.0);
          col += vec3(0.93, 0.87, 0.70) * halo * 0.20 * mix(1.0, 0.38, wisp * 0.7);

          /* 暗角 + 胶片颗粒 */
          float vig = 1.0 - 0.5 * pow(length(uv - vec2(0.52, 0.5)) * 1.28, 2.1);
          col *= vig;
          col += (hash(gl_FragCoord.xy + fract(u_time)) - 0.5) * 0.018;

          gl_FragColor = vec4(col, 1.0);
        }
      `,
    });

    scene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), flowMaterial));

    /* ---- 共享时间 uniform ---- */

    /* ---- 光尘粒子：自下而上漂浮、闪烁 ---- */
    const DUST_COUNT = 130;
    const dustPositions = new Float32Array(DUST_COUNT * 3);
    const dustSeeds = new Float32Array(DUST_COUNT * 3);
    for (let i = 0; i < DUST_COUNT; i++) {
      dustPositions[i * 3 + 0] = Math.random() * 2.4 - 1.2;
      dustPositions[i * 3 + 1] = 0;
      dustPositions[i * 3 + 2] = 0;
      dustSeeds[i * 3 + 0] = Math.random();
      dustSeeds[i * 3 + 1] = Math.random();
      dustSeeds[i * 3 + 2] = Math.random();
    }

    const makePoints = (count, positions, seeds, vertexSizeExpr, colorMode) => {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.BufferAttribute(positions, 3));
      g.setAttribute('seed', new THREE.BufferAttribute(seeds, 3));
      const m = new THREE.ShaderMaterial({
        uniforms: { u_time: uniforms.u_time, u_dpr: { value: 1 } },
        transparent: true,
        depthTest: false,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        vertexShader: /* glsl */ `
          attribute vec3 seed;
          uniform float u_time;
          uniform float u_dpr;
          varying float v_alpha;
          varying vec3  v_color;

          void main(){
            ${colorMode === 'fall'
              ? `/* 桂花雨：自上而下飘落 */
                 float life = fract(seed.x - u_time * (0.010 + 0.013 * seed.y));
                 vec3 pos = position;
                 pos.y = mix(1.12, -0.12, life);
                 pos.x += sin(u_time * (0.35 + 0.5 * seed.y) + seed.x * 51.0) * 0.032;
                 float env = smoothstep(0.0, 0.14, life) * (1.0 - smoothstep(0.86, 1.0, life));
                 float twk = 0.66 + 0.34 * sin(u_time * (1.2 + 1.8 * seed.z) + seed.x * 83.0);
                 v_alpha = env * twk * (0.42 + 0.50 * seed.y);
                 v_color = mix(vec3(0.949, 0.788, 0.475), vec3(1.0, 0.925, 0.70), seed.z);`
              : `/* 光尘：自下而上漂浮 */
                 float life = fract(seed.x + u_time * (0.008 + 0.016 * seed.y));
                 vec3 pos = position;
                 pos.y = mix(-0.14, 1.14, life);
                 pos.x += sin(u_time * (0.25 + 0.5 * seed.y) + seed.x * 43.0) * 0.025;
                 float env = smoothstep(0.0, 0.18, life) * (1.0 - smoothstep(0.82, 1.0, life));
                 float twk = 0.62 + 0.38 * sin(u_time * (1.4 + 2.2 * seed.z) + seed.x * 91.0);
                 v_alpha = env * twk * (0.26 + 0.58 * seed.y);
                 /* 青 → 暮紫过渡，少数桂金星尘 */
                 v_color = mix(vec3(0.365, 0.827, 0.945), vec3(0.655, 0.545, 0.980), smoothstep(0.5, 0.95, seed.z));
                 if (seed.z < 0.14) v_color = vec3(0.984, 0.859, 0.639);`}
            gl_Position = vec4(pos.xy, 0.0, 1.0);
            gl_PointSize = ${vertexSizeExpr} * u_dpr;
          }
        `,
        fragmentShader: /* glsl */ `
          precision mediump float;
          varying float v_alpha;
          varying vec3  v_color;

          void main(){
            vec2 c = gl_PointCoord - 0.5;
            float d = length(c);
            float halo = smoothstep(0.5, 0.04, d);
            float a = halo * v_alpha * 0.85;
            gl_FragColor = vec4(v_color * a, a);
          }
        `,
      });
      return new THREE.Points(g, m);
    };

    const dust = makePoints(
      DUST_COUNT, dustPositions, dustSeeds,
      '(1.6 + 2.8 * seed.y)', 'rise',
    );

    /* ---- 桂花雨：金屑自上而下 ---- */
    const PETAL_COUNT = 46;
    const petalPositions = new Float32Array(PETAL_COUNT * 3);
    const petalSeeds = new Float32Array(PETAL_COUNT * 3);
    for (let i = 0; i < PETAL_COUNT; i++) {
      petalPositions[i * 3 + 0] = Math.random() * 2.4 - 1.2;
      petalPositions[i * 3 + 1] = 0;
      petalPositions[i * 3 + 2] = 0;
      petalSeeds[i * 3 + 0] = Math.random();
      petalSeeds[i * 3 + 1] = Math.random();
      petalSeeds[i * 3 + 2] = Math.random();
    }
    const petals = makePoints(
      PETAL_COUNT, petalPositions, petalSeeds,
      '(2.4 + 3.6 * seed.y)', 'fall',
    );

    scene.add(dust);
    scene.add(petals);

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      renderer.setPixelRatio(dpr);
      dust.material.uniforms.u_dpr.value = dpr;
      petals.material.uniforms.u_dpr.value = dpr;
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
