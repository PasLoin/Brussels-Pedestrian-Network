const test = require("node:test");
const assert = require("node:assert/strict");
const f = require("../../filters.js");

function fakeMap(layers, { throwOnSet = false } = {}) {
  const calls = [];
  return {
    calls,
    getLayer: (id) => (layers.includes(id) ? { id } : undefined),
    setFilter: (id, filter) => {
      if (throwOnSet) throw new Error("invalid filter");
      calls.push(["setFilter", id, filter]);
    },
    setLayoutProperty: (id, prop, value) => calls.push(["setLayoutProperty", id, prop, value]),
  };
}

test("membershipFilter: nothing active hides everything", () => {
  assert.deepEqual(f.membershipFilter("type", new Set(), 3), ["==", ["get", "type"], "__none__"]);
});

test("membershipFilter: everything active removes the filter", () => {
  assert.equal(f.membershipFilter("sw", new Set(["a", "b"]), 2), null);
});

test("membershipFilter: a subset keeps only its values, on the given property", () => {
  assert.deepEqual(
    f.membershipFilter("sw", new Set(["yes", "partial"]), 5),
    ["in", ["get", "sw"], ["literal", ["yes", "partial"]]],
  );
});

test("setFilterIfLayer applies the filter when the layer exists", () => {
  const map = fakeMap(["kerb-issues"]);
  assert.equal(f.setFilterIfLayer(map, "kerb-issues", ["==", 1, 1]), true);
  assert.deepEqual(map.calls, [["setFilter", "kerb-issues", ["==", 1, 1]]]);
});

test("setFilterIfLayer does nothing when the layer is missing or the map is not ready", () => {
  const map = fakeMap([]);
  assert.equal(f.setFilterIfLayer(map, "kerb-issues", null), false);
  assert.deepEqual(map.calls, []);
  assert.equal(f.setFilterIfLayer(null, "kerb-issues", null), false);
});

test("setFilterIfLayer lets real errors through", () => {
  const map = fakeMap(["kerb-issues"], { throwOnSet: true });
  assert.throws(() => f.setFilterIfLayer(map, "kerb-issues", ["bad"]), /invalid filter/);
});

test("setVisibilityIfLayer toggles visibility only on existing layers", () => {
  const map = fakeMap(["a"]);
  assert.equal(f.setVisibilityIfLayer(map, "a", true), true);
  assert.equal(f.setVisibilityIfLayer(map, "a", false), true);
  assert.equal(f.setVisibilityIfLayer(map, "b", true), false);
  assert.deepEqual(map.calls, [
    ["setLayoutProperty", "a", "visibility", "visible"],
    ["setLayoutProperty", "a", "visibility", "none"],
  ]);
});

test("updater reads the live set and the current map at each call", () => {
  let map = null;
  const items = [{ value: "x" }, { value: "y" }, { value: "z" }];
  const active = new Set(["x"]);
  const update = f.makeMembershipFilterUpdater(() => map, "islands", "type", active, items);
  assert.equal(update(), false);
  map = fakeMap(["islands"]);
  update();
  active.add("y");
  update();
  active.add("z");
  update();
  active.clear();
  update();
  assert.deepEqual(map.calls.map(c => c[2]), [
    ["in", ["get", "type"], ["literal", ["x"]]],
    ["in", ["get", "type"], ["literal", ["x", "y"]]],
    null,
    ["==", ["get", "type"], "__none__"],
  ]);
});
