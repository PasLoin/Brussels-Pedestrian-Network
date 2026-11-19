const path = require("node:path");
const { pathToFileURL } = require("node:url");

const EDIT = path.join(__dirname, "..", "..", "edit");

const loadEdit = name => import(pathToFileURL(path.join(EDIT, name)).href);

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: key => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, String(value)),
    removeItem: key => data.delete(key),
    dump: () => Object.fromEntries(data),
  };
}

module.exports = { EDIT, loadEdit, memoryStorage };
