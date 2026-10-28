import { describe, expect, it } from "vitest";
import { localDay, localPeriod } from "./format";

describe("household date formatting", () => {
  it("uses the supplied timezone across a date and month boundary", () => {
    const instant = new Date("2026-03-01T02:30:00.000Z");
    expect(localDay(instant, "UTC")).toBe("2026-03-01");
    expect(localDay(instant, "America/Sao_Paulo")).toBe("2026-02-28");
    expect(localPeriod(instant, "America/Sao_Paulo")).toBe("2026-02");
  });
});
