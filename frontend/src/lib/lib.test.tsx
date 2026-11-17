import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { displayPath, formatCost, formatLatency, stripFindingKey } from "./format";
import { renderBold } from "./boldSplit";
import { findQuote } from "./quote";

describe("format", () => {
  it("follows the backend format_cost convention", () => {
    expect(formatCost(0.0041, true)).toBe("$0.004");
    expect(formatCost(0.0041, false)).toBe("$0.004+");
    expect(formatCost(0, false)).toBe("n/a");
  });
  it("formats latency in seconds with one decimal", () => {
    expect(formatLatency(3140)).toBe("3.1 s");
    expect(formatLatency(null)).toBe("–");
  });
  it("shows corpus paths relative to the corpus", () => {
    expect(displayPath("/mnt/x/stacklight/corpus/handbook/a.md")).toBe("corpus/handbook/a.md");
    expect(displayPath("corpus/handbook/a.md")).toBe("corpus/handbook/a.md");
    expect(displayPath("handbook/a.md")).toBe("handbook/a.md");
  });
  it("strips the curator dedupe key", () => {
    expect(stripFindingKey("[conflict:3-7] 'A' and 'B' conflict")).toBe("'A' and 'B' conflict");
  });
});

describe("renderBold", () => {
  it("renders ** runs as strong without raw asterisks", () => {
    render(<p>{renderBold("**Refund window:** 14 days")}</p>);
    expect(screen.getByText("Refund window:").tagName).toBe("STRONG");
    expect(document.body.textContent).toBe("Refund window: 14 days");
  });
  it("keeps an unmatched marker literal and never parses HTML", () => {
    render(<p>{renderBold("a **b <img src=x onerror=alert(1)>")}</p>);
    expect(document.body.textContent).toBe("a **b <img src=x onerror=alert(1)>");
    expect(document.querySelector("img")).toBeNull();
  });
});

describe("findQuote", () => {
  it("matches across whitespace differences and returns original offsets", () => {
    const text = "Intro.\n\n| Business | 1 hour,\n  24/7 |\nTail";
    const r = findQuote(text, "1 hour, 24/7")!;
    expect(text.slice(r[0], r[1])).toBe("1 hour,\n  24/7");
  });
  it("returns null when absent", () => {
    expect(findQuote("abc", "xyz")).toBeNull();
    expect(findQuote("abc", "  ")).toBeNull();
  });
});
