// 粒子まわりの純粋な数学。フレーム番号だけから位置が決まる（＝どのフレームも単独で再現できる）。

export const mulberry32 = (seed: number) => () => {
  seed |= 0;
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

const gauss = (r: () => number) => {
  const u = Math.max(1e-9, r());
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r());
};

export type Cloud = Float32Array; // xyz, xyz, ...

/** ガウス分布の雲 */
export const makeCloud = (n: number, spread: number, seed: number): Cloud => {
  const r = mulberry32(seed);
  const a = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    a[i * 3] = gauss(r) * spread * 1.6;
    a[i * 3 + 1] = gauss(r) * spread * 0.9;
    a[i * 3 + 2] = gauss(r) * spread;
  }
  return a;
};

/** フィボナッチ格子の球 */
export const makeSphere = (n: number, radius: number): Cloud => {
  const a = new Float32Array(n * 3);
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2;
    const rr = Math.sqrt(1 - y * y);
    const th = golden * i;
    a[i * 3] = Math.cos(th) * rr * radius;
    a[i * 3 + 1] = y * radius;
    a[i * 3 + 2] = Math.sin(th) * rr * radius;
  }
  return a;
};

/** (2,3) トーラス結び目: x=(2+cos3t)cos2t, y=(2+cos3t)sin2t, z=sin3t */
export const makeTorusKnot = (n: number, scale: number, tube = 0.42): Cloud => {
  const a = new Float32Array(n * 3);
  const per = 20; // 管の断面1周あたりの点数
  const rings = Math.ceil(n / per);
  const curve = (t: number) => {
    const k = 2 + Math.cos(3 * t);
    return [k * Math.cos(2 * t), k * Math.sin(2 * t), 1.25 * Math.sin(3 * t)];
  };
  for (let i = 0; i < n; i++) {
    const ring = Math.floor(i / per);
    const t = (ring / rings) * Math.PI * 2;
    const phi = ((i % per) / per) * Math.PI * 2 + ring * 0.31;
    const c = curve(t);
    const d = curve(t + 1e-3);
    // 接線 T、法線 N = T × z、従法線 B = T × N
    let tx = d[0] - c[0], ty = d[1] - c[1], tz = d[2] - c[2];
    const tl = Math.hypot(tx, ty, tz);
    tx /= tl; ty /= tl; tz /= tl;
    let nx = ty, ny = -tx;
    const nl = Math.hypot(nx, ny);
    nx /= nl; ny /= nl;
    const bx = -tz * ny, by = tz * nx, bz = tx * ny - ty * nx;
    const cp = Math.cos(phi) * tube, sp = Math.sin(phi) * tube;
    a[i * 3] = (c[0] + nx * cp + bx * sp) * scale;
    a[i * 3 + 1] = (c[1] + ny * cp + by * sp) * scale;
    a[i * 3 + 2] = (c[2] + bz * sp) * scale;
  }
  return a;
};

/** 波打つ面: y = sin(x)·cos(z) を格子で */
export const makeWave = (n: number, size: number): Cloud => {
  const a = new Float32Array(n * 3);
  const side = Math.ceil(Math.sqrt(n));
  for (let i = 0; i < n; i++) {
    const u = (i % side) / (side - 1) - 0.5;
    const v = Math.floor(i / side) / (side - 1) - 0.5;
    a[i * 3] = u * size * 2.3;
    a[i * 3 + 1] = 0;
    a[i * 3 + 2] = v * size * 1.5;
  }
  return a;
};

/** 文字を Canvas に描き、インクのある画素から n 点を拾う */
export const sampleText = (opts: {
  lines: { text: string; y: number }[];
  font: string;
  width: number;
  height: number;
  n: number;
  seed: number;
  letterSpacing?: string;
}): Float32Array => {
  const { lines, font, width, height, n, seed } = opts;
  const c = document.createElement("canvas");
  c.width = width;
  c.height = height;
  const ctx = c.getContext("2d", { willReadFrequently: true })!;
  ctx.font = font;
  if (opts.letterSpacing) (ctx as unknown as { letterSpacing: string }).letterSpacing = opts.letterSpacing;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillStyle = "#fff";
  for (const l of lines) ctx.fillText(l.text, width / 2, l.y);
  const data = ctx.getImageData(0, 0, width, height).data;
  const ink: number[] = [];
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (data[(y * width + x) * 4 + 3] > 140) ink.push(y * width + x);
    }
  }
  const r = mulberry32(seed);
  const out = new Float32Array(n * 2);
  if (ink.length === 0) return out;
  for (let i = 0; i < n; i++) {
    const p = ink[Math.floor(r() * ink.length)];
    out[i * 2] = (p % width) + r() - 0.5;
    out[i * 2 + 1] = Math.floor(p / width) + r() - 0.5;
  }
  return out;
};

export const easeInOut = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
export const easeOut = (x: number, p = 3) => 1 - Math.pow(1 - x, p);
