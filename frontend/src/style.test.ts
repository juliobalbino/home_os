import { describe, expect, it } from "vitest";
// @ts-expect-error Node.js types are intentionally not part of the frontend bundle.
import { readFileSync } from "node:fs";
const styles = readFileSync("src/style.css", "utf8");

describe("responsive accessibility foundation", () => {
  it("defines semantic colors, visible keyboard focus, and reduced motion", () => {
    expect(styles).toContain("--color-text");
    expect(styles).toMatch(/:focus-visible\s*\{/);
    expect(styles).toContain("prefers-reduced-motion: reduce");
  });

  it("provides a mobile layout breakpoint and allows flex children to shrink", () => {
    expect(styles).toContain("@media (max-width: 768px)");
    expect(styles).toMatch(/min-width:\s*0/);
  });
});
