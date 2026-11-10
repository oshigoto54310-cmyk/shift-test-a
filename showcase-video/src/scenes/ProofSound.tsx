import React, { useCallback } from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import audio from "../generated/audio-data.json";
import timeline from "../generated/timeline.json";
import { Canvas2D } from "../lib/Canvas2D";
import { ProofLabels } from "../lib/Proof";
import { C, T } from "../theme";

const CY = 450;
const X0 = 100;
const X1 = 1820;
const MAXH = 300;

/** 04 音 — 流れているサウンドトラックの実データ（周波数帯と波形）をそのまま描く */
export const ProofSound: React.FC = () => {
  const frame = useCurrentFrame();
  const g = frame + T.sound.from;

  const draw = useCallback(
    (ctx: CanvasRenderingContext2D) => {
      const row = audio.bands[Math.min(audio.bands.length - 1, g)];
      const prev = audio.bands[Math.max(0, g - 1)];
      const n = row.length;
      const step = (X1 - X0) / n;
      const bw = step - 9;
      const appear = Math.min(1, frame / 8);
      for (let i = 0; i < n; i++) {
        // 1フレーム前と混ぜて、落ちるときだけ少し粘らせる
        // 高域は元々小さいので、見た目だけ右上がりに補正する
        const v = Math.min(1, Math.max(row[i], prev[i] * 0.78) * (1 + (i / n) * 0.55)) * appear;
        const h = Math.max(3, Math.pow(v, 1.6) * MAXH);
        const x = X0 + i * step + 4.5;
        ctx.fillStyle = C.ink;
        ctx.globalAlpha = 0.9;
        ctx.fillRect(x, CY - h, bw, h);
        ctx.globalAlpha = 0.16;
        ctx.fillRect(x, CY + 14, bw, h * 0.55);
        if (v > 0.8) {
          ctx.globalAlpha = 1;
          ctx.fillStyle = C.accent;
          ctx.fillRect(x, CY - h, bw, Math.min(h, 12 + (v - 0.8) * 5 * 60));
        }
      }
      // 波形（実サンプル）
      const w = audio.wave[Math.min(audio.wave.length - 1, Math.max(0, g - audio.waveFrom))];
      ctx.globalAlpha = 1;
      ctx.strokeStyle = C.accent;
      ctx.lineWidth = 4;
      ctx.lineJoin = "round";
      ctx.beginPath();
      for (let p = 0; p < w.length; p++) {
        const x = X0 + (p / (w.length - 1)) * (X1 - X0);
        const edge = Math.sin((p / (w.length - 1)) * Math.PI);
        const y = CY + 7 + w[p] * 150 * edge * appear;
        if (p === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    },
    [frame, g],
  );

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <Canvas2D draw={draw} />
      <ProofLabels
        index="04"
        tag="音"
        caption="この音も、コードで鳴らした。"
        fact={`${timeline.samples.toLocaleString("en-US")} サンプルを合成 ・ 録音 0 ・ 音源素材 0`}
      />
    </AbsoluteFill>
  );
};
