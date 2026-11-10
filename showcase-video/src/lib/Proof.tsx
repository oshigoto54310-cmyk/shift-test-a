import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";
import { C, CLAMP, MONO, SANS } from "../theme";

/** 「証拠」4場面の共通の枠。番号は左上、言葉は左下、事実は右下。主役は中央の実物に譲る。 */
export const ProofLabels: React.FC<{
  index: string;
  tag: string;
  caption: string;
  fact: string;
}> = ({ index, tag, caption, fact }) => {
  const frame = useCurrentFrame();
  const chars = [...caption];
  return (
    <AbsoluteFill>
      <div
        style={{
          position: "absolute",
          left: 100,
          top: 92,
          fontFamily: MONO,
          fontSize: 34,
          fontWeight: 600,
          letterSpacing: "0.08em",
          color: C.dim,
          opacity: interpolate(frame, [0, 8], [0, 1], CLAMP),
        }}
      >
        <span style={{ color: C.accent }}>{index}</span>
        <span style={{ margin: "0 18px", color: C.faint }}>/</span>
        {tag}
      </div>
      <div
        style={{
          position: "absolute",
          left: 100,
          bottom: 104,
          fontFamily: SANS,
          fontSize: 80,
          fontWeight: 800,
          letterSpacing: "-0.01em",
          color: C.ink,
          whiteSpace: "nowrap",
          textShadow: "0 4px 40px rgba(6,7,10,0.9)",
        }}
      >
        {chars.map((ch, i) => (
          <span
            key={i}
            style={{
              display: "inline-block",
              opacity: interpolate(frame, [5 + i * 1.1, 13 + i * 1.1], [0, 1], CLAMP),
              translate: interpolate(frame, [5 + i * 1.1, 17 + i * 1.1], ["0px 36px", "0px 0px"], {
                ...CLAMP,
                easing: Easing.bezier(0.16, 1, 0.3, 1),
              }),
            }}
          >
            {ch}
          </span>
        ))}
      </div>
      <div
        style={{
          position: "absolute",
          right: 100,
          bottom: 52,
          fontFamily: MONO,
          fontSize: 28,
          fontWeight: 500,
          letterSpacing: "0.04em",
          color: C.dim,
          opacity: interpolate(frame, [26, 40], [0, 1], CLAMP),
        }}
      >
        {fact}
      </div>
    </AbsoluteFill>
  );
};
