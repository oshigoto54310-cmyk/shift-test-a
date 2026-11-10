import React from "react";
import { Audio } from "@remotion/media";
import { AbsoluteFill, Sequence, staticFile } from "remotion";
import { useFonts } from "./lib/useFonts";
import { Climax } from "./scenes/Climax";
import { Manifesto } from "./scenes/Manifesto";
import { Outro } from "./scenes/Outro";
import { ProofData } from "./scenes/ProofData";
import { ProofMath } from "./scenes/ProofMath";
import { ProofRepo } from "./scenes/ProofRepo";
import { ProofSound } from "./scenes/ProofSound";
import { Prompt } from "./scenes/Prompt";
import { C, T } from "./theme";

/**
 * 「一行で、ここまで。」— 52秒。
 * 静（一行）→ 宣言 → 証拠×4（速い）→ 静寂 → 見せ場 → 静（次の一行）
 */
export const Showcase: React.FC = () => {
  useFonts();
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <Sequence name="1 一行" from={T.prompt.from} durationInFrames={T.prompt.dur}>
        <Prompt />
      </Sequence>
      <Sequence name="2 宣言" from={T.manifesto.from} durationInFrames={T.manifesto.dur}>
        <Manifesto />
      </Sequence>
      <Sequence name="3 数式" from={T.math.from} durationInFrames={T.math.dur}>
        <ProofMath />
      </Sequence>
      <Sequence name="4 データ" from={T.data.from} durationInFrames={T.data.dur}>
        <ProofData />
      </Sequence>
      <Sequence name="5 実物" from={T.repo.from} durationInFrames={T.repo.dur}>
        <ProofRepo />
      </Sequence>
      <Sequence name="6 音" from={T.sound.from} durationInFrames={T.sound.dur}>
        <ProofSound />
      </Sequence>
      <Sequence name="7 見せ場" from={T.climax.from} durationInFrames={T.climax.dur}>
        <Climax />
      </Sequence>
      <Sequence name="8 次の一行" from={T.outro.from} durationInFrames={T.outro.dur}>
        <Outro />
      </Sequence>
      <Audio src={staticFile("soundtrack.wav")} />
    </AbsoluteFill>
  );
};
