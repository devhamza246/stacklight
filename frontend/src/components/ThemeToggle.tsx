import { useTheme } from "../state/ThemeProvider";
import { Icon } from "./Icon";

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  return (
    <button
      className="icon-btn theme-toggle"
      type="button"
      aria-pressed={dark}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      onClick={toggle}
    >
      <Icon name={dark ? "sun" : "moon"} large />
    </button>
  );
}
