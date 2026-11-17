import { Icon, type IconName } from "./Icon";

export type Tab = "chat" | "trace" | "queue";
const TABS: { id: Tab; label: string; icon: IconName }[] = [
  { id: "chat", label: "Chat", icon: "chat" },
  { id: "trace", label: "Trace", icon: "activity" },
  { id: "queue", label: "Queue", icon: "inbox" },
];

/** Bottom navigation below 1024 px (one panel at a time). Hidden by CSS on wide screens. */
export function TabBar({ tab, onChange, queueCount }: { tab: Tab; onChange: (t: Tab) => void; queueCount: number }) {
  return (
    <nav className="tabbar" aria-label="Sections">
      {TABS.map((t) => (
        <button key={t.id} className="tab" type="button" aria-current={tab === t.id ? "true" : "false"} onClick={() => onChange(t.id)}>
          <Icon name={t.icon} large />
          {t.label}
          {t.id === "queue" && queueCount > 0 && <span className="count" aria-label={`${queueCount} items to review`}>{queueCount}</span>}
        </button>
      ))}
    </nav>
  );
}
