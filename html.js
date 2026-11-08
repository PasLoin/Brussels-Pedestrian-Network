(function (global) {
  class SafeHTML {
    constructor(markup) {
      this.markup = markup;
    }

    toString() {
      return this.markup;
    }
  }

  function escapeHTML(str) {
    if (!str) return str;
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function fragment(value) {
    if (value === null || value === undefined || value === false || value === "") return "";
    if (value instanceof SafeHTML) return value.markup;
    if (Array.isArray(value)) return value.map(fragment).join("");
    return escapeHTML(String(value));
  }

  function html(strings, ...values) {
    let markup = strings[0];
    for (let i = 0; i < values.length; i++) markup += fragment(values[i]) + strings[i + 1];
    return new SafeHTML(markup);
  }

  const api = { SafeHTML, escapeHTML, html };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else Object.assign(global, api);
})(typeof window !== "undefined" ? window : globalThis);
