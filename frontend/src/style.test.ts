import { describe, expect, it } from "vitest";
// @ts-expect-error Node.js types are intentionally not part of the frontend bundle.
import { readFileSync } from "node:fs";
const styles = readFileSync("src/styles/ladrilho.css", "utf8");

describe("responsive accessibility foundation", () => {
  it("defines semantic colors for both schemes, visible focus, and reduced motion", () => {
    expect(styles).toContain("--color-text");
    expect(styles).toContain('[data-mantine-color-scheme="dark"]');
    expect(styles).toMatch(/:focus-visible\s*\{/);
    expect(styles).toContain("prefers-reduced-motion: reduce");
  });

  it("starts from the phone layout and lets flex children shrink", () => {
    expect(styles).toContain("@media (min-width: 48em)");
    expect(styles).toContain("@media (min-width: 64em)");
    expect(styles).toMatch(/min-width:\s*0/);
    expect(styles).toContain("env(safe-area-inset-bottom)");
  });
});
