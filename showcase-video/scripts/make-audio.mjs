// サウンドトラックをゼロから合成する。サンプル素材・録音は一切使わない。
// 出力: public/soundtrack.wav / src/generated/timeline.json / src/generated/audio-data.json
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const SR = 44100;
const FPS = 30;
const TOTAL_FRAMES = 1560;
const DUR = TOTAL_FRAMES / FPS; // 52s
const N = Math.round(SR * DUR);

// ---------------------------------------------------------------- utils
const mulberry32 = (seed) => () => {
  seed |= 0;
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};
const rnd = mulberry32(20261110);
const noise = () => rnd() * 2 - 1;
const midi = (n) => 440 * Math.pow(2, (n - 69) / 12);
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
const TAU = Math.PI * 2;

const bus = () => ({ L: new Float32Array(N), R: new Float32Array(N) });
const dry = bus();
const revSend = bus();
const dlySend = new Float32Array(N);
const duck = new Float32Array(N).fill(1);

// 定位つきでバスへ書き込む
const put = (i, s, pan, { d = 1, r = 0, e = 0, ducked = false } = {}) => {
  if (i < 0 || i >= N) return;
  const g = ducked ? duck[i] : 1;
  const l = s * Math.cos((pan + 1) * 0.25 * Math.PI) * g;
  const rr = s * Math.sin((pan + 1) * 0.25 * Math.PI) * g;
  dry.L[i] += l * d;
  dry.R[i] += rr * d;
  if (r) {
    revSend.L[i] += l * r;
    revSend.R[i] += rr * r;
  }
  if (e) dlySend[i] += s * g * e;
};

// TPT state variable filter
class SVF {
  constructor() {
    this.ic1 = 0;
    this.ic2 = 0;
    this.set(1000, 0.7);
  }
  set(fc, q) {
    const g = Math.tan(Math.PI * clamp(fc, 20, SR * 0.45) / SR);
    this.k = 1 / q;
    this.a1 = 1 / (1 + g * (g + this.k));
    this.a2 = g * this.a1;
    this.a3 = g * this.a2;
  }
  run(x) {
    const v3 = x - this.ic2;
    const v1 = this.a1 * this.ic1 + this.a2 * v3;
    const v2 = this.ic2 + this.a2 * this.ic1 + this.a3 * v3;
    this.ic1 = 2 * v1 - this.ic1;
    this.ic2 = 2 * v2 - this.ic2;
    this.lp = v2;
    this.bp = v1;
    this.hp = x - this.k * v1 - v2;
    return v2;
  }
}

// PolyBLEP ノコギリ波
const polyblep = (t, dt) => {
  if (t < dt) {
    t /= dt;
    return t + t - t * t - 1;
  }
  if (t > 1 - dt) {
    t = (t - 1) / dt;
    return t * t + t + t + 1;
  }
  return 0;
};
class Saw {
  constructor(phase = rnd()) {
    this.p = phase;
  }
  run(freq) {
    const dt = freq / SR;
    this.p += dt;
    if (this.p >= 1) this.p -= 1;
    return 2 * this.p - 1 - polyblep(this.p, dt);
  }
}

// ---------------------------------------------------------------- timeline
const BEAT = 0.5; // 120 BPM
const BAR = 2.0;
const T0 = 7.0; // 音楽の頭（= frame 210）
const bar = (b) => T0 + b * BAR;
const fr = (f) => f / FPS;

// 冒頭プロンプトのタイピング（1文字ずつのフレーム）
const PROMPT = "あなたの実力を見せつける最強の動画を作って";
const promptTypeFrames = [];
{
  let f = 40;
  for (let i = 0; i < [...PROMPT].length; i++) {
    promptTypeFrames.push(Math.round(f));
    f += 2.6 + rnd() * 1.6 + (i === 3 || i === 11 || i === 14 ? 3.5 : 0);
  }
}
const enterFrame = promptTypeFrames[promptTypeFrames.length - 1] + 30;
// 「作業ログ」が加速しながら出る
const logFrames = [enterFrame + 14, enterFrame + 25, enterFrame + 34, enterFrame + 41, enterFrame + 47, enterFrame + 52];
const zoomStartFrame = 190;

const OUTRO = "次は、あなたの一行。";
const outroTypeFrames = [];
{
  let f = 1416;
  for (let i = 0; i < [...OUTRO].length; i++) {
    outroTypeFrames.push(Math.round(f));
    f += 3.4 + rnd() * 1.4 + (i === 2 ? 5 : 0);
  }
}
const outroPromptFrame = 1482;

// ---------------------------------------------------------------- instruments
const keyTick = (t, gain = 0.2, bright = 1) => {
  const i0 = Math.round(t * SR);
  const f = new SVF();
  f.set(2600 * bright + rnd() * 1400, 2.2);
  const pan = (rnd() - 0.5) * 0.5;
  const thock = 150 + rnd() * 70;
  const len = Math.round(0.06 * SR);
  for (let i = 0; i < len; i++) {
    const tt = i / SR;
    f.run(noise());
    const click = f.bp * Math.exp(-tt * 380);
    const body = Math.sin(TAU * thock * tt) * Math.exp(-tt * 90) * 0.8;
    put(i0 + i, (click + body) * gain, pan, { r: 0.12 });
  }
};

const kick = (t, gain = 0.9) => {
  const i0 = Math.round(t * SR);
  const len = Math.round(0.42 * SR);
  let ph = 0;
  for (let i = 0; i < len; i++) {
    const tt = i / SR;
    const freq = 46 + 120 * Math.exp(-tt * 38);
    ph += freq / SR;
    const amp = Math.exp(-tt * 9.5) * Math.min(1, tt * 900);
    const click = noise() * Math.exp(-tt * 900) * 0.25;
    put(i0 + i, Math.tanh((Math.sin(TAU * ph) + click) * 1.6) * amp * gain, 0);
  }
  // サイドチェイン用のダッキング
  const dl = Math.round(0.26 * SR);
  for (let i = 0; i < dl; i++) {
    const j = i0 + i;
    if (j >= N) break;
    const x = i / dl;
    duck[j] = Math.min(duck[j], 0.28 + 0.72 * x * x);
  }
};

const clap = (t, gain = 0.4) => {
  const i0 = Math.round(t * SR);
  const f = new SVF();
  f.set(1700, 1.4);
  const len = Math.round(0.22 * SR);
  for (let i = 0; i < len; i++) {
    const tt = i / SR;
    f.run(noise());
    // 3連の短いバースト＋尾
    const burst = (tt < 0.03 ? Math.abs(Math.sin(tt * TAU * 55)) : 0) * 0.9 + Math.exp(-(tt - 0.028) * 28) * (tt > 0.028 ? 1 : 0);
    put(i0 + i, f.bp * burst * gain, 0.05, { r: 0.35 });
  }
};

const hat = (t, gain = 0.12, open = false) => {
  const i0 = Math.round(t * SR);
  const f = new SVF();
  f.set(8200, 0.9);
  const len = Math.round((open ? 0.16 : 0.045) * SR);
  const pan = 0.25 + (rnd() - 0.5) * 0.2;
  for (let i = 0; i < len; i++) {
    const tt = i / SR;
    f.run(noise());
    put(i0 + i, f.hp * Math.exp(-tt * (open ? 22 : 95)) * gain, pan, { r: 0.05 });
  }
};

// 低域のドロップ＋ノイズ。場面の「打点」
const impact = (t, gain = 1) => {
  const i0 = Math.round(t * SR);
  const len = Math.round(3.2 * SR);
  let ph = 0;
  const f = new SVF();
  for (let i = 0; i < len; i++) {
    const tt = i / SR;
    const freq = 36 + 62 * Math.exp(-tt * 5);
    ph += freq / SR;
    const sub = Math.sin(TAU * ph) * Math.exp(-tt * 1.9);
    if (i % 32 === 0) f.set(300 + 5200 * Math.exp(-tt * 7), 0.7);
    const n = f.run(noise()) * Math.exp(-tt * 5.5);
    put(i0 + i, Math.tanh(sub * 1.5) * 0.85 * gain * Math.min(1, tt * 500), 0);
    put(i0 + i, n * 0.55 * gain, 0, { d: 0.6, r: 0.9 });
  }
  const dl = Math.round(0.5 * SR);
  for (let i = 0; i < dl; i++) {
    const j = i0 + i;
    if (j >= N) break;
    const x = i / dl;
    duck[j] = Math.min(duck[j], 0.2 + 0.8 * x * x);
  }
};

// ノイズのライザー（終点 tEnd で切れる）
const riser = (tStart, tEnd, gain = 0.3, fromHz = 250, toHz = 9000) => {
  const i0 = Math.round(tStart * SR);
  const len = Math.round((tEnd - tStart) * SR);
  const f = new SVF();
  let ph = 0;
  for (let i = 0; i < len; i++) {
    const x = i / len;
    if (i % 32 === 0) f.set(fromHz * Math.pow(toHz / fromHz, x), 1.8);
    f.run(noise());
    ph += (70 + 330 * x * x) / SR;
    const tone = Math.sin(TAU * ph) * 0.25;
    const amp = Math.pow(x, 2.2) * Math.min(1, (1 - x) * 200);
    const pan = Math.sin(x * 9) * 0.5;
    put(i0 + i, (f.bp + tone) * amp * gain, pan, { r: 0.4 });
  }
};

// 打ち消し線の「シュッ」
const slash = (t, gain = 0.35) => {
  const i0 = Math.round(t * SR);
  const len = Math.round(0.2 * SR);
  const f = new SVF();
  for (let i = 0; i < len; i++) {
    const x = i / len;
    if (i % 16 === 0) f.set(900 + 7000 * x, 2.5);
    f.run(noise());
    put(i0 + i, f.bp * Math.sin(Math.PI * x) ** 1.5 * gain, -0.7 + 1.4 * x, { r: 0.3 });
  }
};

const crash = (t, gain = 0.25) => {
  const i0 = Math.round(t * SR);
  const len = Math.round(2.6 * SR);
  const f = new SVF();
  f.set(6000, 0.6);
  for (let i = 0; i < len; i++) {
    const tt = i / SR;
    f.run(noise());
    put(i0 + i, f.hp * Math.exp(-tt * 2.2) * gain, (rnd() - 0.5) * 0.2, { r: 0.5 });
  }
};

// 汎用シンセボイス（ノコギリ×複数デチューン → LPF）
const synth = ({ t, dur, note, gain = 0.2, pan = 0, voices = 1, detune = 0.006, a = 0.005, d = 0.2, s = 0.6, r = 0.15, cut = 1200, cutEnv = 0, cutDecay = 8, q = 0.9, rev = 0, dly = 0, ducked = true, sub = 0, vibrato = 0 }) => {
  const i0 = Math.round(t * SR);
  const len = Math.round((dur + r) * SR);
  const f0 = midi(note);
  const oscs = [];
  for (let v = 0; v < voices; v++) {
    const off = voices === 1 ? 0 : (v / (voices - 1)) * 2 - 1;
    oscs.push({ o: new Saw(), mul: 1 + off * detune, pan: clamp(pan + off * 0.6, -1, 1) });
  }
  const filters = oscs.map(() => new SVF());
  let subPh = 0;
  for (let i = 0; i < len; i++) {
    const tt = i / SR;
    let env;
    if (tt < a) env = tt / a;
    else if (tt < dur) env = s + (1 - s) * Math.exp(-(tt - a) / d);
    else env = (s + (1 - s) * Math.exp(-(dur - a) / d)) * Math.max(0, 1 - (tt - dur) / r);
    const vib = vibrato ? 1 + Math.sin(TAU * 5.2 * tt) * vibrato * Math.min(1, tt * 3) : 1;
    if (i % 16 === 0) {
      const fc = cut + cutEnv * Math.exp(-tt * cutDecay);
      for (const fl of filters) fl.set(fc, q);
    }
    for (let v = 0; v < oscs.length; v++) {
      const x = filters[v].run(oscs[v].o.run(f0 * oscs[v].mul * vib));
      put(i0 + i, (x * env * gain) / Math.sqrt(voices), oscs[v].pan, { r: rev, e: dly, ducked });
    }
    if (sub) {
      subPh += (f0 / 2) / SR;
      put(i0 + i, Math.sin(TAU * subPh) * env * sub, 0, { ducked });
    }
  }
};

// ---------------------------------------------------------------- score
// --- S1: プロンプト（無音に近い）
// ごく薄い部屋鳴り
{
  const f = new SVF();
  f.set(320, 0.6);
  const end = Math.round(fr(zoomStartFrame) * SR);
  for (let i = 0; i < end; i++) {
    const tt = i / SR;
    const amp = 0.012 * Math.min(1, tt / 1.5) * Math.min(1, (end - i) / (0.3 * SR));
    put(i, (f.run(noise()) * 1.2 + Math.sin(TAU * 55 * tt) * 0.9) * amp, 0);
  }
}
promptTypeFrames.forEach((f) => keyTick(fr(f), 0.2 + rnd() * 0.06));
// Enter
keyTick(fr(enterFrame), 0.34, 0.55);
keyTick(fr(enterFrame) + 0.012, 0.2, 0.4);
logFrames.forEach((f, i) => keyTick(fr(f), 0.1 + i * 0.012, 1.6));
riser(fr(zoomStartFrame) - 0.9, T0 - 0.03, 0.34, 220, 10000);

// --- 進行: Dm – B♭ – F – C
const CH = [
  { root: 38, pad: [57, 62, 65, 69, 76], arp: [62, 65, 69, 72, 74, 77, 81, 77, 74, 72, 69, 65, 62, 69, 74, 77] }, // Dm(add9)
  { root: 34, pad: [58, 62, 65, 69, 74], arp: [58, 62, 65, 69, 70, 74, 77, 74, 70, 69, 65, 62, 58, 65, 70, 74] }, // B♭maj7
  { root: 41, pad: [57, 60, 65, 69, 72], arp: [60, 65, 69, 72, 77, 72, 69, 65, 60, 65, 69, 72, 77, 81, 77, 72] }, // F
  { root: 36, pad: [55, 60, 64, 67, 74], arp: [60, 64, 67, 72, 74, 76, 79, 76, 74, 72, 67, 64, 60, 67, 72, 76] }, // C(add9)
];

// 先にキック・打点を置く（ダッキングカーブを作るため）
impact(bar(0), 1.0);
for (let b = 0; b < 4; b++) {
  if (b > 0) kick(bar(b), 0.95);
  kick(bar(b) + 2 * BEAT, 0.55);
}
slash(bar(0) + 2 * BEAT, 0.36);
slash(bar(1) + 2 * BEAT, 0.36);
// bar3 後半: スネアロール的に加速
for (let k = 0; k < 8; k++) clap(bar(3) + 2 * BEAT + k * 0.125, 0.12 + k * 0.035);
riser(bar(3), bar(4) - 0.02, 0.26, 300, 9000);

// bars 4 – 14.5: 4つ打ち
const GROOVE_END = bar(14.5);
for (let t = bar(4); t < GROOVE_END - 1e-6; t += BEAT) kick(t, 0.95);
impact(bar(4), 0.55);
crash(bar(4), 0.2);
for (let b = 4; b < 15; b++) {
  for (let k = 0; k < 16; k++) {
    const t = bar(b) + k * 0.125;
    if (t >= GROOVE_END - 1e-6) break;
    const inSound = t >= bar(12.5);
    // クラップ: 2・4拍
    if (k === 4 || k === 12) clap(t, inSound ? 0.32 : 0.44);
    // ハット
    if (!inSound) {
      if (k % 4 === 2) hat(t, 0.26, true);
      else hat(t, k % 2 === 0 ? 0.13 : 0.085);
    } else if (k % 4 === 2) hat(t, 0.17, true);
  }
}
// 場面転換の合図
riser(bar(6.5), bar(7) - 0.02, 0.16, 500, 9000);
crash(bar(7), 0.14);
riser(bar(9), bar(9.5) - 0.02, 0.16, 500, 9000);
impact(bar(9.5), 0.4);
riser(bar(12), bar(12.5) - 0.02, 0.18, 500, 9000);
crash(bar(12.5), 0.16);

// ブレイク（36.0–37.0s）→ クライマックス
riser(bar(14.5) + 0.3, bar(15) - 0.03, 0.42, 200, 11000);
impact(bar(15), 1.15);
crash(bar(15), 0.3);
for (let t = bar(15) + BEAT; t < bar(19) - 1e-6; t += BEAT) kick(t, 0.95);
for (let b = 15; b < 19; b++) {
  for (let k = 0; k < 16; k++) {
    const t = bar(b) + k * 0.125;
    if (k === 4 || k === 12) clap(t, 0.46);
    if (k % 4 === 2) hat(t, 0.26, true);
    else hat(t, k % 2 === 0 ? 0.13 : 0.085);
  }
}
crash(bar(17), 0.2);
for (let k = 0; k < 8; k++) clap(bar(18) + 2 * BEAT + k * 0.125, 0.14 + k * 0.04);
riser(bar(18), bar(19) - 0.02, 0.3, 300, 10000);
impact(bar(19), 1.1);
crash(bar(19), 0.26);

// ベース（8分）
const bassNote = (t, note, gain, cut) =>
  synth({ t, dur: 0.2, note, gain, voices: 2, detune: 0.004, a: 0.004, d: 0.12, s: 0.5, r: 0.06, cut, cutEnv: cut * 1.8, cutDecay: 16, q: 1.3, sub: gain * 0.7 });
for (let b = 0; b < 19; b++) {
  if (b === 14) {
    // bar14 は前半のみ（後半はブレイク）
  }
  const ch = CH[b % 4];
  for (let k = 0; k < 8; k++) {
    const t = bar(b) + k * 0.25;
    if (t >= bar(14.5) - 1e-6 && t < bar(15)) continue;
    let cut, gain;
    if (b < 4) {
      cut = 140 + ((b * 8 + k) / 32) * 420;
      gain = 0.2 + (b / 4) * 0.08;
    } else if (b < 15) {
      cut = 620;
      gain = 0.3;
    } else {
      cut = 900;
      gain = 0.32;
    }
    const oct = k % 4 === 3 ? 12 : 0;
    bassNote(t, ch.root + oct, gain, cut);
  }
}

// パッド
for (let b = 0; b < 19; b++) {
  const ch = CH[b % 4];
  if (b >= 13 && b < 15) continue; // 「音」の場面はパッドを抜いてアルペジオを主役に
  const dur = b === 12 ? BAR / 2 : BAR;
  const lvl = b < 4 ? 0.07 + b * 0.012 : b < 15 ? 0.13 : 0.17;
  const cut = b < 4 ? 500 + b * 260 : b < 15 ? 2500 : 3400;
  ch.pad.forEach((n, idx) =>
    synth({ t: bar(b), dur: dur - 0.05, note: n, gain: lvl * (idx === 0 ? 0.8 : 1), voices: 3, detune: 0.007, a: b < 4 ? 0.5 : 0.08, d: 1.2, s: 0.8, r: 0.5, cut, q: 0.7, rev: 0.45, pan: (idx - 2) * 0.22 }),
  );
}

// アルペジオ（16分）— bar4 から。「音」の場面で前に出る
for (let b = 4; b < 19; b++) {
  const ch = CH[b % 4];
  for (let k = 0; k < 16; k++) {
    const t = bar(b) + k * 0.125;
    if (t >= bar(14.5) - 1e-6 && t < bar(15)) continue;
    const feature = t >= bar(12.5) && t < bar(14.5);
    const climax = b >= 15;
    const open = b < 7 ? (b - 4) / 3 : 1;
    const note = ch.arp[k] + (climax ? 12 : 0);
    const acc = k % 4 === 0 ? 1.25 : k % 2 === 0 ? 1 : 0.8;
    synth({
      t,
      dur: 0.09,
      note,
      gain: (feature ? 0.27 : climax ? 0.17 : 0.13 + open * 0.07) * acc,
      voices: 2,
      detune: 0.005,
      a: 0.002,
      d: 0.07,
      s: 0.25,
      r: 0.12,
      cut: feature ? 2200 : 900 + open * 900,
      cutEnv: feature ? 6500 : 3200 + open * 2200,
      cutDecay: 22,
      q: 1.6,
      rev: 0.25,
      dly: feature ? 0.5 : 0.32,
      pan: Math.sin(k * 1.7 + b) * 0.55,
    });
    if (feature && k % 2 === 0)
      synth({ t, dur: 0.07, note: note + 12, gain: 0.06, voices: 1, a: 0.002, d: 0.05, s: 0.2, r: 0.1, cut: 3000, cutEnv: 5000, cutDecay: 25, q: 1.2, rev: 0.3, dly: 0.5, pan: -Math.sin(k * 1.7 + b) * 0.6 });
  }
}

// リード（クライマックス bars 15–18）
const lead = (t, beats, note, gain = 0.2) =>
  synth({ t, dur: beats * BEAT - 0.04, note, gain, voices: 3, detune: 0.008, a: 0.02, d: 0.5, s: 0.75, r: 0.25, cut: 2400, cutEnv: 2600, cutDecay: 5, q: 1.0, rev: 0.45, dly: 0.35, ducked: false, vibrato: 0.006 });
const melody = [
  // [bar, beatOffset, beats, midi]
  [15, 0, 1.5, 74], [15, 1.5, 0.5, 77], [15, 2, 2, 81],
  [16, 0, 1.5, 79], [16, 1.5, 0.5, 77], [16, 2, 2, 74],
  [17, 0, 1.5, 72], [17, 1.5, 0.5, 77], [17, 2, 2, 81],
  [18, 0, 1.5, 79], [18, 1.5, 0.5, 76], [18, 2, 1, 79], [18, 3, 1, 84],
];
melody.forEach(([b, o, len, n]) => {
  lead(bar(b) + o * BEAT, len, n, 0.2);
  lead(bar(b) + o * BEAT, len, n - 12, 0.1);
});

// 最後の和音（D の開放和音、長い余韻）
[38, 45, 50, 57, 62, 64, 69, 74, 86].forEach((n, idx) =>
  synth({ t: bar(19), dur: 2.2, note: n, gain: idx > 6 ? 0.07 : 0.14, voices: 3, detune: 0.007, a: 0.01, d: 1.4, s: 0.35, r: 2.4, cut: 900, cutEnv: 3200, cutDecay: 1.6, q: 0.7, rev: 0.6, ducked: false, pan: (idx - 4) * 0.18 }),
);

// アウトロ: 静かなタイピング
outroTypeFrames.forEach((f) => keyTick(fr(f), 0.13 + rnd() * 0.04, 0.9));
keyTick(fr(outroPromptFrame), 0.16, 0.6);

// ---------------------------------------------------------------- FX
// ピンポンディレイ（付点8分）
{
  const D = Math.round(0.375 * SR);
  const bl = new Float32Array(N);
  const br = new Float32Array(N);
  let lpL = 0;
  let lpR = 0;
  for (let i = 0; i < N; i++) {
    const inL = dlySend[i] + (i >= D ? br[i - D] * 0.46 : 0);
    const inR = i >= D ? bl[i - D] * 0.46 : 0;
    lpL += (inL - lpL) * 0.35;
    lpR += (inR - lpR) * 0.35;
    bl[i] = lpL;
    br[i] = lpR;
    if (i >= D) {
      dry.L[i] += bl[i - D] * 0.5;
      dry.R[i] += br[i - D] * 0.5;
      revSend.L[i] += bl[i - D] * 0.12;
      revSend.R[i] += br[i - D] * 0.12;
    }
  }
}
// Freeverb 型リバーブ
const reverb = (input, spread) => {
  const out = new Float32Array(N);
  const combs = [1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617].map((l) => ({ buf: new Float32Array(l + spread), i: 0, store: 0 }));
  const aps = [556, 441, 341, 225].map((l) => ({ buf: new Float32Array(l + spread), i: 0 }));
  const fb = 0.88;
  const damp = 0.28;
  for (let n = 0; n < N; n++) {
    const x = input[n] * 0.015;
    let acc = 0;
    for (const c of combs) {
      const y = c.buf[c.i];
      c.store = y * (1 - damp) + c.store * damp;
      c.buf[c.i] = x + c.store * fb;
      if (++c.i >= c.buf.length) c.i = 0;
      acc += y;
    }
    for (const a of aps) {
      const b = a.buf[a.i];
      const y = -acc + b;
      a.buf[a.i] = acc + b * 0.5;
      if (++a.i >= a.buf.length) a.i = 0;
      acc = y;
    }
    out[n] = acc;
  }
  return out;
};
const wetL = reverb(revSend.L, 0);
const wetR = reverb(revSend.R, 23);

// ---------------------------------------------------------------- master
const L = new Float32Array(N);
const R = new Float32Array(N);
{
  // 25Hz ハイパス + ソフトクリップ
  let hl = 0, hr = 0, pl = 0, pr = 0;
  const c = Math.exp((-TAU * 25) / SR);
  for (let i = 0; i < N; i++) {
    const xl = dry.L[i] + wetL[i] * 3.0;
    const xr = dry.R[i] + wetR[i] * 3.0;
    hl = c * (hl + xl - pl);
    pl = xl;
    hr = c * (hr + xr - pr);
    pr = xr;
    L[i] = Math.tanh(hl * 1.15);
    R[i] = Math.tanh(hr * 1.15);
  }
  let peak = 0;
  for (let i = 0; i < N; i++) peak = Math.max(peak, Math.abs(L[i]), Math.abs(R[i]));
  const g = 0.9 / peak;
  // 最後の 0.4 秒はフェードアウト
  const fade = Math.round(0.4 * SR);
  for (let i = 0; i < N; i++) {
    const f = i > N - fade ? (N - i) / fade : 1;
    L[i] *= g * f;
    R[i] *= g * f;
  }
}

// ---------------------------------------------------------------- write wav
{
  const data = Buffer.alloc(N * 4);
  for (let i = 0; i < N; i++) {
    data.writeInt16LE(Math.round(clamp(L[i], -1, 1) * 32767), i * 4);
    data.writeInt16LE(Math.round(clamp(R[i], -1, 1) * 32767), i * 4 + 2);
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
  fs.writeFileSync(path.join(here, "../public/soundtrack.wav"), Buffer.concat([h, data]));
}

// ---------------------------------------------------------------- analysis (映像を音に同期させるための実データ)
const FFT_N = 2048;
const fft = (re, im) => {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      [re[i], re[j]] = [re[j], re[i]];
      [im[i], im[j]] = [im[j], im[i]];
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = -TAU / len;
    for (let i = 0; i < n; i += len) {
      for (let k = 0; k < len / 2; k++) {
        const wr = Math.cos(ang * k), wi = Math.sin(ang * k);
        const a = i + k, b = i + k + len / 2;
        const tr = re[b] * wr - im[b] * wi, ti = re[b] * wi + im[b] * wr;
        re[b] = re[a] - tr;
        im[b] = im[a] - ti;
        re[a] += tr;
        im[a] += ti;
      }
    }
  }
};
const BANDS = 56;
const edges = Array.from({ length: BANDS + 1 }, (_, i) => 38 * Math.pow(12000 / 38, i / BANDS));
const bands = [];
const level = [];
for (let f = 0; f < TOTAL_FRAMES; f++) {
  const c = Math.round(((f + 0.5) / FPS) * SR);
  const re = new Float64Array(FFT_N), im = new Float64Array(FFT_N);
  let sq = 0;
  for (let i = 0; i < FFT_N; i++) {
    const j = c - FFT_N / 2 + i;
    const x = j >= 0 && j < N ? (L[j] + R[j]) * 0.5 : 0;
    sq += x * x;
    re[i] = x * (0.5 - 0.5 * Math.cos((TAU * i) / (FFT_N - 1)));
  }
  fft(re, im);
  const row = [];
  for (let b = 0; b < BANDS; b++) {
    const lo = Math.max(1, Math.floor((edges[b] / SR) * FFT_N));
    const hi = Math.max(lo + 1, Math.ceil((edges[b + 1] / SR) * FFT_N));
    let m = 0;
    for (let k = lo; k < hi; k++) m = Math.max(m, Math.hypot(re[k], im[k]));
    const db = 20 * Math.log10(m / (FFT_N / 4) + 1e-9);
    row.push(Math.round(clamp((db + 62) / 56, 0, 1) * 1000) / 1000);
  }
  bands.push(row);
  level.push(Math.round(Math.sqrt(sq / FFT_N) * 1000) / 1000);
}
// 「音」の場面用の波形（frame 960–1080）
const WAVE_FROM = 960, WAVE_TO = 1080, WAVE_PTS = 240;
const wave = [];
for (let f = WAVE_FROM; f < WAVE_TO; f++) {
  const c = Math.round((f / FPS) * SR);
  const row = [];
  for (let p = 0; p < WAVE_PTS; p++) {
    const j = c + p * 6;
    row.push(Math.round((L[j] + R[j]) * 0.5 * 1000) / 1000);
  }
  wave.push(row);
}

fs.mkdirSync(path.join(here, "../src/generated"), { recursive: true });
fs.writeFileSync(
  path.join(here, "../src/generated/timeline.json"),
  JSON.stringify({ fps: FPS, totalFrames: TOTAL_FRAMES, prompt: PROMPT, promptTypeFrames, enterFrame, logFrames, zoomStartFrame, outro: OUTRO, outroTypeFrames, outroPromptFrame, sampleRate: SR, samples: N * 2 }, null, 2),
);
fs.writeFileSync(path.join(here, "../src/generated/audio-data.json"), JSON.stringify({ bands, level, waveFrom: WAVE_FROM, wave }));
console.log(JSON.stringify({ seconds: DUR, samples: N * 2, enterFrame, logFrames, promptEnd: promptTypeFrames.at(-1), outroEnd: outroTypeFrames.at(-1) }));
