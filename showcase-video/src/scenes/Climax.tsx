import React, { useCallback, useMemo } from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import stats from "../generated/stats.json";
import timeline from "../generated/timeline.json";
import { Canvas2D } from "../lib/Canvas2D";
import { easeOut, mulberry32, sampleText } from "../lib/particles";
import { useFonts } from "../lib/useFonts";
import { C, CLAMP, clamp01, MONO, T } from "../theme";

const N = 42000;
const W = 1920;
const H = 1080;
const BREAK = 30; // 静寂の長さ
const EXIT = 270; // 最後の打点（全体の frame 1350）
const SMALL_FONT = '500 46px "JetBrains Mono", "Noto Sans JP"';
const BIG_FONT = '900 320px "Noto Sans JP"';
const BIG_LINES = [
  { text: "一行で、", y: 356 },
  { text: "ここまで。", y: 700 },
];

/**
 * 見せ場。冒頭の「一行」をもう一度だけ小さく置き、
 * その画素から 42,000 個の粒を飛ばして大きな言葉に組み直す。
 */
export const Climax: React.FC = () => {
  const frame = useCurrentFrame();
  const fontsOk = useFonts();

  const pts = useMemo(() => {
    if (!fontsOk) return null;
    const start = sampleText({ lines: [{ text: timeline.prompt, y: H / 2 }], font: SMALL_FONT, width: W, height: H, n: N, seed: 21 });
    const target = sampleText({
      lines: BIG_LINES,
      font: BIG_FONT,
      width: W,
      height: H,
      n: N,
      seed: 22,
      letterSpacing: "-6px",
    });
    const r = mulberry32(23);
    // 粒ごとの個性: 遅れ / 経由点 / 揺らぎの位相 / 退場の向き
    const delay = new Float32Array(N);
    const ctrl = new Float32Array(N * 2);
    const phase = new Float32Array(N);
    const out = new Float32Array(N * 2);
    for (let i = 0; i < N; i++) {
      delay[i] = r() * 14;
      const ang = r() * Math.PI * 2;
      const rad = 260 + Math.pow(r(), 0.7) * 900;
      ctrl[i * 2] = W / 2 + Math.cos(ang) * rad * 1.35;
      ctrl[i * 2 + 1] = H / 2 + Math.sin(ang) * rad * 0.8;
      phase[i] = r() * Math.PI * 2;
      const dx = target[i * 2] - W / 2;
      const dy = target[i * 2 + 1] - H / 2;
      const len = Math.hypot(dx, dy) + 1;
      const speed = 260 + r() * 1100;
      out[i * 2] = (dx / len) * speed + (r() - 0.5) * 240;
      out[i * 2 + 1] = (dy / len) * speed + (r() - 0.5) * 240;
    }
    return { start, target, delay, ctrl, phase, out };
  }, [fontsOk]);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D) => {
      if (!pts) return;
      if (frame < BREAK) {
        // 静寂。最初の一行だけ。
        ctx.font = SMALL_FONT;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = C.ink;
        ctx.globalAlpha = 0.92;
        ctx.fillText(timeline.prompt, W / 2, H / 2);
        return;
      }
      const { start, target, delay, ctrl, phase, out } = pts;
      const pos = (f: number, i: number, o: number[]) => {
        const t = f - BREAK;
        const u = clamp01((t - delay[i]) / 50);
        const e = easeOut(u, 3.2);
        const a = (1 - e) * (1 - e);
        const b = 2 * e * (1 - e);
        const c = e * e;
        let x = a * start[i * 2] + b * ctrl[i * 2] + c * target[i * 2];
        let y = a * start[i * 2 + 1] + b * ctrl[i * 2 + 1] + c * target[i * 2 + 1];
        // 組み上がったあとの呼吸: 拍ごとに少しふくらむ
        const beat = (t % 15) / 15;
        const barHit = Math.floor(t / 15) % 4 === 0;
        const puff = (barHit ? 9 : 3.5) * Math.exp(-beat * 5) * c;
        x += Math.cos(phase[i]) * puff + Math.sin(f * 0.05 + phase[i]) * 0.9 * c;
        y += Math.sin(phase[i]) * puff + Math.cos(f * 0.043 + phase[i] * 1.7) * 0.9 * c;
        // 一部の粒は定着させず、文字のまわりを漂わせる
        if (i % 14 === 0) {
          x += Math.sin(f * 0.031 + phase[i] * 3) * 46 * c;
          y += Math.cos(f * 0.027 + phase[i] * 2) * 38 * c;
        }
        // 退場
        if (f > EXIT) {
          const q = easeOut(clamp01((f - EXIT) / 30), 2.4);
          x += out[i * 2] * q;
          y += out[i * 2 + 1] * q;
        }
        o[0] = x;
        o[1] = y;
      };
      const fade = 1 - clamp01((frame - EXIT) / 24);
      // 組み上がったら、粒の下に文字そのものを薄く敷いて読みやすくする
      const solid = clamp01((frame - BREAK - 44) / 20) * (1 - clamp01((frame - EXIT) / 5));
      if (solid > 0) {
        ctx.font = BIG_FONT;
        (ctx as unknown as { letterSpacing: string }).letterSpacing = "-6px";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = C.ink;
        ctx.globalAlpha = solid * 0.5;
        for (const l of BIG_LINES) ctx.fillText(l.text, W / 2, l.y);
        (ctx as unknown as { letterSpacing: string }).letterSpacing = "0px";
      }
      ctx.globalCompositeOperation = "lighter";
      ctx.lineCap = "round";
      const p = [0, 0];
      const q = [0, 0];
      for (let i = 0; i < N; i++) {
        pos(frame, i, p);
        pos(frame - 0.6, i, q);
        const accent = i % 14 === 0 || i % 23 === 0;
        ctx.fillStyle = ctx.strokeStyle = accent ? C.accent : C.ink;
        ctx.globalAlpha = (accent ? 0.95 : 0.82) * fade;
        const dx = p[0] - q[0];
        const dy = p[1] - q[1];
        if (dx * dx + dy * dy > 4) {
          ctx.lineWidth = 2.2;
          ctx.beginPath();
          ctx.moveTo(q[0], q[1]);
          ctx.lineTo(p[0], p[1]);
          ctx.stroke();
        } else {
          ctx.fillRect(p[0] - 1.4, p[1] - 1.4, 2.8, 2.8);
        }
      }
    },
    [frame, pts],
  );

  const t = frame - BREAK;
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      {/* 打点の瞬間だけ白く光る */}
      <AbsoluteFill style={{ backgroundColor: C.ink, opacity: interpolate(t, [0, 1, 9], [0, 0.4, 0], CLAMP) }} />
      <Canvas2D draw={draw} style={{ scale: interpolate(t, [0, 240], [1, 1.045], CLAMP) }} />
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: 78,
          display: "flex",
          justifyContent: "center",
          gap: 34,
          fontFamily: MONO,
          fontSize: 34,
          fontWeight: 500,
          letterSpacing: "0.04em",
          color: C.dim,
          opacity: interpolate(frame, [BREAK + 120, BREAK + 136, EXIT, EXIT + 8], [0, 1, 1, 0], CLAMP),
        }}
      >
        <span>
          コード <span style={{ color: C.ink }}>{stats.lines.toLocaleString("en-US")}</span> 行
        </span>
        <span style={{ color: C.faint }}>/</span>
        <span>
          <span style={{ color: C.ink }}>{T.total.toLocaleString("en-US")}</span> フレーム
        </span>
        <span style={{ color: C.faint }}>/</span>
        <span>
          カメラ <span style={{ color: C.accent }}>0</span>
        </span>
      </div>
    </AbsoluteFill>
  );
};
