import type { ReactNode } from "react";

// Inline SVG icons (24x24 grid, stroke-based). No icon font, no CDN.
const PATHS: Record<string, ReactNode> = {
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  x: <path d="M6 6l12 12M18 6L6 18" />,
  dash: <path d="M7 12h10" />,
  dot: <circle cx="12" cy="12" r="4" fill="currentColor" stroke="none" />,
  warn: <><path d="M12 3.8l9.2 16H2.8z" /><path d="M12 10v4.2M12 17.2v.01" /></>,
  help: <><circle cx="12" cy="12" r="9.2" /><path d="M9.6 9.6a2.5 2.5 0 1 1 3.6 2.2c-.8.4-1.2.9-1.2 1.8M12 17.2v.01" /></>,
  moon: <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z" />,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4" /></>,
  shield: <><path d="M12 3l8 3v5.5c0 4.7-3.2 8.2-8 9.5-4.8-1.3-8-4.8-8-9.5V6z" /><path d="M8.5 12l2.5 2.5 4.5-5" /></>,
  file: <><path d="M7 3h7l5 5v13H7z" /><path d="M14 3v5h5" /></>,
  send: <path d="M12 19V5M6 11l6-6 6 6" />,
  search: <><circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" /></>,
  swap: <path d="M4 9h13l-3-3M20 15H7l3 3" />,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  mail: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3.5 7l8.5 6 8.5-6" /></>,
  activity: <path d="M3 12h4l3-7 4 14 3-7h4" />,
  inbox: <><path d="M3 13l3-8h12l3 8v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" /><path d="M3 13h5l1 2h6l1-2h5" /></>,
  chat: <path d="M4 5h16v11H9l-5 4z" />,
  refresh: <path d="M20 11a8 8 0 1 0-2.3 5.7M20 5v6h-6" />,
  pause: <path d="M9 5v14M15 5v14" />,
  power: <path d="M12 3v8M6.6 6.6a8 8 0 1 0 10.8 0" />,
  archive: <path d="M3 5h18v4H3zM5 9v10h14V9M10 13h4" />,
  lock: <><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></>,
  plane: <path d="M4 12l16-8-6 16-3-7z" />,
};

export type IconName = keyof typeof PATHS;

export function Icon({ name, large = false }: { name: IconName; large?: boolean }) {
  return (
    <svg className={`i${large ? " lg" : ""}`} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {PATHS[name]}
    </svg>
  );
}

export function Logo() {
  return (
    <svg className="logo" viewBox="0 0 28 28" aria-hidden="true">
      <rect x="3" y="4" width="22" height="6" rx="3" fill="currentColor" />
      <rect x="3" y="11" width="22" height="6" rx="3" fill="currentColor" opacity=".6" />
      <rect x="3" y="18" width="22" height="6" rx="3" fill="currentColor" opacity=".3" />
    </svg>
  );
}
