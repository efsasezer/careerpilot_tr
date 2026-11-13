import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MatchBadge } from "./MatchBadge";

describe("MatchBadge", () => {
  it("renders the backend classification without recalculating it", () => {
    render(<MatchBadge category="POTANSİYEL OLARAK UYGUN" />);

    expect(screen.getByText("POTANSİYEL OLARAK UYGUN")).toBeInTheDocument();
  });
});
