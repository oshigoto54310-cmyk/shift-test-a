import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";

export const C = {
  bg: "#06070a",
  ink: "#f4f1ea",
  dim: "rgba(244,241,234,0.42)",
  faint: "rgba(244,241,234,0.16)",
  accent: "#ff4a1c",
};

export const SANS = '"Noto Sans JP", sans-serif';
export const SERIF = '"Noto Serif JP", serif';
export const MONO = '"JetBrains Mono", "Noto Sans JP", monospace';

// 可変フォントを1ファイルずつ読み込む（Canvas への文字描画でも使うので完了を待てるようにする）
export const fontsReady: Promise<unknown> =
  typeof document === "undefined"
    ? Promise.resolve()
    : Promise.all([
        loadFont({ family: "Noto Sans JP", url: staticFile("fonts/NotoSansJP.ttf"), weight: "100 900" }),
        loadFont({ family: "Noto Serif JP", url: staticFile("fonts/NotoSerifJP.ttf"), weight: "200 900" }),
        loadFont({ family: "JetBrains Mono", url: staticFile("fonts/JetBrainsMono.ttf"), weight: "100 800" }),
      ]);

// ---- 全体のタイムライン（30fps / 120BPM: 1拍=15f, 1小節=60f）
export const FPS = 30;
export const BEAT = 15;
export const BAR = 60;
export const T = {
  prompt: { from: 0, dur: 210 },
  manifesto: { from: 210, dur: 240 },
  math: { from: 450, dur: 180 },
  data: { from: 630, dur: 150 },
  repo: { from: 780, dur: 180 },
  sound: { from: 960, dur: 120 },
  climax: { from: 1080, dur: 300 }, // 先頭30fはブレイク（静寂）
  outro: { from: 1380, dur: 180 },
  total: 1560,
};

export const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
export const CLAMP = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
