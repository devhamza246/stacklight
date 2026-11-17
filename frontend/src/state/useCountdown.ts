import { useEffect, useState } from "react";

/** Whole seconds left until `deadline` (epoch ms); 0 when null or reached. Computed at render, re-rendered once a second. */
export function useCountdown(deadline: number | null): number {
  const [, tick] = useState(0);
  useEffect(() => {
    if (deadline === null) return;
    const id = setInterval(() => {
      tick((n) => n + 1);
      if (Date.now() >= deadline) clearInterval(id);
    }, 1000);
    return () => clearInterval(id);
  }, [deadline]);
  return deadline === null ? 0 : Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
}
