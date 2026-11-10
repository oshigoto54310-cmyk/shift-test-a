import React from "react";
import { Composition } from "remotion";
import { Showcase } from "./Composition";
import { Hook } from "./sangoku/Hook";
import cues from "./sangoku/cues.json";
import { FPS, T } from "./theme";

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition id="Showcase" component={Showcase} durationInFrames={T.total} fps={FPS} width={1920} height={1080} />
      <Composition id="SangokuHook" component={Hook} durationInFrames={cues.total} fps={cues.fps} width={1920} height={1080} />
    </>
  );
};
