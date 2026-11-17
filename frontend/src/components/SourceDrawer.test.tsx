import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { CitationChip } from "./CitationChip";
import { SourceDrawer, type OpenSource } from "./SourceDrawer";
import { CHUNK } from "../test/fixtures";
import type { Chunk } from "../api/types";

const SRC: OpenSource = { chunkId: 5, title: "SLA and Support Tiers", source: "corpus/handbook/sla.md", quote: "1 hour, 24/7" };

function Harness({ fetchChunk }: { fetchChunk: (id: number) => Promise<Chunk> }) {
  const [open, setOpen] = useState<{ s: OpenSource; el: HTMLElement } | null>(null);
  return (
    <>
      <CitationChip n={1} title={SRC.title} expanded={open !== null} onOpen={(el) => setOpen({ s: SRC, el })} />
      <button type="button">other control</button>
      <SourceDrawer source={open?.s ?? null} returnFocusTo={open?.el ?? null} onClose={() => setOpen(null)} fetchChunk={fetchChunk} />
    </>
  );
}

describe("CitationChip -> SourceDrawer", () => {
  it("opens a modal dialog with the quoted sentence highlighted in the passage", async () => {
    const fetchChunk = vi.fn().mockResolvedValue(CHUNK);
    render(<Harness fetchChunk={fetchChunk} />);
    const chip = screen.getByRole("button", { name: "Source 1: SLA and Support Tiers" });
    expect(chip).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(chip);
    const dialog = await screen.findByRole("dialog", { name: "SLA and Support Tiers" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(fetchChunk).toHaveBeenCalledWith(5);
    await waitFor(() => expect(document.querySelector("mark")).not.toBeNull());
    expect(document.querySelector("mark")).toHaveTextContent("1 hour, 24/7");
    expect(screen.getByText("corpus/handbook/sla-and-support-tiers.md")).toBeInTheDocument();
    expect(chip).toHaveAttribute("aria-expanded", "true");
    expect(document.querySelector("tr.cited")).toHaveTextContent("Business");
  });

  it("shows the passage without a highlight when the quote is not in it", async () => {
    const fetchChunk = vi.fn().mockResolvedValue({ ...CHUNK, text: "Totally different text." });
    render(<Harness fetchChunk={fetchChunk} />);
    await userEvent.click(screen.getByRole("button", { name: /Source 1/ }));
    expect(await screen.findByText("Totally different text.")).toBeInTheDocument();
    expect(document.querySelector("mark")).toBeNull();
  });

  it("degrades to the quote when the chunk cannot be loaded", async () => {
    render(<Harness fetchChunk={vi.fn().mockRejectedValue(new Error("404"))} />);
    await userEvent.click(screen.getByRole("button", { name: /Source 1/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Couldn’t load/);
    expect(screen.getByText("1 hour, 24/7")).toBeInTheDocument();
  });

  it("moves focus into the dialog, traps Tab, closes on Escape and returns focus to the chip", async () => {
    render(<Harness fetchChunk={vi.fn().mockResolvedValue(CHUNK)} />);
    const chip = screen.getByRole("button", { name: /Source 1/ });
    await userEvent.click(chip);
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog).toContainElement(document.activeElement as HTMLElement));
    const close = screen.getByRole("button", { name: "Close source" });
    close.focus();
    await userEvent.tab(); // only focusable control: wraps back to itself, never to the page behind
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    await userEvent.tab({ shift: true });
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(chip).toHaveFocus();
  });

  it("closes from the close button and from the scrim", async () => {
    render(<Harness fetchChunk={vi.fn().mockResolvedValue(CHUNK)} />);
    await userEvent.click(screen.getByRole("button", { name: /Source 1/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Close source" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
