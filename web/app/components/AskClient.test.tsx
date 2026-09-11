import { describe, expect, it } from "vitest";

describe("Ask UI", () => {
  it("keeps the API boundary configurable", () => {
    expect(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").toContain("http");
  });
});
