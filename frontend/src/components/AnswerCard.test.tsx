import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { initialRun, type RunState } from "../state/runReducer";
import { AnswerCard } from "./AnswerCard";

const mount = (run: RunState) =>
  render(<AnswerCard run={run} openChunkId={null} onOpenSource={() => {}} onViewTrace={() => {}} />);

describe("AnswerCard verification gate", () => {
  it("renders streamed text only once `verified` has been received", () => {
    const tokens: RunState = { ...initialRun, phase: "running", text: "A P1 incident gets 1 hour." };
    const { rerender } = mount(tokens);
    expect(screen.queryByText(/A P1 incident/)).not.toBeInTheDocument();
    expect(screen.getByTestId("answer-body").querySelector(".skeleton")).not.toBeNull();
    rerender(<AnswerCard run={{ ...tokens, verified: { type: "verified", faithfulness: 1, claims_supported: 1, claims_total: 1 } }}
      openChunkId={null} onOpenSource={() => {}} onViewTrace={() => {}} />);
    expect(screen.getByText(/A P1 incident gets 1 hour\./)).toBeInTheDocument();
  });
});
