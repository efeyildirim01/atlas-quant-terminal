import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AnswerMarkdown, citationsIn } from "@/features/research/answer-markdown";
import { renderWithProviders } from "./render";

describe("AI answer rendering", () => {
  it("extracts single and grouped citations", () => {
    expect(citationsIn("CAGR 12.3% [E1], vol 20% [E2, E3].")).toEqual(["E1", "E2", "E3"]);
    expect(citationsIn("no cites [1] [X2]")).toEqual([]);
  });

  it("renders lists, bold and clickable chips; unknown ids are flagged; never injects HTML", () => {
    const onCite = vi.fn();
    renderWithProviders(
      <AnswerMarkdown known={new Set(["E1"])} onCite={onCite}
        text={"## Summary\n- **D-EQF** grew 12.3% [E1]\n- risk [E9]\n<img src=x onerror=alert(1)>"} />,
    );
    expect(screen.getByRole("heading", { name: "Summary" })).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("D-EQF").tagName).toBe("STRONG");
    const chips = screen.getAllByTestId("citation");
    expect(chips.map((c) => c.textContent)).toEqual(["E1", "E9"]);
    expect(chips[1].getAttribute("title")).toBe("E9 does not exist");
    fireEvent.click(chips[0]);
    expect(onCite).toHaveBeenCalledWith("E1");
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeTruthy();
  });
});
