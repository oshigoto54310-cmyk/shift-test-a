import { useEffect, useState } from "react";
import { useDelayRender } from "remotion";
import { fontsReady } from "../theme";

/** フォントの読み込み完了までレンダリングを待たせる */
export const useFonts = (): boolean => {
  const { delayRender, continueRender } = useDelayRender();
  const [ready, setReady] = useState(false);
  const [handle] = useState(() => delayRender("fonts"));
  useEffect(() => {
    let alive = true;
    fontsReady.then(() => {
      if (!alive) return;
      setReady(true);
      continueRender(handle);
    });
    return () => {
      alive = false;
    };
  }, [continueRender, handle]);
  return ready;
};
