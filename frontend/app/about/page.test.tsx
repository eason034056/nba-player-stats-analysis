import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AboutPage from "@/app/about/page";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: ReactNode;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

describe("AboutPage", () => {
  it("describes the vig math and marks a blend as planned", () => {
    render(<AboutPage />);

    expect(screen.getByRole("heading", { name: /how we read a prop/i })).toBeInTheDocument();
    expect(screen.getByText(/not blended into a single probability/i)).toBeInTheDocument();
    expect(screen.getByText("p_fair = p / (p_over + p_under)")).toBeInTheDocument();
    expect(screen.getByText(/fair price: 50% \/ 50%/i)).toBeInTheDocument();
    expect(screen.getByText(/planned: one blended probability/i)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /blend five signals/i })).not.toBeInTheDocument();
    const hrefs = screen.getAllByRole("link").map((link) => link.getAttribute("href"));
    expect(hrefs).toEqual(
      expect.arrayContaining(["/picks", "/betslip", "/wnba/picks", "/wnba/betslip"]),
    );
  });
});
