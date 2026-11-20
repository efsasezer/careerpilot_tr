import { afterEach, describe, expect, it, vi } from "vitest";
import { apiRequest, getApiUrl } from "./client";

describe("apiRequest", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends the session cookie and never an Authorization header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest("/profile")).resolves.toEqual({ ok: true });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${getApiUrl()}/profile`);
    expect(init.credentials).toBe("include");
    expect(init.headers.has("Authorization")).toBe(false);
  });

  it("shows a meaningful message when a write fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("oops", { status: 500 })));
    await expect(apiRequest("/profile", { method: "PUT", body: "{}" })).rejects.toMatchObject({
      status: 500,
      message: "Kaydedilemedi, tekrar dene.",
    });
  });
});
