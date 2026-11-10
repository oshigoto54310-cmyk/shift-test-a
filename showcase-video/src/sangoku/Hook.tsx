import React from "react";
import { Audio } from "@remotion/media";
import { AbsoluteFill, Easing, interpolate, staticFile, useCurrentFrame } from "remotion";
import cues from "./cues.json";
import { useFonts } from "../lib/useFonts";
import { C, CLAMP, MONO, SANS } from "../theme";

const EASE = Easing.bezier(0.16, 1, 0.3, 1);
const lines = cues.lines as Record<string, string>;
const typing = cues.typing as Record<string, { start: number; gap: number }>;

/** 1文字ずつ出す。タイミングは cues.json（音と共通） */
const Typed: React.FC<{ k: string; style?: React.CSSProperties }> = ({ k, style }) => {
  const frame = useCurrentFrame();
  const { start, gap } = typing[k];
  return (
    <div style={{ whiteSpace: "nowrap", ...style }}>
      {[...lines[k]].map((ch, i) => {
        const s = start + i * gap;
        return (
          <span
            key={i}
            style={{
              display: "inline-block",
              opacity: interpolate(frame, [s, s + 4], [0, 1], CLAMP),
              translate: interpolate(frame, [s, s + 10], ["0px 24px", "0px 0px"], { ...CLAMP, easing: EASE }),
            }}
          >
            {ch}
          </span>
        );
      })}
    </div>
  );
};

/** 区間だけ見せる層。前後6フレームでフェード */
const Layer: React.FC<{ a: number; b: number; children: React.ReactNode; gap?: number }> = ({ a, b, children, gap = 28 }) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill
      style={{
        opacity: interpolate(frame, [a, a + 6, b - 6, b], [0, 1, 1, 0], CLAMP),
        justifyContent: "center",
        alignItems: "center",
        flexDirection: "column",
        gap,
      }}
    >
      {children}
    </AbsoluteFill>
  );
};

const SERIFLESS = { fontFamily: SANS, fontWeight: 900 } as const;

export const Hook: React.FC = () => {
  const frame = useCurrentFrame();
  const ready = useFonts();

  // 進む点の位置（221年 → 263年）
  const dot = interpolate(frame, cues.dotMove as [number, number], [0, 1], { ...CLAMP, easing: EASE });
  const yearNow = Math.round(cues.years.from + dot * (cues.years.to - cues.years.from));
  const axisL = 360;
  const axisW = 1200;
  const dotX = axisL + dot * axisW;
  const strikeP = interpolate(frame, cues.strike as [number, number], [0, 1], { ...CLAMP, easing: Easing.out(Easing.cubic) });

  if (!ready) return null;

  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      {/* 1. 問い */}
      <Layer a={0} b={96}>
        <Typed k="a1" style={{ ...SERIFLESS, fontSize: 96, color: C.ink }} />
        <Typed k="a2" style={{ ...SERIFLESS, fontSize: 96, color: C.ink }} />
      </Layer>

      {/* 2. 規模の順（数値ではなくイメージ） */}
      <Layer a={90} b={192} gap={0}>
        <Typed k="b" style={{ ...SERIFLESS, fontSize: 84, color: C.ink }} />
        <div style={{ marginTop: 72, width: 1100, display: "flex", flexDirection: "column", gap: 26 }}>
          {cues.rank.bars.map((bar, i) => {
            const p = interpolate(frame, [cues.rank.grow + i * 8, cues.rank.grow + i * 8 + 22], [0, 1], { ...CLAMP, easing: EASE });
            const isShu = bar.name === "蜀";
            return (
              <div key={bar.name} style={{ display: "flex", alignItems: "center", gap: 28 }}>
                <div style={{ width: 80, ...SERIFLESS, fontSize: 58, color: isShu ? C.accent : C.ink }}>{bar.name}</div>
                <div style={{ height: 54, width: bar.w * p, background: isShu ? C.accent : C.faint }} />
              </div>
            );
          })}
          <div
            style={{
              marginTop: 12,
              fontFamily: MONO,
              fontSize: 30,
              color: C.dim,
              opacity: interpolate(frame, [170, 184], [0, 1], CLAMP),
            }}
          >
            規模の順（イメージ・数値ではありません）
          </div>
        </div>
      </Layer>

      {/* 3. 誤解を打ち消す */}
      <Layer a={186} b={282} gap={34}>
        <div style={{ position: "relative", display: "inline-block" }}>
          <Typed k="c" style={{ ...SERIFLESS, fontSize: 112, color: C.ink }} />
          <div
            style={{
              position: "absolute",
              left: -24,
              right: -24,
              top: "52%",
              height: 16,
              background: C.accent,
              rotate: "-3deg",
              transformOrigin: "left center",
              scale: `${strikeP} 1`,
            }}
          />
        </div>
        <Typed k="d" style={{ ...SERIFLESS, fontSize: 110, color: C.accent }} />
      </Layer>

      {/* 4. 年号で確かめる */}
      <Layer a={282} b={392} gap={0}>
        <AbsoluteFill>
          <div style={{ position: "absolute", left: axisL, top: 560, width: axisW, height: 6, background: C.faint }} />
          <div style={{ position: "absolute", left: axisL, top: 560, width: axisW * dot, height: 6, background: C.accent }} />
          <div
            style={{
              position: "absolute",
              left: dotX - 15,
              top: 545,
              width: 30,
              height: 30,
              borderRadius: 15,
              background: C.ink,
            }}
          />
          <div
            style={{
              position: "absolute",
              left: dotX,
              top: 320,
              transform: "translateX(-50%)",
              ...SERIFLESS,
              fontSize: 120,
              color: C.ink,
              fontVariantNumeric: "tabular-nums",
              whiteSpace: "nowrap",
            }}
          >
            {yearNow}
          </div>
          <div
            style={{
              position: "absolute",
              left: axisL,
              top: 616,
              opacity: interpolate(frame, [300, 312], [0, 1], CLAMP),
            }}
          >
            <div style={{ ...SERIFLESS, fontSize: 64, color: C.ink }}>221年</div>
            <div style={{ fontFamily: MONO, fontSize: 32, color: C.dim, marginTop: 8 }}>蜀の建国（劉備が即位）</div>
          </div>
          <div
            style={{
              position: "absolute",
              right: 1920 - (axisL + axisW),
              top: 616,
              textAlign: "right",
              opacity: interpolate(frame, [340, 352], [0, 1], CLAMP),
            }}
          >
            <div style={{ ...SERIFLESS, fontSize: 64, color: C.ink }}>263年</div>
            <div style={{ fontFamily: MONO, fontSize: 32, color: C.dim, marginTop: 8 }}>魏により滅亡</div>
          </div>
          <div
            style={{
              position: "absolute",
              left: 0,
              right: 0,
              top: 730,
              textAlign: "center",
              ...SERIFLESS,
              fontSize: 130,
              color: C.accent,
              opacity: interpolate(frame, [350, 364], [0, 1], { ...CLAMP, easing: EASE }),
            }}
          >
            42年
          </div>
        </AbsoluteFill>
      </Layer>

      {/* 5. 静寂（388–470）の後、問いが戻る */}
      <Layer a={466} b={900} gap={0}>
        <AbsoluteFill style={{ justifyContent: "center", alignItems: "center", flexDirection: "column", gap: 0 }}>
          <Typed k="a3" style={{ ...SERIFLESS, fontSize: 96, color: C.ink, position: "relative", top: -170 }} />
          <div style={{ position: "absolute", top: 560, left: 0, right: 0, display: "flex", justifyContent: "center", gap: 40 }}>
            {cues.keywords.words.map((w, i) => {
              const s = cues.keywords.starts[i];
              return (
                <div
                  key={w}
                  style={{
                    opacity: interpolate(frame, [s, s + 8], [0, 1], CLAMP),
                    translate: `0px ${interpolate(frame, [s, s + 12], [24, 0], { ...CLAMP, easing: EASE })}px`,
                    border: `2px solid ${C.faint}`,
                    borderRadius: 8,
                    padding: "22px 48px",
                    ...SERIFLESS,
                    fontSize: 64,
                    color: C.ink,
                  }}
                >
                  {w}
                </div>
              );
            })}
          </div>
          <div style={{ position: "absolute", top: 800, left: 0, right: 0, textAlign: "center" }}>
            <Typed k="end" style={{ fontFamily: MONO, fontWeight: 700, fontSize: 64, color: C.accent, display: "inline-block" }} />
          </div>
        </AbsoluteFill>
      </Layer>

      <Audio src={staticFile("hook.wav")} />
    </AbsoluteFill>
  );
};
