import { render } from "@testing-library/react";
import { expect, it } from "vitest";
import { TileMark } from "./Tile";

it("keeps tile marks matte while retaining clipping and motif palette", () => {
  const { container } = render(<TileMark motif="estrela" />);
  expect(container.querySelector("linearGradient")).toBeNull();
  expect(container.querySelector("clipPath")).not.toBeNull();
  expect(container.querySelector("path[fill='var(--m-a)']")).not.toBeNull();
});
