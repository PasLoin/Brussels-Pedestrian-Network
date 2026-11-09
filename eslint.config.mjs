import { readFileSync } from "node:fs";
import js from "@eslint/js";
import globals from "globals";

const readonly = names => Object.fromEntries(names.map(name => [name, "readonly"]));

const topLevelFunctions = file =>
  [...readFileSync(new URL(file, import.meta.url), "utf8").matchAll(/^function (\w+)\(/gm)].map(m => m[1]);

const PAGE_RUNTIME = readonly(["I18N", "BPNLang", "html", "escapeHTML", "SafeHTML"]);
const MAP_SCRIPTS = readonly([
  "maplibregl",
  "pmtiles",
  ...topLevelFunctions("./nav.js"),
  ...topLevelFunctions("./filters.js"),
  ...topLevelFunctions("./popups.js"),
]);
const CHART_SCRIPTS = readonly(["Chart"]);

const SAFE_HTML_ONLY = "Build markup with the html`` tag from html.js so every value is escaped.";
const UNSAFE_HTML = [
  {
    selector: "AssignmentExpression[left.property.name=/^(innerHTML|outerHTML)$/]:not([right.type='TaggedTemplateExpression'][right.tag.name='html']):not([right.type='Literal'][right.value=''])",
    message: SAFE_HTML_ONLY,
  },
  {
    selector: "CallExpression[callee.property.name='insertAdjacentHTML']:not([arguments.1.type='TaggedTemplateExpression'][arguments.1.tag.name='html'])",
    message: SAFE_HTML_ONLY,
  },
  {
    selector: "CallExpression[callee.object.name='document'][callee.property.name=/^(write|writeln)$/]",
    message: "document.write is not allowed.",
  },
];

export default [
  { ignores: ["_site/**", "node_modules/**", "coverage/**"] },
  js.configs.recommended,
  {
    files: ["*.js"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "script",
      globals: { ...globals.browser, ...PAGE_RUNTIME, module: "readonly", require: "readonly" },
    },
  },
  {
    files: ["map/**/*.js"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "module",
      globals: { ...globals.browser, ...PAGE_RUNTIME, ...MAP_SCRIPTS },
    },
  },
  {
    files: ["*.js", "map/**/*.js"],
    rules: {
      "no-restricted-syntax": ["error", ...UNSAFE_HTML],
      "no-empty": ["error", { allowEmptyCatch: true }],
      "eqeqeq": ["error", "smart"],
      "no-var": "error",
      "prefer-const": "error",
    },
  },
  { files: ["stats.js", "evolution.js"], languageOptions: { globals: CHART_SCRIPTS } },
  {
    files: ["tests/js/**/*.js"],
    languageOptions: { ecmaVersion: 2023, sourceType: "commonjs", globals: globals.node },
  },
  {
    files: ["eslint.config.mjs"],
    languageOptions: { ecmaVersion: 2023, sourceType: "module", globals: globals.node },
  },
];
