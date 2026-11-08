const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

function loadESLint() {
  try {
    return require("eslint").ESLint;
  } catch {
    return null;
  }
}

const ESLint = loadESLint();

const ROOT = path.join(__dirname, "..", "..");
const lint = ESLint && new ESLint({ cwd: ROOT });

async function rules(code, file = "app.js") {
  const [result] = await lint.lintText(code, { filePath: path.join(ROOT, file) });
  return result.messages.map(m => m.ruleId);
}

const options = { skip: ESLint ? false : "eslint is not installed: run npm ci" };

test("markup must go through the html tag", options, async () => {
  for (const code of [
    'document.body.innerHTML = "<b>x</b>";',
    "document.body.innerHTML = `<b>${location.hash}</b>`;",
    "document.body.innerHTML += location.hash;",
    "document.body.outerHTML = location.hash;",
    'document.body.insertAdjacentHTML("beforeend", location.hash);',
    'document.write("x");',
  ]) {
    assert.deepEqual(await rules(code), ["no-restricted-syntax"], code);
  }
});

test("the html tag and empty strings are accepted", options, async () => {
  for (const code of [
    "document.body.innerHTML = html`<b>${location.hash}</b>`;",
    "document.body.innerHTML += html`<b>${location.hash}</b>`;",
    'document.body.innerHTML = "";',
    'document.body.insertAdjacentHTML("beforeend", html`<i>${location.hash}</i>`);',
  ]) {
    assert.deepEqual(await rules(code), [], code);
  }
});

test("scripts see the globals of the scripts loaded before them", options, async () => {
  assert.deepEqual(await rules("buildRoute(); makePopupLayers(); setFilterIfLayer(); I18N.fromDocument();"), []);
  assert.deepEqual(await rules("Chart.defaults.color = '#000';", "stats.js"), []);
  assert.deepEqual(await rules("Chart.defaults.color = '#000';", "app.js"), ["no-undef"]);
  assert.deepEqual(await rules("notDefinedAnywhere();"), ["no-undef"]);
});
