import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { ProofLabels } from "../lib/Proof";
import { C, CLAMP, MONO } from "../theme";

const W = 1760;
const H = (W * 1000) / 1600;
const EASE = Easing.bezier(0.16, 1, 0.3, 1);

/** 03 実物 — このリポジトリのシフト管理表を実ブラウザで起動し、実際に入力した画面 */
export const ProofRepo: React.FC = () => {
  const frame = useCurrentFrame();
  const scan = interpolate(frame, [42, 118], [0, 1], { ...CLAMP, easing: Easing.inOut(Easing.cubic) });
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <AbsoluteFill style={{ perspective: 2400 }}>
        <div
          style={{
            position: "absolute",
            left: 300,
            top: 40,
            width: W,
            transformStyle: "preserve-3d",
            transformOrigin: "30% 40%",
            opacity: interpolate(frame, [0, 6], [0, 1], CLAMP),
            transform: `translateX(${interpolate(frame, [0, 60], [260, 0], { ...CLAMP, easing: EASE })}px) rotateY(${interpolate(frame, [0, 70, 180], [-30, -13, -7], { ...CLAMP, easing: EASE })}deg) rotateX(${interpolate(frame, [0, 70, 180], [12, 5, 3], { ...CLAMP, easing: EASE })}deg) scale(${interpolate(frame, [0, 180], [0.94, 1.03], CLAMP)})`,
            borderRadius: 18,
            overflow: "hidden",
            border: "1px solid rgba(244,241,234,0.2)",
            boxShadow: "0 60px 160px rgba(0,0,0,0.8), 0 0 120px rgba(255,74,28,0.12)",
            backgroundColor: "#0f1117",
          }}
        >
          <div
            style={{
              height: 52,
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "0 20px",
              backgroundColor: "#171a24",
              borderBottom: "1px solid rgba(244,241,234,0.1)",
            }}
          >
            {[0, 1, 2].map((i) => (
              <div key={i} style={{ width: 13, height: 13, borderRadius: 7, backgroundColor: "rgba(244,241,234,0.22)" }} />
            ))}
            <div style={{ marginLeft: 22, fontFamily: MONO, fontSize: 22, color: C.dim }}>shift-test-a / index.html</div>
          </div>
          <div style={{ position: "relative", width: W, height: H }}>
            <Img src={staticFile("app-empty.png")} style={{ position: "absolute", inset: 0, width: W, height: H }} />
            <Img
              src={staticFile("app-filled.png")}
              style={{ position: "absolute", inset: 0, width: W, height: H, clipPath: `inset(0 ${(1 - scan) * 100}% 0 0)` }}
            />
            <div
              style={{
                position: "absolute",
                top: 0,
                left: scan * W - 3,
                width: 6,
                height: H,
                backgroundColor: C.accent,
                boxShadow: `0 0 40px 10px ${C.accent}`,
                opacity: scan > 0 && scan < 1 ? 1 : 0,
              }}
            />
          </div>
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(6,7,10,0) 58%, rgba(6,7,10,0.94) 84%)" }} />
      <ProofLabels index="03" tag="実物" caption="あなたのアプリも、動かした。" fact="実ブラウザで120セル入力 → 総労働 604:30h を自動集計" />
    </AbsoluteFill>
  );
};
