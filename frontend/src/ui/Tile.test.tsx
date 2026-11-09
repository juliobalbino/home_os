import { render } from "@testing-library/react";
import { expect, it } from "vitest";
import { TileMark } from "./Tile";

it.each([
  ["arcos", "layout-grid"],
  ["losango", "wallet"],
  ["flor", "shopping-cart"],
  ["catavento", "checklist"],
  ["estrela", "home-2"],
  ["olho", "sparkles"],
] as const)(
  "uses a simple %s area icon without tile artwork",
  (motif, icon) => {
    const { container } = render(<TileMark motif={motif} />);
    expect(container.querySelector(`svg.tabler-icon-${icon}`)).not.toBeNull();
    expect(container.querySelector("clipPath, pattern, ellipse")).toBeNull();
    expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
  },
);
