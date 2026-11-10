import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import timeline from "../generated/timeline.json";
import { C, CLAMP, MONO, SERIF, T } from "../theme";

const FONT = 88;
const chars = [...timeline.outro];
const LEFT = (1920 - chars.length * FONT) / 2;

/** 締め。動かさない。次の一行を待つカーソルだけ残す。 */
export const Outro: React.FC = () => {
  const frame = useCurrentFrame();
  const g = frame + T.outro.from;
  const typed = timeline.outroTypeFrames.filter((f) => g >= f).length;
  const promptOn = g >= timeline.outroPromptFrame;
  const blink = Math.floor((g - timeline.outroPromptFrame) / 14) % 2 === 0;
  return (
    <AbsoluteFill
      style={{
        backgroundColor: C.bg,
        opacity: interpolate(frame, [T.outro.dur - 10, T.outro.dur - 1], [1, 0], CLAMP),
      }}
    >
      <div
        style={{
          position: "absolute",
          left: LEFT,
          top: 400,
          fontFamily: SERIF,
          fontWeight: 600,
          fontSize: FONT,
          color: C.ink,
          whiteSpace: "nowrap",
        }}
      >
        {chars.slice(0, typed).map((ch, i) => (
          <span key={i} style={{ display: "inline-block", width: FONT, textAlign: "center" }}>
            {ch}
          </span>
        ))}
      </div>
      {promptOn ? (
        <div
          style={{
            position: "absolute",
            left: LEFT + 14,
            top: 590,
            display: "flex",
            alignItems: "center",
            gap: 22,
            fontFamily: MONO,
            fontSize: 60,
            fontWeight: 700,
            color: C.accent,
          }}
        >
          ›
          <div style={{ width: 28, height: 70, backgroundColor: C.accent, opacity: blink ? 1 : 0 }} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};
