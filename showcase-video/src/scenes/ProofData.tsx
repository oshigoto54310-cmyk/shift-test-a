import React from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";
import { ProofLabels } from "../lib/Proof";
import { C, CLAMP, MONO, SANS } from "../theme";

// サンプルデータ（12週の売上指数）
const THIS = [82, 85, 84, 90, 96, 93, 101, 108, 118, 111, 115, 124];
const LAST = [80, 81, 83, 84, 88, 90, 92, 97, 104, 103, 106, 109];
const sum = (a: number[]) => a.reduce((x, y) => x + y, 0);
const RATIO = (sum(THIS) / sum(LAST)) * 100;

const X0 = 1010;
const X1 = 1800;
const Y0 = 170;
const Y1 = 700;
const MIN = 70;
const MAX = 130;
const px = (i: number) => X0 + (i / (THIS.length - 1)) * (X1 - X0);
const py = (v: number) => Y1 - ((v - MIN) / (MAX - MIN)) * (Y1 - Y0);

// Catmull-Rom → ベジェでなめらかな線に
const smooth = (vals: number[]) => {
  const p = vals.map((v, i) => [px(i), py(v)]);
  let d = `M ${p[0][0]} ${p[0][1]}`;
  for (let i = 0; i < p.length - 1; i++) {
    const p0 = p[Math.max(0, i - 1)];
    const p1 = p[i];
    const p2 = p[i + 1];
    const p3 = p[Math.min(p.length - 1, i + 2)];
    const t = 0.18;
    d += ` C ${p1[0] + (p2[0] - p0[0]) * t} ${p1[1] + (p2[1] - p0[1]) * t}, ${p2[0] - (p3[0] - p1[0]) * t} ${p2[1] - (p3[1] - p1[1]) * t}, ${p2[0]} ${p2[1]}`;
  }
  return d;
};
const THIS_D = smooth(THIS);
const LAST_D = smooth(LAST);

/** 02 データ — 主役は数字ひとつ。グラフは根拠として脇に置く。 */
export const ProofData: React.FC = () => {
  const frame = useCurrentFrame();
  const value = interpolate(frame, [4, 52], [100, RATIO], { ...CLAMP, easing: Easing.out(Easing.cubic) });
  const drawn = interpolate(frame, [10, 74], [0, 1], { ...CLAMP, easing: Easing.bezier(0.45, 0, 0.2, 1) });
  const lastI = THIS.length - 1;
  const ring = (frame - 74) / 22;
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <div style={{ position: "absolute", left: 100, top: 250 }}>
        <div style={{ fontFamily: SANS, fontWeight: 600, fontSize: 46, color: C.dim, opacity: interpolate(frame, [0, 8], [0, 1], CLAMP) }}>
          前年比
        </div>
        <div
          style={{
            fontFamily: SANS,
            fontWeight: 900,
            fontSize: 268,
            lineHeight: 1.05,
            letterSpacing: "-0.04em",
            color: C.ink,
            fontVariantNumeric: "tabular-nums",
            whiteSpace: "nowrap",
            opacity: interpolate(frame, [2, 8], [0, 1], CLAMP),
          }}
        >
          {value.toFixed(1)}
          <span style={{ fontSize: 110, color: C.accent, marginLeft: 10 }}>%</span>
        </div>
      </div>

      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        <defs>
          <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={C.accent} stopOpacity="0.32" />
            <stop offset="1" stopColor={C.accent} stopOpacity="0" />
          </linearGradient>
          <clipPath id="reveal">
            <rect x={X0 - 20} y={0} width={(X1 - X0 + 40) * drawn} height={1080} />
          </clipPath>
        </defs>
        {[80, 100, 120].map((v) => (
          <line key={v} x1={X0} x2={X1} y1={py(v)} y2={py(v)} stroke={C.faint} strokeWidth={1.5} opacity={interpolate(frame, [0, 12], [0, 1], CLAMP)} />
        ))}
        <g clipPath="url(#reveal)">
          <path d={`${THIS_D} L ${X1} ${Y1 + 40} L ${X0} ${Y1 + 40} Z`} fill="url(#area)" />
          <path d={LAST_D} fill="none" stroke={C.dim} strokeWidth={3} strokeDasharray="4 10" strokeLinecap="round" />
          <path d={THIS_D} fill="none" stroke={C.accent} strokeWidth={8} strokeLinecap="round" strokeLinejoin="round" />
        </g>
        {frame >= 74 ? (
          <>
            <circle cx={px(lastI)} cy={py(THIS[lastI])} r={14 + Math.max(0, ring % 1.6) * 46} fill="none" stroke={C.accent} strokeWidth={3} opacity={Math.max(0, 1 - (ring % 1.6))} />
            <circle cx={px(lastI)} cy={py(THIS[lastI])} r={13} fill={C.ink} />
          </>
        ) : null}
      </svg>
      <div
        style={{
          position: "absolute",
          left: X0,
          top: Y1 + 34,
          width: X1 - X0,
          display: "flex",
          justifyContent: "space-between",
          fontFamily: MONO,
          fontSize: 26,
          color: C.dim,
          opacity: interpolate(frame, [8, 20], [0, 1], CLAMP),
        }}
      >
        <span>1週</span>
        <span>
          <span style={{ color: C.accent }}>━</span> 今年
          <span style={{ marginLeft: 28 }}>┄</span> 前年
        </span>
        <span>12週</span>
      </div>
      <ProofLabels index="02" tag="データ" caption="数字を、判断できる形に。" fact="12週累計 ・ サンプルデータ" />
    </AbsoluteFill>
  );
};
