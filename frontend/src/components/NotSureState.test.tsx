import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { NotSureState } from "./NotSureState";
import type { AbstainEvent } from "../api/types";

const abstain: AbstainEvent = {
  type: "abstain", reason: "not_in_kb",
  closest: [
    { chunk_id: 2, title: "PTO and Holidays", source: "handbook/pto-and-holidays.md" },
    { chunk_id: 1, title: "Benefits and Stipends", source: "handbook/benefits-and-stipends.md" },
  ],
};

describe("NotSureState", () => {
  it("renders calmly with the closest sources in retrieval order and a rephrase hint", () => {
    const hits = [
      { chunk_id: 1, title: "Benefits and Stipends", source: "s", ord: 0, score: 0.5 },
      { chunk_id: 2, title: "PTO and Holidays", source: "s", ord: 0, score: 0.3 },
    ];
    render(<NotSureState abstain={abstain} hits={hits} onRephrase={() => {}} onOpenSource={() => {}} />);
    expect(screen.getByRole("heading", { name: "I’m not sure" })).toBeInTheDocument();
    expect(screen.getByText(/Try rephrasing/)).toBeInTheDocument();
    expect(screen.getByText("Closest sources, none of them answer it")).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Benefits and Stipends");
    expect(items[0]).toHaveTextContent("Closest match");
    expect(items[1]).toHaveTextContent("PTO and Holidays");
  });

  it("has no 'Ask a human' action (not an API feature)", () => {
    render(<NotSureState abstain={abstain} onRephrase={() => {}} onOpenSource={() => {}} />);
    expect(screen.queryByText(/ask a human/i)).toBeNull();
  });

  it("rephrase and source buttons call back", async () => {
    const onRephrase = vi.fn();
    const onOpenSource = vi.fn();
    render(<NotSureState abstain={abstain} onRephrase={onRephrase} onOpenSource={onOpenSource} />);
    await userEvent.click(screen.getByRole("button", { name: "Rephrase the question" }));
    expect(onRephrase).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: /PTO and Holidays/ }));
    expect(onOpenSource).toHaveBeenCalledWith({ chunkId: 2, title: "PTO and Holidays", source: "handbook/pto-and-holidays.md" }, expect.any(HTMLElement));
  });
});
