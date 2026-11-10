import React from "react";
import { AbsoluteFill, Easing, interpolate, Sequence, useCurrentFrame } from "remotion";
import stats from "../generated/stats.json";
import { C, CLAMP, MONO, SANS } from "../theme";

const SLAM = Easing.bezier(0.16, 1, 0.3, 1);

/** 打点で画面を一瞬だけ揺らす */
const shake = (frame: number, hit: number, amp: number) => {
  const t = frame - hit;
  if (t < 0 || t > 9) return 0;
  return Math.sin(t * 2.4) * amp * Math.exp(-t * 0.45);
};

/** 大きな言葉 → 赤い線で消す → 「0」 */
const Struck: React.FC<{ word: string; zero: string; size: number }> = ({ word, zero, size }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ justifyContent: "center", alignItems: "center" }}>
      <div
        style={{
          position: "relative",
          scale: interpolate(frame, [0, 9], [1.22, 1], { ...CLAMP, easing: SLAM }),
        }}
      >
        <div
          style={{
            fontFamily: SANS,
            fontWeight: 900,
            fontSize: size,
            lineHeight: 1,
            letterSpacing: "-0.03em",
            color: C.ink,
            whiteSpace: "nowrap",
            opacity: interpolate(frame, [30, 36], [1, 0.3], CLAMP),
          }}
        >
          {word}
        </div>
        <div
          style={{
            position: "absolute",
            left: "-5%",
            top: "50%",
            width: "110%",
            height: size * 0.085,
            marginTop: -size * 0.02,
            backgroundColor: C.accent,
            rotate: "-3.5deg",
            transformOrigin: "left center",
            scale: `${interpolate(frame, [30, 35], [0, 1], { ...CLAMP, easing: Easing.out(Easing.cubic) })} 1`,
          }}
        />
        <div
          style={{
            position: "absolute",
            right: 0,
            top: "100%",
            marginTop: 26,
            fontFamily: MONO,
            fontWeight: 700,
            fontSize: 76,
            color: C.accent,
            opacity: interpolate(frame, [34, 38], [0, 1], CLAMP),
          }}
        >
          {zero}
        </div>
      </div>
    </AbsoluteFill>
  );
};

/** 背景に流す、この動画自身のソースコード（本物） */
const CodeWall: React.FC<{ opacity: number }> = ({ opacity }) => {
  const frame = useCurrentFrame();
  const lineH = 36;
  const offset = frame * 2.2;
  const first = Math.floor(offset / lineH);
  const rows = 34;
  return (
    <AbsoluteFill
      style={{
        opacity,
        maskImage: "linear-gradient(90deg, transparent 0%, rgba(0,0,0,0.25) 35%, #000 70%)",
        WebkitMaskImage: "linear-gradient(90deg, transparent 0%, rgba(0,0,0,0.25) 35%, #000 70%)",
      }}
    >
      {Array.from({ length: rows }, (_, i) => {
        const idx = (first + i) % stats.snippet.length;
        return (
          <div
            key={first + i}
            style={{
              position: "absolute",
              left: 700,
              top: i * lineH - (offset % lineH) - 20,
              fontFamily: MONO,
              fontSize: 24,
              color: C.ink,
              whiteSpace: "pre",
            }}
          >
            <span style={{ color: C.accent, opacity: 0.7, marginRight: 28 }}>{String(idx + 1).padStart(3, " ")}</span>
            {stats.snippet[idx]}
          </div>
        );
      })}
    </AbsoluteFill>
  );
};

export const Manifesto: React.FC = () => {
  const frame = useCurrentFrame();
  const x = shake(frame, 0, 22) + shake(frame, 60, 14) + shake(frame, 120, 18);
  const line2 = [..."コードで書いた。"];
  const f3 = frame - 120;
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg, translate: `${x}px ${-x * 0.4}px` }}>
      {frame < 60 ? <Struck word="カメラ" zero="0 台" size={400} /> : null}
      {frame >= 60 && frame < 120 ? (
        <AbsoluteFill style={{ translate: "0px 0px" }}>
          <FrameShift by={60}>
            <Struck word="編集ソフト" zero="0 本" size={300} />
          </FrameShift>
        </AbsoluteFill>
      ) : null}
      {frame >= 120 ? (
        <>
          <CodeWall opacity={interpolate(f3, [0, 30], [0, 0.34], CLAMP)} />
          <div style={{ position: "absolute", left: 110, top: 330 }}>
            <div
              style={{
                fontFamily: SANS,
                fontWeight: 500,
                fontSize: 96,
                color: C.dim,
                opacity: interpolate(f3, [0, 6], [0, 1], CLAMP),
              }}
            >
              全部、
            </div>
            <div
              style={{
                fontFamily: SANS,
                fontWeight: 900,
                fontSize: 212,
                lineHeight: 1.15,
                letterSpacing: "-0.03em",
                whiteSpace: "nowrap",
                scale: interpolate(f3, [60, 66, 78], [1, 1.035, 1], CLAMP),
                transformOrigin: "left center",
              }}
            >
              {line2.map((ch, i) => (
                <span
                  key={i}
                  style={{
                    display: "inline-block",
                    color: i < 3 ? C.accent : C.ink,
                    opacity: interpolate(f3, [6 + i * 1.6, 10 + i * 1.6], [0, 1], CLAMP),
                    translate: interpolate(f3, [6 + i * 1.6, 20 + i * 1.6], ["0px 70px", "0px 0px"], { ...CLAMP, easing: SLAM }),
                  }}
                >
                  {ch}
                </span>
              ))}
            </div>
          </div>
          <div
            style={{
              position: "absolute",
              left: 118,
              bottom: 108,
              fontFamily: MONO,
              fontSize: 36,
              fontWeight: 500,
              color: C.dim,
              opacity: interpolate(f3, [28, 40], [0, 1], CLAMP),
            }}
          >
            この動画のソース{" "}
            <span style={{ color: C.ink, fontWeight: 700 }}>
              {Math.round(
                interpolate(f3, [30, 84], [0, stats.lines], { ...CLAMP, easing: Easing.out(Easing.cubic) }),
              ).toLocaleString("en-US")}
            </span>{" "}
            行
          </div>
        </>
      ) : null}
    </AbsoluteFill>
  );
};

/** 子の useCurrentFrame を by フレームぶん手前にずらす */
const FrameShift: React.FC<{ by: number; children: React.ReactNode }> = ({ by, children }) => (
  <Sequence from={by} layout="none">
    {children}
  </Sequence>
);
