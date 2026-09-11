/* CFD 物理图像渲染引擎 —— 前端（零外部依赖，原生 WebGL + Canvas）。
 * 数据来自 cfd-npy3d HTTP 桥的 /api/* 端点；支持格式见 /api/formats。
 */
'use strict';

/* ============================ 色图 ============================ */
const CMAPS = {
  viridis: [[0.267,0.005,0.329],[0.283,0.141,0.458],[0.254,0.265,0.530],[0.207,0.372,0.553],
            [0.164,0.471,0.558],[0.128,0.567,0.551],[0.135,0.659,0.518],[0.267,0.749,0.441],
            [0.478,0.821,0.318],[0.741,0.873,0.150],[0.993,0.906,0.144]],
  turbo:   [[0.189,0.071,0.232],[0.271,0.420,0.980],[0.100,0.720,0.900],[0.200,0.900,0.550],
            [0.600,0.950,0.200],[0.950,0.750,0.130],[0.980,0.400,0.050],[0.750,0.100,0.020]],
  jet:     [[0.0,0.0,0.5],[0.0,0.0,1.0],[0.0,1.0,1.0],[0.0,1.0,0.0],
            [1.0,1.0,0.0],[1.0,0.0,0.0],[0.5,0.0,0.0]],
  coolwarm:[[0.230,0.300,0.750],[0.870,0.870,0.870],[0.710,0.020,0.150]],
  plasma:  [[0.050,0.030,0.530],[0.290,0.010,0.630],[0.490,0.030,0.660],[0.660,0.130,0.580],
            [0.800,0.280,0.470],[0.900,0.420,0.360],[0.970,0.580,0.250],[0.990,0.750,0.160],
            [0.940,0.980,0.130]],
  gray:    [[0.05,0.05,0.05],[0.98,0.98,0.98]],
};

function colormap(name, t) {
  const a = CMAPS[name] || CMAPS.viridis;
  t = Math.min(1, Math.max(0, t));
  const n = a.length - 1;
  const f = t * n;
  const i = Math.min(n - 1, Math.floor(f));
  const u = f - i;
  const c0 = a[i], c1 = a[i + 1];
  return [c0[0] + (c1[0] - c0[0]) * u,
          c0[1] + (c1[1] - c0[1]) * u,
          c0[2] + (c1[2] - c0[2]) * u];
}

/* ============================ 4x4 矩阵 ============================ */
function mat4() { return new Float32Array(16); }
function perspective(out, fovy, aspect, near, far) {
  const f = 1 / Math.tan(fovy / 2);
  out.fill(0);
  out[0] = f / aspect; out[5] = f;
  out[10] = (far + near) / (near - far); out[11] = -1;
  out[14] = (2 * far * near) / (near - far);
  return out;
}
function normalize3(v) {
  const l = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / l, v[1] / l, v[2] / l];
}
function cross3(a, b) {
  return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
}
function lookAt(out, eye, center, up) {
  const z = normalize3([eye[0]-center[0], eye[1]-center[1], eye[2]-center[2]]);
  const x = normalize3(cross3(up, z));
  const y = cross3(z, x);
  out[0]=x[0]; out[1]=y[0]; out[2]=z[0]; out[3]=0;
  out[4]=x[1]; out[5]=y[1]; out[6]=z[1]; out[7]=0;
  out[8]=x[2]; out[9]=y[2]; out[10]=z[2]; out[11]=0;
  out[12]=-(x[0]*eye[0]+x[1]*eye[1]+x[2]*eye[2]);
  out[13]=-(y[0]*eye[0]+y[1]*eye[1]+y[2]*eye[2]);
  out[14]=-(z[0]*eye[0]+z[1]*eye[1]+z[2]*eye[2]);
  out[15]=1;
  return out;
}
function multiply(out, a, b) {
  for (let i = 0; i < 4; i++) {
    for (let j = 0; j < 4; j++) {
      out[i*4+j] = a[i*4]*b[j] + a[i*4+1]*b[4+j] + a[i*4+2]*b[8+j] + a[i*4+3]*b[12+j];
    }
  }
  return out;
}

/* ============================ 渲染器 ============================ */
const VS = `
attribute vec3 aPos;
attribute vec3 aNormal;
attribute vec3 aColor;
uniform mat4 uMVP;
uniform float uPointSize;
uniform float uUseNormal;
uniform vec3 uLightDir;
varying vec3 vColor;
void main() {
  gl_Position = uMVP * vec4(aPos, 1.0);
  float lam = max(dot(normalize(aNormal + vec3(1e-6)), normalize(uLightDir)), 0.0);
  float shade = mix(1.0, 0.35 + 0.65 * lam, uUseNormal);
  vColor = aColor * shade;
  gl_PointSize = uPointSize;
}`;
const FS = `
precision mediump float;
varying vec3 vColor;
uniform float uRound;
void main() {
  if (uRound > 0.5) {
    vec2 c = gl_PointCoord - vec2(0.5);
    if (dot(c, c) > 0.25) discard;
  }
  gl_FragColor = vec4(vColor, 1.0);
}`;

const state = {
  gl: null, prog: null, loc: {},
  posBuf: null, nrmBuf: null, colBuf: null, idxBuf: null,
  count: 0, idxCount: 0, hasSurface: false,
  val: null, range: [0, 1], pos3: null, bbox: null,
  meta: null, mode: 'surface', cmap: 'viridis',
  theta: -55, phi: 25, dist: 3.0, target: [0, 0, 0],
  pointSize: 2, dirty: true, playing: false, timer: null,
  loading: false,
};

function initGL() {
  const canvas = document.getElementById('gl');
  const gl = canvas.getContext('webgl', { antialias: true, preserveDrawingBuffer: true })
          || canvas.getContext('experimental-webgl', { preserveDrawingBuffer: true });
  if (!gl) {
    document.getElementById('overlay').textContent = '当前浏览器不支持 WebGL';
    return false;
  }
  const compile = (type, src) => {
    const s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) console.error(gl.getShaderInfoLog(s));
    return s;
  };
  const p = gl.createProgram();
  gl.attachShader(p, compile(gl.VERTEX_SHADER, VS));
  gl.attachShader(p, compile(gl.FRAGMENT_SHADER, FS));
  gl.bindAttribLocation(p, 0, 'aPos');
  gl.bindAttribLocation(p, 1, 'aNormal');
  gl.bindAttribLocation(p, 2, 'aColor');
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) console.error(gl.getProgramInfoLog(p));
  gl.useProgram(p);
  state.gl = gl; state.prog = p;
  state.loc = {
    mvp: gl.getUniformLocation(p, 'uMVP'),
    ps: gl.getUniformLocation(p, 'uPointSize'),
    useN: gl.getUniformLocation(p, 'uUseNormal'),
    light: gl.getUniformLocation(p, 'uLightDir'),
    round: gl.getUniformLocation(p, 'uRound'),
  };
  gl.uniform3f(state.loc.light, 0.4, -0.6, 0.8);
  gl.enable(gl.DEPTH_TEST);
  gl.clearColor(0.043, 0.063, 0.086, 1.0);
  window.addEventListener('resize', resize);
  resize();
  return true;
}

function resize() {
  const c = document.getElementById('gl');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = Math.max(1, Math.floor(c.clientWidth * dpr));
  const h = Math.max(1, Math.floor(c.clientHeight * dpr));
  if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
  state.dirty = true;
}

/* ---------- 数据装载 ---------- */
function computeNormals(pos, idx) {
  const n = new Float32Array(pos.length);
  for (let t = 0; t < idx.length; t += 3) {
    const a = idx[t] * 3, b = idx[t+1] * 3, c = idx[t+2] * 3;
    const ux = pos[b]-pos[a], uy = pos[b+1]-pos[a+1], uz = pos[b+2]-pos[a+2];
    const vx = pos[c]-pos[a], vy = pos[c+1]-pos[a+1], vz = pos[c+2]-pos[a+2];
    const nx = uy*vz-uz*vy, ny = uz*vx-ux*vz, nz = ux*vy-uy*vx;
    for (const o of [a, b, c]) { n[o]+=nx; n[o+1]+=ny; n[o+2]+=nz; }
  }
  for (let i = 0; i < n.length; i += 3) {
    const l = Math.hypot(n[i], n[i+1], n[i+2]) || 1;
    n[i]/=l; n[i+1]/=l; n[i+2]/=l;
  }
  return n;
}

function buildGeometry(payload) {
  let raw, val;
  if (payload.kind === 'grid') {
    const N = payload.x.length;
    raw = new Float64Array(N * 3);
    for (let i = 0; i < N; i++) { raw[i*3]=payload.x[i]; raw[i*3+1]=payload.y[i]; raw[i*3+2]=payload.z[i]; }
    val = Float64Array.from(payload.z);
  } else {
    const N = payload.points.length;
    raw = new Float64Array(N * 3);
    for (let i = 0; i < N; i++) { const p = payload.points[i]; raw[i*3]=p[0]; raw[i*3+1]=p[1]; raw[i*3+2]=p[2]; }
    val = Float64Array.from(payload.value);
  }
  const n = val.length;
  const mn = [Infinity, Infinity, Infinity], mx = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < n; i++) {
    for (let k = 0; k < 3; k++) {
      const v = raw[i*3+k];
      if (v < mn[k]) mn[k] = v;
      if (v > mx[k]) mx[k] = v;
    }
  }
  const ctr = [0,0,0], span = Math.max(mx[0]-mn[0], mx[1]-mn[1], mx[2]-mn[2]) || 1;
  for (let k = 0; k < 3; k++) ctr[k] = (mn[k] + mx[k]) / 2;
  const pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    pos[i*3]   = (raw[i*3]   - ctr[0]) / span;
    pos[i*3+1] = (raw[i*3+1] - ctr[1]) / span;
    pos[i*3+2] = (raw[i*3+2] - ctr[2]) / span;
  }
  const idx = (payload.kind === 'grid' && payload.indices) ? Uint32Array.from(payload.indices) : null;
  const nrm = idx ? computeNormals(pos, idx) : new Float32Array(n * 3);

  state.pos3 = pos; state.val = val;
  state.bbox = { min: mn, max: mx, span };
  state.count = n; state.idxCount = idx ? idx.length : 0;
  state.hasSurface = !!idx;
  state.range = [payload.value_range[0], payload.value_range[1]];
  state.meta = payload;
  state.dist = 3.0; state.target = [0, 0, 0];
  state.mode = idx ? 'surface' : 'points';
  document.getElementById('modeSel').value = state.mode;
  document.getElementById('modeSel').options[0].disabled = !idx;

  const gl = state.gl;
  const up = (buf, data) => {
    if (buf) gl.deleteBuffer(buf);
    const b = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, b);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    return b;
  };
  state.posBuf = up(state.posBuf, pos);   // attrib 0
  state.nrmBuf = up(state.nrmBuf, nrm);   // attrib 1
  if (state.idxBuf) { gl.deleteBuffer(state.idxBuf); state.idxBuf = null; }
  if (idx) {
    const b = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, b);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx, gl.STATIC_DRAW);
    state.idxBuf = b;
  }
  applyRange(false);
  resize();
}

function bindAttribs() {
  const gl = state.gl;
  gl.bindBuffer(gl.ARRAY_BUFFER, state.posBuf);
  gl.enableVertexAttribArray(0); gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
  gl.bindBuffer(gl.ARRAY_BUFFER, state.nrmBuf);
  gl.enableVertexAttribArray(1); gl.vertexAttribPointer(1, 3, gl.FLOAT, false, 0, 0);
}

/* ---------- 颜色 ---------- */
function applyRange(resetInputs) {
  const gl = state.gl;
  if (!state.val) return;
  let lo = parseFloat(document.getElementById('vminInput').value);
  let hi = parseFloat(document.getElementById('vmaxInput').value);
  if (resetInputs || !isFinite(lo)) lo = state.range[0];
  if (resetInputs || !isFinite(hi)) hi = state.range[1];
  if (!isFinite(lo)) lo = 0;
  if (!isFinite(hi)) hi = 1;
  if (hi <= lo) hi = lo + 1e-9;
  document.getElementById('vminInput').value = String(+lo.toFixed(6));
  document.getElementById('vmaxInput').value = String(+hi.toFixed(6));
  state.range = [lo, hi];

  const n = state.val.length;
  const col = new Float32Array(n * 3);
  const inv = 1 / (hi - lo);
  for (let i = 0; i < n; i++) {
    const c = colormap(state.cmap, (state.val[i] - lo) * inv);
    col[i*3] = c[0]; col[i*3+1] = c[1]; col[i*3+2] = c[2];
  }
  if (state.colBuf) gl.deleteBuffer(state.colBuf);
  const b = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, b);
  gl.bufferData(gl.ARRAY_BUFFER, col, gl.STATIC_DRAW);
  state.colBuf = b;
  drawLegend();
  state.dirty = true;
}

function drawLegend() {
  const cv = document.getElementById('legendCanvas');
  const ctx = cv.getContext('2d');
  const w = cv.width, h = cv.height;
  for (let x = 0; x < w; x++) {
    const c = colormap(state.cmap, x / (w - 1));
    ctx.fillStyle = `rgb(${(c[0]*255)|0},${(c[1]*255)|0},${(c[2]*255)|0})`;
    ctx.fillRect(x, 0, 1, h - 12);
  }
  document.getElementById('legend').classList.remove('hidden');
  const fmt = (v) => (Math.abs(v) >= 1e4 || (Math.abs(v) < 1e-2 && v !== 0)) ? v.toExponential(2) : v.toFixed(3);
  document.getElementById('legendMin').textContent = fmt(state.range[0]);
  document.getElementById('legendMax').textContent = fmt(state.range[1]);
  const axes = (state.meta && state.meta.axes) || ['X', 'Y', 'Z'];
  document.getElementById('legendName').textContent = axes[2] || 'Q';
}

/* ---------- 绘制 ---------- */
function render() {
  const gl = state.gl;
  const c = document.getElementById('gl');
  gl.viewport(0, 0, c.width, c.height);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  if (!state.count) return;

  const aspect = c.width / Math.max(1, c.height);
  const proj = perspective(mat4(), Math.PI / 4, aspect, 0.01, 1000);
  const th = state.theta * Math.PI / 180, ph = state.phi * Math.PI / 180;
  const d = state.dist;
  const eye = [state.target[0] + d * Math.cos(ph) * Math.cos(th),
               state.target[1] + d * Math.cos(ph) * Math.sin(th),
               state.target[2] + d * Math.sin(ph)];
  const view = lookAt(mat4(), eye, state.target, [0, 0, 1]);
  const mvp = multiply(mat4(), proj, view);

  gl.useProgram(state.prog);
  gl.uniformMatrix4fv(state.loc.mvp, false, mvp);
  bindAttribs();
  gl.bindBuffer(gl.ARRAY_BUFFER, state.colBuf);
  gl.enableVertexAttribArray(2); gl.vertexAttribPointer(2, 3, gl.FLOAT, false, 0, 0);

  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const useSurface = (state.mode === 'surface' && state.idxBuf);
  gl.uniform1f(state.loc.ps, state.pointSize * dpr);
  gl.uniform1f(state.loc.useN, useSurface ? 1.0 : 0.0);
  gl.uniform1f(state.loc.round, useSurface ? 0.0 : 1.0);

  if (useSurface) {
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, state.idxBuf);
    gl.drawElements(gl.TRIANGLES, state.idxCount, gl.UNSIGNED_INT, 0);
  } else {
    gl.drawArrays(gl.POINTS, 0, state.count);
  }
  updateReadout();
}

function loop() {
  if (state.dirty) { render(); state.dirty = false; }
  requestAnimationFrame(loop);
}

function updateReadout() {
  if (!state.meta) return;
  const m = state.meta;
  const b = state.bbox;
  const f = (v) => (Math.abs(v) >= 1e4 || (Math.abs(v) < 1e-2 && v !== 0)) ? v.toExponential(2) : v.toFixed(4);
  const axes = m.axes || ['X', 'Y', 'Z'];
  const lines = [
    `${m.kind === 'grid' ? '网格曲面' : '点云'}  |  ${state.count} 点  |  帧 ${m.frame}/${Math.max(0, (m.frames || 1) - 1)}  |  通道 ${m.channel}`,
    `${axes[0]}∈[${f(b.min[0])}, ${f(b.max[0])}]  ${axes[1]}∈[${f(b.min[1])}, ${f(b.max[1])}]  ${axes[2]}∈[${f(b.min[2])}, ${f(b.max[2])}]`,
    m.note ? m.note : '',
  ];
  document.getElementById('readout').textContent = lines.filter(Boolean).join('\n');
}

/* ============================ API ============================ */
/* 技能共享令牌：由技能入口 URL 携带；页内所有 /api 请求都带上它，
 * 因为渲染服务是「技能后端」，/api/* 只对携带令牌的请求开放。 */
function withToken(path) {
  const t = new URLSearchParams(location.search).get('t');
  if (!t) return path;
  return path + (path.indexOf('?') === -1 ? '?' : '&') + 't=' + encodeURIComponent(t);
}

const api = {
  async get(path) { const r = await fetch(withToken(path)); if (!r.ok) throw new Error(await r.text()); return r.json(); },
  async post(path, body) {
    const r = await fetch(withToken(path), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    const txt = await r.text();
    let data; try { data = JSON.parse(txt); } catch (_) { data = { error: txt }; }
    if (!r.ok || data.error) throw new Error(data.error || txt);
    return data;
  },
};

function setStatus(msg, cls) {
  const b = document.getElementById('statusBadge');
  b.textContent = msg;
  b.className = 'badge' + (cls ? ' ' + cls : '');
}

/* ============================ UI 逻辑 ============================ */
const QUERY = new URLSearchParams(location.search);
const WIN_NAME = 'cfd_render_engine';
let dataDir = '';

/* 主题：与项目 webui（Open WebUI）一致，支持明/暗双主题并本地记忆。 */
const THEME_KEY = 'cfd_theme';
function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  const b = document.getElementById('btnTheme');
  if (b) {
    b.textContent = t === 'dark' ? '☀' : '☾';
    b.title = t === 'dark' ? '切换到浅色主题' : '切换到深色主题';
  }
}
function initTheme() {
  let t = null;
  try { t = localStorage.getItem(THEME_KEY); } catch (e) { /* 隐私模式下忽略 */ }
  if (t !== 'light' && t !== 'dark') {
    t = document.documentElement.getAttribute('data-theme')
      || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  }
  applyTheme(t);
  const b = document.getElementById('btnTheme');
  if (b) {
    b.onclick = () => {
      const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      applyTheme(next);
      try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* 忽略 */ }
    };
  }
}

/* 当前视口的入口链接（含数据集/帧/通道/论文开关），供「弹出新窗口」复用。 */
function currentEntryUrl() {
  const p = new URLSearchParams({
    frame: String(+document.getElementById('frameRange').value || 0),
    channel: String(+document.getElementById('channelSel').value || 0),
    popup: '1',
  });
  const ds = state.meta && state.meta.dataset;
  if (ds) p.set('dataset', ds);
  if (document.getElementById('paperDrawer').classList.contains('open')) p.set('paper', '1');
  const tk = QUERY.get('t');
  if (tk) p.set('t', tk);           // 弹出窗口同样需要令牌授权
  return '/viewer?' + p.toString();
}

function fmtList(items) {
  const ul = document.getElementById('datasetList');
  ul.innerHTML = '';
  if (!items.length) { ul.innerHTML = '<li class="empty">（未发现数据集）</li>'; return; }
  for (const it of items) {
    const li = document.createElement('li');
    li.dataset.id = it.id;
    li.textContent = it.label + (it.renderable ? '' : '  ✗ ' + (it.note || '').slice(0, 40));
    if (!it.renderable) li.className = 'bad';
    li.title = it.path;
    li.onclick = () => {
      if (!it.renderable) return;
      ul.querySelectorAll('li').forEach((x) => x.classList.remove('active'));
      li.classList.add('active');
      loadDataset(it.id, 0, 0);
    };
    ul.appendChild(li);
  }
}

async function refreshDatasets() {
  dataDir = document.getElementById('dataDirInput').value.trim();
  try {
    const d = await api.post('/api/datasets', { data_dir: dataDir || null });
    fmtList(d.datasets || []);
    setStatus(`${(d.datasets || []).length} 个数据集`, '');
  } catch (e) { setStatus('扫描失败: ' + e.message, 'err'); }
}

async function loadDataset(dataset, frame, channel) {
  if (state.loading) return;
  state.loading = true;
  document.getElementById('overlay').classList.remove('hidden');
  document.getElementById('overlay').textContent = '正在加载数据…';
  setStatus('加载中…', '');
  try {
    const payload = await api.post('/api/series', {
      dataset, frame: frame || 0, channel: channel || 0,
    });
    buildGeometry(payload);
    document.getElementById('overlay').classList.add('hidden');
    const fr = document.getElementById('frameRange');
    fr.max = String(Math.max(0, (payload.frames || 1) - 1));
    fr.value = String(payload.frame || 0);
    document.getElementById('frameVal').textContent = `${payload.frame || 0} / ${Math.max(1, (payload.frames || 1)) }`;
    const chSel = document.getElementById('channelSel');
    chSel.innerHTML = '';
    for (let i = 0; i < (payload.channels || 1); i++) {
      const o = document.createElement('option'); o.value = String(i); o.textContent = '通道 ' + i;
      if (i === (payload.channel || 0)) o.selected = true;
      chSel.appendChild(o);
    }
    setStatus(`${payload.kind === 'grid' ? '网格曲面' : '点云'} · ${state.count} 点`, 'ok');
  } catch (e) {
    document.getElementById('overlay').classList.remove('hidden');
    document.getElementById('overlay').textContent = '加载失败：' + e.message;
    setStatus('加载失败', 'err');
  } finally { state.loading = false; }
}

function wire() {
  /* --- 主题（与项目 webui 一致的明暗双主题） --- */
  initTheme();

  /* --- 面板开合 --- */
  document.getElementById('btnImportToggle').onclick = () =>
    document.getElementById('importPanel').classList.toggle('hidden');
  document.getElementById('btnPaperToggle').onclick = () =>
    document.getElementById('paperDrawer').classList.toggle('open');
  document.getElementById('btnPaperClose').onclick = () =>
    document.getElementById('paperDrawer').classList.remove('open');

  /* --- 弹出独立渲染新界面 --- */
  const popBtn = document.getElementById('btnPopout');
  if (QUERY.get('popup') === '1') popBtn.classList.add('hidden');
  popBtn.onclick = () => {
    const w = window.open(currentEntryUrl(), WIN_NAME,
      'popup=yes,width=1440,height=900,resizable=yes,scrollbars=no');
    if (w) { try { w.focus(); } catch (e) { /* 忽略跨窗口聚焦失败 */ } }
    else setStatus('弹窗被拦截，请允许本站点弹窗', 'err');
  };

  /* --- 数据集 --- */
  document.getElementById('btnRefresh').onclick = refreshDatasets;
  api.get('/api/formats').then((d) => {
    const tb = document.querySelector('#formatTable tbody');
    tb.innerHTML = '';
    for (const g of d.formats || []) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td class="k">${g.ext.join(' ')}</td><td>${g.note || g.label}</td>`;
      tb.appendChild(tr);
    }
  }).catch(() => {});

  /* --- 导入：上传 --- */
  document.getElementById('btnUpload').onclick = async () => {
    const files = document.getElementById('fileInput').files;
    if (!files || !files.length) { setStatus('请先选择文件', 'err'); return; }
    const convert = document.getElementById('convertChk').checked;
    for (const f of files) {
      try {
        setStatus('正在导入 ' + f.name + ' …', '');
        const b64 = await new Promise((res, rej) => {
          const r = new FileReader();
          r.onload = () => res(r.result); r.onerror = rej;
          r.readAsDataURL(f);
        });
        const rep = await api.post('/api/import', {
          filename: f.name, content_b64: b64,
          case: document.getElementById('caseInput').value.trim() || null, convert,
        });
        if (!rep.ok) { setStatus('导入未完成: ' + (rep.message || ''), 'err'); }
        else if (rep.data_dir) await loadDataset(rep.data_dir, 0, 0);
      } catch (e) { setStatus('导入失败: ' + e.message, 'err'); }
    }
    setStatus('导入完成', 'ok');
    refreshDatasets();
  };

  /* --- 导入：服务器路径 --- */
  document.getElementById('btnPathImport').onclick = async () => {
    const p = document.getElementById('pathInput').value.trim();
    if (!p) { setStatus('请填写路径', 'err'); return; }
    try {
      setStatus('正在导入…', '');
      const rep = await api.post('/api/import', {
        file_path: p, case: document.getElementById('caseInput').value.trim() || null,
        array_name: document.getElementById('arrayInput').value.trim() || null,
        convert: document.getElementById('convertChk').checked,
      });
      if (rep.data_dir) await loadDataset(rep.data_dir, 0, 0);
      else if (rep.renderable !== false) await loadDataset(rep.file, 0, 0);
      setStatus(rep.ok ? '导入完成' : '导入未完成', rep.ok ? 'ok' : 'err');
      refreshDatasets();
    } catch (e) { setStatus('导入失败: ' + e.message, 'err'); }
  };

  /* --- 渲染参数 --- */
  document.getElementById('modeSel').onchange = (e) => { state.mode = e.target.value; state.dirty = true; };
  document.getElementById('cmapSel').onchange = (e) => { state.cmap = e.target.value; applyRange(false); };
  document.getElementById('vminInput').onchange = () => applyRange(false);
  document.getElementById('vmaxInput').onchange = () => applyRange(false);
  document.getElementById('btnRangeAuto').onclick = () => applyRange(true);
  document.getElementById('pointSize').oninput = (e) => {
    state.pointSize = parseFloat(e.target.value);
    document.getElementById('psVal').textContent = state.pointSize.toFixed(1);
    state.dirty = true;
  };
  document.getElementById('elevInput').oninput = (e) => { state.phi = +e.target.value; state.dirty = true; };
  document.getElementById('azimInput').oninput = (e) => { state.theta = +e.target.value; state.dirty = true; };
  document.getElementById('btnResetView').onclick = () => {
    state.theta = -55; state.phi = 25; state.dist = 3.0; state.target = [0, 0, 0];
    document.getElementById('elevInput').value = 25;
    document.getElementById('azimInput').value = -55;
    state.dirty = true;
  };
  document.getElementById('btnPlay').onclick = togglePlay;
  document.getElementById('frameRange').oninput = (e) => {
    const li = document.querySelector('#datasetList li.active');
    const ds = state.meta && state.meta.dataset;
    if (ds) loadDataset(ds, +e.target.value, +document.getElementById('channelSel').value || 0);
  };
  document.getElementById('channelSel').onchange = (e) => {
    const ds = state.meta && state.meta.dataset;
    if (ds) loadDataset(ds, +document.getElementById('frameRange').value || 0, +e.target.value);
  };

  /* --- 论文导出 --- */
  document.getElementById('btnExport').onclick = async () => {
    const canvas = document.getElementById('gl');
    render();
    const b64 = canvas.toDataURL('image/png');
    try {
      setStatus('正在生成论文插图…', '');
      const res = await api.post('/api/export/paper', {
        image_b64: b64,
        caption: document.getElementById('capInput').value.trim(),
        label: document.getElementById('labInput').value.trim(),
        width: document.getElementById('widthInput').value.trim() || '\\linewidth',
      });
      const box = document.getElementById('paperResult');
      box.classList.remove('hidden');
      document.getElementById('paperPreview').src = b64;
      document.getElementById('latexOut').value = res.latex;
      const dl = document.getElementById('paperDownload');
      dl.href = res.url; dl.setAttribute('download', res.filename);
      setStatus('论文插图已生成', 'ok');
    } catch (e) { setStatus('导出失败: ' + e.message, 'err'); }
  };
  document.getElementById('btnCopyLatex').onclick = () => {
    const t = document.getElementById('latexOut');
    t.select(); document.execCommand('copy');
    navigator.clipboard && navigator.clipboard.writeText(t.value).catch(() => {});
    setStatus('LaTeX 已复制', 'ok');
  };

  /* --- 鼠标交互 --- */
  const c = document.getElementById('gl');
  let drag = null;
  c.addEventListener('mousedown', (e) => {
    drag = { x: e.clientX, y: e.clientY, pan: e.shiftKey || e.button === 2 || e.button === 1 };
    e.preventDefault();
  });
  window.addEventListener('mouseup', () => { drag = null; });
  window.addEventListener('mousemove', (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    drag.x = e.clientX; drag.y = e.clientY;
    if (drag.pan) {
      const th = state.theta * Math.PI / 180, ph = state.phi * Math.PI / 180;
      const fwd = [Math.cos(ph)*Math.cos(th), Math.cos(ph)*Math.sin(th), Math.sin(ph)];
      const right = normalize3(cross3([0,0,1], fwd));
      const up = normalize3(cross3(fwd, right));
      const k = state.dist * 0.0018;
      for (let i = 0; i < 3; i++) state.target[i] -= right[i]*dx*k + up[i]*(-dy)*k;
    } else {
      state.theta += dx * 0.4;
      state.phi = Math.max(-89, Math.min(89, state.phi + dy * 0.4));
      document.getElementById('azimInput').value = Math.round(state.theta);
      document.getElementById('elevInput').value = Math.round(state.phi);
    }
    state.dirty = true;
  });
  c.addEventListener('contextmenu', (e) => e.preventDefault());
  c.addEventListener('wheel', (e) => {
    state.dist = Math.max(0.5, Math.min(50, state.dist * Math.exp(e.deltaY * 0.0012)));
    state.dirty = true; e.preventDefault();
  }, { passive: false });
}

function togglePlay() {
  const btn = document.getElementById('btnPlay');
  if (state.playing) {
    state.playing = false; clearInterval(state.timer); btn.textContent = '▶ 播放'; return;
  }
  state.playing = true; btn.textContent = '⏸ 暂停';
  const fps = +document.getElementById('fpsSel').value;
  state.timer = setInterval(() => {
    const fr = document.getElementById('frameRange');
    const max = +fr.max;
    if (max <= 0) return;
    const next = (+fr.value + 1) % (max + 1);
    fr.value = String(next);
    const ds = state.meta && state.meta.dataset;
    if (ds) loadDataset(ds, next, +document.getElementById('channelSel').value || 0);
  }, 1000 / fps);
}

/* ============================ 启动 ============================ */
window.addEventListener('DOMContentLoaded', async () => {
  if (!initGL()) return;
  wire();
  loop();
  await refreshDatasets();
  if (QUERY.get('paper') === '1') document.getElementById('paperDrawer').classList.add('open');
  if (QUERY.get('dataset')) {
    loadDataset(QUERY.get('dataset'), +(QUERY.get('frame') || 0), +(QUERY.get('channel') || 0));
  } else {
    const first = document.querySelector('#datasetList li:not(.empty):not(.bad)');
    if (first) first.click();
  }
});
