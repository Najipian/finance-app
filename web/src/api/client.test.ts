import { api, ApiError, clearTokens, setSessionEndedHandler, storeTokens } from "./client";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("api client", () => {
  beforeEach(() => clearTokens());

  it("sends the bearer token and parses JSON", async () => {
    storeTokens({ access_token: "access-1", refresh_token: "refresh-1", expires_in: 900 });
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(json(200, { ok: true }));

    await expect(api("/me")).resolves.toEqual({ ok: true });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/me");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer access-1");
  });

  it("refreshes once for concurrent 401s, then retries", async () => {
    storeTokens({ access_token: "expired", refresh_token: "refresh-1", expires_in: 900 });
    let refreshes = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) {
        refreshes += 1;
        return json(200, { access_token: "fresh", refresh_token: "refresh-2", expires_in: 900 });
      }
      const auth = new Headers(init?.headers).get("Authorization");
      return auth === "Bearer fresh" ? json(200, { url }) : json(401, { title: "Unauthorized", status: 401 });
    });

    const results = await Promise.all([api("/a"), api("/b"), api("/c")]);

    expect(results).toHaveLength(3);
    expect(refreshes).toBe(1); // single-use refresh tokens must not be refreshed twice
    expect(sessionStorage.getItem("finance.refresh")).toBe("refresh-2");
  });

  it("ends the session when refresh fails", async () => {
    storeTokens({ access_token: "expired", refresh_token: "revoked", expires_in: 900 });
    const ended = vi.fn();
    setSessionEndedHandler(ended);
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json(401, { title: "Unauthorized", status: 401 }));

    await expect(api("/me")).rejects.toBeInstanceOf(ApiError);
    expect(ended).toHaveBeenCalledOnce();
    expect(sessionStorage.getItem("finance.refresh")).toBeNull();
  });

  it("surfaces RFC 9457 problem details", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json(409, { title: "Conflict", status: 409, detail: "An account with this email already exists." }),
    );

    const error = (await api("/auth/register", { method: "POST", body: {}, auth: false }).catch((e: unknown) => e)) as ApiError;

    expect(error.status).toBe(409);
    expect(error.message).toBe("An account with this email already exists.");
  });

  it("returns undefined for 204 and drops empty query values", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));

    await expect(api("/x", { method: "DELETE", query: { a: "1", b: "", c: undefined }, auth: false })).resolves.toBeUndefined();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/x?a=1");
  });
});
