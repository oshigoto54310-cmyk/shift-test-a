// 三国志の冒頭30秒（試作）の音と、映像が読むタイミング表を一緒に作る。
// 出力: public/hook.wav / src/sangoku/cues.json
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const SR = 44100;
const FPS = 30;
const TOTAL = 900;
const N = Math.round((TOTAL / FPS) * SR);

const cues = {
  fps: FPS,
  total: TOTAL,
  lines: {
    a1: "三国で一番小さな国が、",
    a2: "なぜ、42年も持ちこたえたのか。",
    b: "蜀は、三国で一番小さな国だった。",
    c: "小さい国は、すぐ滅ぶ。",
    d: "→ 違う。",
    a3: "その答えは、本編で。",
    end: "本編へ →",
  },
  typing: {
    a1: { start: 8, gap: 2.6 },
    a2: { start: 52, gap: 2.4 },
    b: { start: 96, gap: 2.2 },
    c: { start: 194, gap: 2.4 },
    d: { start: 252, gap: 4 },
    a3: { start: 478, gap: 2.8 },
    end: { start: 830, gap: 5 },
  },
  strike: [232, 246],
  dotMove: [300, 350],
  silence: [388, 470],
  rank: {
    grow: 140,
    bars: [
      { name: "魏", w: 900 },
      { name: "呉", w: 650 },
      { name: "蜀", w: 420 },
    ],
  },
  keywords: { starts: [530, 570, 610], words: ["地形", "同盟", "人"] },
  years: { from: 221, to: 263 },
  thumps: [96, 194, 300, 362, 478, 830],
};

// ---- 合成
let seed = 77;
const rnd = () => {
  seed = (seed * 1664525 + 1013904223) >>> 0;
  return seed / 4294967296;
};
const L = new Float32Array(N);
const R = new Float32Array(N);
const clamp01 = (x) => Math.min(1, Math.max(0, x));

// 持続音（D・A・D のドローン）。無音区間は gate で0にする
const gate = (f) => 1 - clamp01(Math.min((f - (cues.silence[0] - 2)) / 3, (cues.silence[1] + 2 - f) / 3));
for (let i = 0; i < N; i++) {
  const t = i / SR;
  const f = t * FPS;
  const swell = Math.min(1, t / 1.6) * Math.min(1, (TOTAL / FPS - t) / 1.0);
  const trem = 0.9 + 0.1 * Math.sin(2 * Math.PI * 0.4 * t);
  const tone =
    0.05 * Math.sin(2 * Math.PI * 73.42 * t) +
    0.035 * Math.sin(2 * Math.PI * 110 * t) +
    0.018 * Math.sin(2 * Math.PI * 146.83 * t);
  const v = tone * swell * trem * gate(f) * 0.9;
  L[i] += v;
  R[i] += v * 0.96;
}

// 太鼓風の低音（ピッチが下がるサイン＋短いノイズ）
const thump = (frame, amp) => {
  const i0 = Math.round((frame / FPS) * SR);
  const len = Math.round(1.1 * SR);
  let ph = 0;
  for (let k = 0; k < len && i0 + k < N; k++) {
    const t = k / SR;
    const freq = 36 + 80 * Math.exp(-t * 14);
    ph += freq / SR;
    const env = Math.exp(-t * 4.2) * Math.min(1, t * 800);
    const click = (rnd() * 2 - 1) * Math.exp(-t * 500) * 0.3;
    const s = (Math.sin(2 * Math.PI * ph) + click) * env * amp;
    L[i0 + k] += s;
    R[i0 + k] += s;
  }
};

// 小さな打鍵音（高域ノイズの短い破裂）
const tick = (frame, amp, pan = 0) => {
  const i0 = Math.round((frame / FPS) * SR);
  const len = Math.round(0.018 * SR);
  let prev = 0;
  for (let k = 0; k < len && i0 + k < N; k++) {
    const t = k / SR;
    const n = rnd() * 2 - 1;
    const hp = n - prev;
    prev = n;
    const s = hp * Math.exp(-t * 260) * amp;
    L[i0 + k] += s * (1 - pan) * 0.5;
    R[i0 + k] += s * (1 + pan) * 0.5;
  }
};

// 打ち消し線の「シュッ」（上がる音）
const chirp = (frame, amp) => {
  const i0 = Math.round((frame / FPS) * SR);
  const len = Math.round(0.35 * SR);
  let ph = 0;
  for (let k = 0; k < len && i0 + k < N; k++) {
    const x = k / len;
    ph += (300 + 900 * x * x) / SR;
    const s = Math.sin(2 * Math.PI * ph) * Math.sin(Math.PI * x) * amp;
    L[i0 + k] += s;
    R[i0 + k] += s;
  }
};

for (const f of cues.thumps) thump(f, 0.55);
chirp(cues.strike[0], 0.05);
for (const k of Object.keys(cues.typing)) {
  const { start, gap } = cues.typing[k];
  [...cues.lines[k]].forEach((_, i) => tick(start + i * gap, 0.035, (i % 2 ? 0.3 : -0.3)));
}
cues.keywords.starts.forEach((f) => tick(f, 0.12));
tick(cues.keywords.starts[2] + 14, 0.08);

// 全体の音量と、末尾の余韻
let peak = 0;
for (let i = 0; i < N; i++) peak = Math.max(peak, Math.abs(L[i]), Math.abs(R[i]));
const g = 0.95 / peak;
const fade = Math.round(0.8 * SR);
for (let i = 0; i < N; i++) {
  const f = i > N - fade ? (N - i) / fade : 1;
  L[i] = Math.tanh(L[i] * g * 1.6) * f;
  R[i] = Math.tanh(R[i] * g * 1.6) * f;
}

// ---- WAV
{
  const data = Buffer.alloc(N * 4);
  for (let i = 0; i < N; i++) {
    data.writeInt16LE(Math.round(Math.max(-1, Math.min(1, L[i])) * 32767), i * 4);
    data.writeInt16LE(Math.round(Math.max(-1, Math.min(1, R[i])) * 32767), i * 4 + 2);
  }
  const h = Buffer.alloc(44);
  h.write("RIFF", 0);
  h.writeUInt32LE(36 + data.length, 4);
  h.write("WAVEfmt ", 8);
  h.writeUInt32LE(16, 16);
  h.writeUInt16LE(1, 20);
  h.writeUInt16LE(2, 22);
  h.writeUInt32LE(SR, 24);
  h.writeUInt32LE(SR * 4, 28);
  h.writeUInt16LE(4, 32);
  h.writeUInt16LE(16, 34);
  h.write("data", 36);
  h.writeUInt32LE(data.length, 40);
  fs.mkdirSync(path.join(here, "../public"), { recursive: true });
  fs.writeFileSync(path.join(here, "../public/hook.wav"), Buffer.concat([h, data]));
}

fs.mkdirSync(path.join(here, "../src/sangoku"), { recursive: true });
fs.writeFileSync(path.join(here, "../src/sangoku/cues.json"), JSON.stringify(cues, null, 2));
console.log(JSON.stringify({ seconds: TOTAL / FPS, peak: +peak.toFixed(3) }));
