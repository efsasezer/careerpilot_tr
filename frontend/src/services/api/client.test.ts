import { afterEach, describe, expect, it, vi } from "vitest";
import { apiRequest } from "./client";

describe("apiRequest", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends the private API token in the Authorization header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ authenticated: true }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest("/auth/check", "session-secret")).resolves.toEqual({ authenticated: true });

    expect(fetchMock.mock.calls[0][1].headers.get("Authorization")).toBe("Bearer session-secret");
  });

  it("surfaces API authorization failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    ));

    await expect(apiRequest("/profile", "wrong-token")).rejects.toMatchObject({
      status: 401,
      message: "Unauthorized",
    });
  });
});
