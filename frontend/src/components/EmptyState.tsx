import { Icon, type IconName } from "./Icon";

export function EmptyState({ icon = "check", title, children }: { icon?: IconName; title: string; children: string }) {
  return (
    <div className="empty">
      <span className="ring"><Icon name={icon} large /></span>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
