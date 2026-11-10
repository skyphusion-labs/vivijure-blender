// The blender door Worker's bearer gate and /ready body.
//
// The gate is vendored from vivijure-cf (see the header of src/gate.ts). The first block pins
// the vendored bytes; the rest drive the real default export, with the container stubbed, so
// they test the wiring and not only the helper.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";

const reached: Request[] = [];
vi.mock("@cloudflare/containers", () => ({
  Container: class {},
  getContainer: () => ({
    fetch: async (request: Request) => {
      reached.push(request);
      return new Response("from-container", { status: 200 });
    },
  }),
}));

import worker from "../src/index";
import { bearerOk, readyBody } from "../src/gate";

const SRC = join(__dirname, "..", "src");
const TOKEN = "door-token-not-a-real-value";
const env = { LOCAL_FINISH_TOKEN: TOKEN, BLENDER: {} } as never;
const call = (path: string, init?: RequestInit, e: unknown = env) =>
  worker.fetch(new Request("https://blender.example" + path, init), e as never);
const post = (authorization?: string) =>
  call("/grade", { method: "POST", headers: authorization === undefined ? {} : { authorization } });

// sha256 of vivijure-cf containers/image-prep/cf-container/src/gate.ts at e6e25cb.
const UPSTREAM_GATE_SHA256 = "752fa2b9f300850a8fe0a8bb89e12712bce19ad16ee4057474f63e0b626853e7";
const HEADER_END = "re-vendor.\n//\n";

describe("the vendored gate", () => {
  it("is byte-for-byte the vivijure-cf door gate below its header", () => {
    const src = readFileSync(join(SRC, "gate.ts"), "utf8");
    const at = src.indexOf(HEADER_END);
    expect(at).toBeGreaterThan(0);
    const body = src.slice(at + HEADER_END.length);
    expect(createHash("sha256").update(body).digest("hex")).toBe(UPSTREAM_GATE_SHA256);
  });

  it("is what index.ts gates with, and the old inline check is gone", () => {
    const src = readFileSync(join(SRC, "index.ts"), "utf8");
    expect(src).toMatch(/import \{ bearerOk, readyBody \} from "\.\/gate";/);
    expect(src).toMatch(/await bearerOk\(request\.headers\.get\("authorization"\), env\.LOCAL_FINISH_TOKEN\)/);
    expect(src).toMatch(/Response\.json\(readyBody\(env\.LOCAL_FINISH_TOKEN\)\)/);
    expect(src).not.toMatch(/token_len|expected !== got|function bearer\(/);
  });
});

describe("the door Worker", () => {
  it("is 401 on a wrong token, of the same length and of another length", async () => {
    const same = TOKEN.slice(0, -1) + (TOKEN.endsWith("e") ? "f" : "e");
    expect(same.length).toBe(TOKEN.length);
    reached.length = 0;
    expect((await post("Bearer " + same)).status).toBe(401);
    expect((await post("Bearer " + TOKEN + "x")).status).toBe(401);
    expect((await post("Bearer wrong")).status).toBe(401);
    expect(reached).toHaveLength(0);
  });

  it("is 401 with no token, another scheme, or an empty bearer", async () => {
    reached.length = 0;
    expect((await post()).status).toBe(401);
    expect((await post(TOKEN)).status).toBe(401);
    expect((await post("Basic " + TOKEN)).status).toBe(401);
    expect((await post("Bearer ")).status).toBe(401);
    expect(reached).toHaveLength(0);
  });

  it("is 401 for every request when no token is configured", async () => {
    reached.length = 0;
    for (const unset of [{ BLENDER: {} }, { LOCAL_FINISH_TOKEN: "", BLENDER: {} }]) {
      expect((await call("/grade", { method: "POST", headers: { authorization: "Bearer " } }, unset)).status).toBe(401);
      expect((await call("/grade", { method: "POST", headers: { authorization: "Bearer x" } }, unset)).status).toBe(401);
    }
    expect(reached).toHaveLength(0);
  });

  it("forwards to the container on the right token, with the scheme in any case", async () => {
    reached.length = 0;
    const ok = await post("Bearer " + TOKEN);
    expect(ok.status).toBe(200);
    expect(await ok.text()).toBe("from-container");
    expect((await post("bearer " + TOKEN)).status).toBe(200);
    expect(reached).toHaveLength(2);
  });

  it("leaves GET /health open", async () => {
    reached.length = 0;
    expect((await call("/health")).status).toBe(200);
    expect(reached).toHaveLength(1);
  });

  it("GET /ready says only whether a token is configured", async () => {
    const body = (await (await call("/ready")).json()) as Record<string, unknown>;
    expect(body).toEqual({ ok: true, token_configured: true });
    expect(Object.keys(body).sort()).toEqual(["ok", "token_configured"]);
    expect(JSON.stringify(body)).not.toContain(String(TOKEN.length));
    const unset = (await (await call("/ready", undefined, { BLENDER: {} })).json()) as Record<string, unknown>;
    expect(unset).toEqual({ ok: true, token_configured: false });
    expect(readyBody("")).toEqual({ ok: true, token_configured: false });
  });

  it("bearerOk accepts exactly the configured token", async () => {
    expect(await bearerOk("Bearer " + TOKEN, TOKEN)).toBe(true);
    expect(await bearerOk("Bearer " + TOKEN, undefined)).toBe(false);
    expect(await bearerOk(null, TOKEN)).toBe(false);
  });
});
