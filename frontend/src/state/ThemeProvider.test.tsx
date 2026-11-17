import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "./ThemeProvider";
import { ThemeToggle } from "../components/ThemeToggle";

function mockSystem(dark: boolean) {
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: dark && q.includes("dark"), media: q, addEventListener: () => {}, removeEventListener: () => {},
  }));
}

beforeEach(() => { document.documentElement.removeAttribute("data-theme"); localStorage.clear(); });
afterEach(() => vi.unstubAllGlobals());

const mount = () => render(<ThemeProvider><ThemeToggle /></ThemeProvider>);

describe("ThemeProvider", () => {
  it("follows the system by default and sets no explicit attribute", () => {
    mockSystem(true);
    mount();
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(screen.getByRole("button", { name: "Switch to light theme" })).toHaveAttribute("aria-pressed", "true");
  });

  it("toggles, sets data-theme and persists the choice", async () => {
    mockSystem(false);
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("stacklight-theme")).toBe("dark");
  });

  it("restores a saved theme", () => {
    mockSystem(false);
    localStorage.setItem("stacklight-theme", "dark");
    mount();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("keeps working when localStorage throws on read and write", async () => {
    mockSystem(false);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    mount();
    await userEvent.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(screen.getByRole("button", { name: "Switch to light theme" })).toBeInTheDocument();
    vi.restoreAllMocks();
  });
});
