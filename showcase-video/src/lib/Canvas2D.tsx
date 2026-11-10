import React, { useLayoutEffect, useRef } from "react";
import { useVideoConfig } from "remotion";

/** 毎フレーム描き直すだけの Canvas。draw はフレーム番号から決定的に描くこと。 */
export const Canvas2D: React.FC<{
  draw: (ctx: CanvasRenderingContext2D, w: number, h: number) => void;
  style?: React.CSSProperties;
}> = ({ draw, style }) => {
  const ref = useRef<HTMLCanvasElement>(null);
  const { width, height } = useVideoConfig();
  useLayoutEffect(() => {
    const ctx = ref.current?.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 1;
    ctx.clearRect(0, 0, width, height);
    draw(ctx, width, height);
  });
  return <canvas ref={ref} width={width} height={height} style={{ position: "absolute", inset: 0, ...style }} />;
};
