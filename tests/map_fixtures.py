import json
import struct

CATCH_MAP_ERRORS = """
(() => {
window.__mapErrors = [];
let lib;
Object.defineProperty(window, "maplibregl", {
  configurable: true,
  get() { return lib; },
  set(value) {
    lib = value;
    const proto = value.Map.prototype;
    const fire = proto.fire;
    proto.fire = function (event, ...rest) {
      const type = typeof event === "string" ? event : event && event.type;
      if (type === "error") {
        const err = event && event.error;
        const message = String((err && err.message) || err || type);
        window.__mapErrors.push(message);
        console.error("MapLibre error: " + message);
      }
      return fire.call(this, event, ...rest);
    };
  },
});
})();
"""


def empty_pmtiles():
    metadata = json.dumps({"vector_layers": []}).encode()
    root = b"\x00"
    header_len = 127
    root_offset = header_len
    meta_offset = root_offset + len(root)
    data_offset = meta_offset + len(metadata)
    e7 = lambda v: int(round(v * 10_000_000))
    header = b"PMTiles" + bytes([3]) + struct.pack(
        "<QQQQQQQQQQQ", root_offset, len(root), meta_offset, len(metadata), data_offset, 0, data_offset, 0, 0, 0, 0,
    ) + bytes([1, 1, 1, 1, 0, 14]) + struct.pack(
        "<iiii", e7(4.23), e7(50.75), e7(4.49), e7(50.92),
    ) + bytes([12]) + struct.pack("<ii", e7(4.3517), e7(50.8503))
    assert len(header) == header_len
    return header + root + metadata
