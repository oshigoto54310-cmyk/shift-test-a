import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";
import timeline from "../generated/timeline.json";
import { C, CLAMP, MONO } from "../theme";

const LOGS = [
  "構成を決める",
  "フォントを読み込む",
  "音をゼロから合成する",
  "粒子 42,000 個の軌道を計算する",
  "あなたのアプリを起動する",
  "1,560 フレームを描く",
];

const FONT = 64;
const LEFT = 262;
const CENTER_Y = 470;

/** 冒頭。静かな黒に一行だけ。最後はカーソルに突っ込んで次の場面へ。 */
export const Prompt: React.FC = () => {
  const frame = useCurrentFrame();
  const chars = [...timeline.prompt];
  const typed = timeline.promptTypeFrames.filter((f) => frame >= f).length;
  const entered = frame >= timeline.enterFrame;
  // 打っている間と Enter 後は点灯、待っている間だけ点滅
  const typing = typed > 0 && typed < chars.length;
  const idleSince = typed === 0 ? 0 : timeline.promptTypeFrames[chars.length - 1];
  const blinkOn = typing || entered || Math.floor((frame - idleSince) / 14) % 2 === 0;

  // カーソル位置（等幅で並ぶので文字数から決まる）
  const markW = FONT * 0.9;
  const cursorX = LEFT + markW + typed * FONT + 8;
  const z0 = timeline.zoomStartFrame;

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <AbsoluteFill
        style={{
          transformOrigin: `${cursorX + 16}px ${CENTER_Y}px`,
          scale: interpolate(frame, [z0, 209], [1, 130], { ...CLAMP, easing: Easing.bezier(0.7, 0, 0.84, 0) }),
        }}
      >
        <div
          style={{
            position: "absolute",
            left: LEFT,
            top: CENTER_Y - FONT * 0.75,
            height: FONT * 1.5,
            display: "flex",
            alignItems: "center",
            fontFamily: MONO,
            fontSize: FONT,
            fontWeight: 500,
            color: C.ink,
            whiteSpace: "nowrap",
            opacity: interpolate(frame, [timeline.enterFrame, timeline.enterFrame + 10], [1, 0.62], CLAMP),
          }}
        >
          <span style={{ width: markW, color: C.accent, fontWeight: 700 }}>›</span>
          {chars.slice(0, typed).map((ch, i) => (
            <span key={i} style={{ display: "inline-block", width: FONT, textAlign: "center" }}>
              {ch}
            </span>
          ))}
        </div>
        <div
          style={{
            position: "absolute",
            left: cursorX,
            top: CENTER_Y - 40,
            width: 32,
            height: 80,
            backgroundColor: C.accent,
            opacity: blinkOn ? 1 : 0,
          }}
        />
        {LOGS.map((line, i) => {
          const at = timeline.logFrames[i];
          return (
            <div
              key={i}
              style={{
                position: "absolute",
                left: LEFT + markW,
                top: CENTER_Y + 92 + i * 52,
                fontFamily: MONO,
                fontSize: 34,
                fontWeight: 400,
                color: C.dim,
                whiteSpace: "nowrap",
                opacity: interpolate(frame, [at, at + 3], [0, 1], CLAMP),
              }}
            >
              <span style={{ color: C.accent, marginRight: 18 }}>→</span>
              {line}
            </div>
          );
        })}
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
