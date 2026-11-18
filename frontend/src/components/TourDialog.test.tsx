import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TOUR_STEPS, TourDialog } from "./TourDialog";

function mountTargets() {
  document.body.insertAdjacentHTML("beforeend",
    '<div id="fx"><form data-tour="composer"></form><div data-tour="modes"></div><div data-tour="chips"></div>' +
    '<section data-panel="trace"></section><section data-panel="queue"></section></div>');
}

beforeEach(() => {
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => { cb(0); return 1; });
  vi.stubGlobal("cancelAnimationFrame", () => {});
});
afterEach(() => { cleanup(); document.getElementById("fx")?.remove(); vi.unstubAllGlobals(); });

describe("TourDialog", () => {
  it("renders nothing when closed", () => {
    render(<TourDialog open={false} onClose={() => {}} returnFocusTo={null} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("walks every step, switches the phone tab for panel steps, then closes", async () => {
    mountTargets();
    const onClose = vi.fn();
    const onTab = vi.fn();
    const user = userEvent.setup();
    render(<TourDialog open onClose={onClose} returnFocusTo={null} onTab={onTab} />);
    expect(await screen.findByText(TOUR_STEPS[0].title)).toBeInTheDocument();
    expect(screen.getByText(`Step 1 of ${TOUR_STEPS.length}`)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back" })).toBeNull();
    for (let n = 1; n < TOUR_STEPS.length; n++) await user.click(screen.getByRole("button", { name: "Next" }));
    expect(onTab).toHaveBeenCalledWith("trace");
    expect(onTab).toHaveBeenCalledWith("queue");
    await user.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByText(`Step ${TOUR_STEPS.length - 1} of ${TOUR_STEPS.length}`)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(screen.getByRole("button", { name: "Start exploring" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("skips steps whose target is not on screen", () => {
    render(<TourDialog open onClose={() => {}} returnFocusTo={null} />);
    expect(screen.getByText("Step 1 of 1")).toBeInTheDocument();
  });

  it("closes on Escape and returns focus to the trigger", async () => {
    const trigger = document.createElement("button");
    document.body.appendChild(trigger);
    const onClose = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(<TourDialog open onClose={onClose} returnFocusTo={trigger} />);
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
    rerender(<TourDialog open={false} onClose={onClose} returnFocusTo={trigger} />);
    expect(document.activeElement).toBe(trigger);
  });
});
