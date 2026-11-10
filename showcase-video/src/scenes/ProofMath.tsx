import React, { useCallback, useMemo } from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { Canvas2D } from "../lib/Canvas2D";
import { ProofLabels } from "../lib/Proof";
import { easeInOut, makeCloud, makeSphere, makeTorusKnot, makeWave, mulberry32 } from "../lib/particles";
import { C, clamp01 } from "../theme";

const N = 14000;
const CX = 1130;
const CY = 470;
const FOCAL = 1100;

// 形の切り替え: 雲 → 球 → 結び目 → 波
const KEYS = [
  { at: 0, len: 26 },
  { at: 56, len: 26 },
  { at: 116, len: 28 },
];

/** 01 数式 — 素材なしで立体を描く */
export const ProofMath: React.FC = () => {
  const frame = useCurrentFrame();
  const shapes = useMemo(() => [makeCloud(N, 520, 7), makeSphere(N, 300), makeTorusKnot(N, 104), makeWave(N, 330)], []);
  const jitter = useMemo(() => {
    const r = mulberry32(3);
    return Float32Array.from({ length: N }, () => r());
  }, []);

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D) => {
      const project = (f: number, i: number, out: number[]) => {
        // どの形の間にいるか
        let k = 0;
        for (let j = 0; j < KEYS.length; j++) if (f >= KEYS[j].at) k = j;
        const key = KEYS[k];
        const m = easeInOut(clamp01((f - key.at - jitter[i] * key.len * 0.55) / (key.len * 0.6)));
        const A = shapes[k];
        const B = shapes[k + 1];
        let x = A[i * 3] + (B[i * 3] - A[i * 3]) * m;
        let y = A[i * 3 + 1] + (B[i * 3 + 1] - A[i * 3 + 1]) * m;
        let z = A[i * 3 + 2] + (B[i * 3 + 2] - A[i * 3 + 2]) * m;
        // 波の高さは毎フレーム数式から
        if (k === 2) {
          const wx = B[i * 3] / 120;
          const wz = B[i * 3 + 2] / 120;
          y += m * Math.sin(wx * 1.5 + f * 0.11) * Math.cos(wz * 1.3 - f * 0.07) * 66;
        }
        // 拍で脈打つ
        const beat = (f % 15) / 15;
        const pulse = 1 + 0.045 * Math.exp(-beat * 5);
        x *= pulse;
        y *= pulse;
        z *= pulse;
        // 回転（波のときは見下ろす角度へ）
        const toWave = k === 2 ? m : 0;
        const ry = f * 0.021 * (1 - toWave * 0.75) + toWave * 0.5;
        const rx = 0.32 + toWave * 0.3;
        const cy = Math.cos(ry), sy = Math.sin(ry);
        const x1 = x * cy + z * sy;
        const z1 = -x * sy + z * cy;
        const cx = Math.cos(rx), sx = Math.sin(rx);
        const y1 = y * cx - z1 * sx;
        const z2 = y * sx + z1 * cx;
        const p = FOCAL / (FOCAL + z2);
        out[0] = CX + x1 * p;
        out[1] = CY - toWave * 70 + y1 * p;
        out[2] = p;
      };

      ctx.globalCompositeOperation = "lighter";
      ctx.lineCap = "round";
      const a = [0, 0, 0];
      const b = [0, 0, 0];
      for (let i = 0; i < N; i++) {
        project(frame, i, a);
        project(frame - 0.7, i, b);
        const p = a[2];
        // カメラの真横〜後ろに来た粒は描かない（巨大な線になるのを防ぐ）
        if (p <= 0 || p > 2.2 || b[2] <= 0 || b[2] > 2.2) continue;
        const accent = i % 9 === 0;
        const alpha = Math.min(1, Math.max(0.08, (p - 0.62) * 1.5)) * (accent ? 1 : 0.8);
        const size = 0.9 + p * 1.5;
        ctx.globalAlpha = alpha;
        ctx.fillStyle = ctx.strokeStyle = accent ? C.accent : C.ink;
        const dx = a[0] - b[0];
        const dy = a[1] - b[1];
        if (dx * dx + dy * dy > 5) {
          // 速く動く粒は軌跡を引く
          ctx.lineWidth = size;
          ctx.beginPath();
          ctx.moveTo(b[0], b[1]);
          ctx.lineTo(a[0], a[1]);
          ctx.stroke();
        } else {
          ctx.fillRect(a[0] - size / 2, a[1] - size / 2, size, size);
        }
      }
    },
    [frame, shapes, jitter],
  );

  const formula =
    frame < 56
      ? "点 14,000 個 ・ フィボナッチ格子"
      : frame < 116
        ? "x=(2+cos3t)cos2t  y=(2+cos3t)sin2t  z=sin3t"
        : "y = sin(x)·cos(z)";

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <Canvas2D draw={draw} />
      <ProofLabels index="01" tag="数式" caption="数式だけで、立体を描く。" fact={formula} />
    </AbsoluteFill>
  );
};
