"use client";

import { useEffect, useRef, useState } from "react";
import { get } from "./api";

export function useApi<T>(path: string, refreshMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    const load = () =>
      get<T>(path)
        .then((d) => live && setData(d))
        .catch((e) => live && setError(String(e)));
    load();
    const id = refreshMs ? setInterval(load, refreshMs) : undefined;
    return () => {
      live = false;
      if (id) clearInterval(id);
    };
  }, [path, refreshMs]);
  return { data, error };
}

/** Count-up for the hero numbers: 900ms ease-out, respects reduced motion. */
export function useCountUp(target: number, ms = 900) {
  const [value, setValue] = useState(0);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setValue(target);
      return;
    }
    const t0 = performance.now();
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / ms);
      setValue(target * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }, [target, ms]);
  return value;
}
