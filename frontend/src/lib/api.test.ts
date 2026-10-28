import { describe, expect, it } from "vitest";
import { apiOriginFromBase } from "./api";

describe("apiOriginFromBase", () => {
  it("returns the origin for an absolute API base URL", () => {
    expect(
      apiOriginFromBase(
        "https://api.example.test/api/v1",
        "https://home.example.test",
      ),
    ).toBe("https://api.example.test");
  });

  it("returns the page origin for a relative API base URL", () => {
    expect(apiOriginFromBase("/api/v1", "https://home.example.test")).toBe(
      "https://home.example.test",
    );
  });
});
