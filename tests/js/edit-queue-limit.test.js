const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const load = name => import(pathToFileURL(path.join(__dirname, "..", "..", "edit", name)).href);
const API = "https://dev.example";

function controlledFetch() {
  const calls = [];
  let running = 0;
  let peak = 0;
  const impl = (url, init = {}) => new Promise((resolve, reject) => {
    running += 1;
    peak = Math.max(peak, running);
    calls.push({
      url,
      ok: (body = "ok", status = 200) => { running -= 1; resolve(new Response(status === 204 ? null : body, { status })); },
      fail: err => { running -= 1; reject(err); },
      init,
    });
  });
  return { impl, calls, peak: () => peak };
}

const tick = () => new Promise(r => setTimeout(r, 0));

test("never more than two API calls at once, in the order they were asked", async () => {
  const { limitConcurrency } = await load("api-queue.js");
  const server = controlledFetch();
  const waits = [];
  const f = limitConcurrency(server.impl, { max: 2, matches: u => u.startsWith(API), onWaiting: n => waits.push(n) });
  const results = [1, 2, 3, 4, 5].map(i => f(`${API}/api/0.6/way/${i}.json`).then(r => r.text()));
  await tick();
  assert.equal(server.calls.length, 2);
  assert.equal(Math.max(...waits), 3);
  server.calls[0].ok("a");
  await tick(); await tick();
  assert.equal(server.calls.length, 3);
  assert.match(server.calls[2].url, /way\/3/);
  for (let i = 1; i < 5; i++) {
    while (server.calls.length <= i) await tick();
    server.calls[i].ok(String(i));
  }
  assert.deepEqual(await Promise.all(results), ["a", "1", "2", "3", "4"]);
  assert.equal(server.peak(), 2);
  assert.equal(waits.at(-1), 0);
});

test("other hosts are never held back", async () => {
  const { limitConcurrency } = await load("api-queue.js");
  const server = controlledFetch();
  const f = limitConcurrency(server.impl, { max: 2, matches: u => u.startsWith(API) });
  f(`${API}/a`); f(`${API}/b`); f("https://tiles.example/1.pbf"); f("https://tiles.example/2.pbf");
  await tick();
  assert.equal(server.calls.length, 4);
});

test("a call aborted while waiting never reaches the server, and a failure frees its place", async () => {
  const { limitConcurrency } = await load("api-queue.js");
  const server = controlledFetch();
  const f = limitConcurrency(server.impl, { max: 1, matches: () => true });
  const first = f(`${API}/1`);
  const controller = new AbortController();
  const second = f(`${API}/2`, { signal: controller.signal });
  const third = f(`${API}/3`);
  await tick();
  controller.abort();
  await assert.rejects(second, err => err.name === "AbortError");
  server.calls[0].fail(new TypeError("offline"));
  await assert.rejects(first, TypeError);
  await tick(); await tick();
  assert.equal(server.calls.length, 2);
  assert.match(server.calls[1].url, /\/3$/);
  server.calls[1].ok("", 204);
  assert.equal((await third).status, 204);
  await assert.rejects(f(`${API}/4`, { signal: AbortSignal.abort() }), err => err.name === "AbortError");
});

test("the body is read before the place is freed, so a slow download counts as busy", async () => {
  const { limitConcurrency } = await load("api-queue.js");
  let released = false;
  const slowBody = new ReadableStream({ start(c) { setTimeout(() => { c.enqueue(new TextEncoder().encode("big")); c.close(); released = true; }, 20); } });
  let calls = 0;
  const f = limitConcurrency(async () => { calls += 1; return calls === 1 ? new Response(slowBody, { status: 200, headers: { "Content-Type": "application/json" } }) : new Response("x"); }, { max: 1 });
  const a = f(`${API}/map`);
  const b = f(`${API}/way`);
  await tick();
  assert.equal(calls, 1);
  const response = await a;
  assert.equal(released, true);
  assert.equal(response.headers.get("Content-Type"), "application/json");
  assert.equal(await response.text(), "big");
  assert.equal(await (await b).text(), "x");
});
