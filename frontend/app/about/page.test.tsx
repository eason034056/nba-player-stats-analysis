import type { ReactNode } from "react";
import { render, screen, within } from "@testing-library/react";
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
  it("describes the vig math, the NBA blend, and the tier source", () => {
    render(<AboutPage />);

    expect(screen.getByRole("heading", { name: /how we read a prop/i })).toBeInTheDocument();
    expect(screen.getByText("p_fair = p / (p_over + p_under)")).toBeInTheDocument();
    expect(screen.getByText(/fair price: 50% \/ 50%/i)).toBeInTheDocument();

    expect(screen.getByRole("heading", { name: /blend the signals/i })).toBeInTheDocument();
    const signals = within(screen.getByRole("list", { name: /signals in the blend/i }))
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(signals).toHaveLength(5);
    expect(signals[0]).toMatch(/^Market price.*Base$/);
    expect(signals.slice(1, 4).every((text) => text?.endsWith("± 0.15"))).toBe(true);
    expect(signals[4]).toMatch(/^Projection.*Off$/);
    expect(screen.getByText(/sigmoid\(logit\(consensus\) \+ a \+ b × clip\(nudges, ± 0\.35\)\)/)).toBeInTheDocument();
    expect(screen.getByText(/player listed out gets no number/i)).toBeInTheDocument();

    expect(screen.getByText(/combined probability on NBA, the historical hit rate on WNBA/i)).toBeInTheDocument();
    expect(screen.queryByText(/planned/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/not blended/i)).not.toBeInTheDocument();

    expect(screen.getByText(/for informational and research purposes only/i)).toBeInTheDocument();
    expect(screen.getByText(/this is not betting advice/i)).toBeInTheDocument();
    const hrefs = screen.getAllByRole("link").map((link) => link.getAttribute("href"));
    expect(hrefs).toEqual(
      expect.arrayContaining(["/picks", "/betslip", "/wnba/picks", "/wnba/betslip"]),
    );
  });
});
