// One-off migration tool. Parses the legacy i18n.js dictionaries into a
// plain JSON dump for the other migration scripts to consume. Not part of
// the runtime or CI - delete this whole scripts/i18n_migrate/ directory
// once the migration is merged.
import fs from "node:fs";

global.window = global;
global.localStorage = { _store: {}, getItem() { return null; }, setItem() {} };
global.document = {
  documentElement: { lang: "", classList: { remove() {} } },
  body: {},
  cookie: "",
  addEventListener() {},
  querySelectorAll() { return []; },
};
global.Node = { TEXT_NODE: 3, ELEMENT_NODE: 1 };
global.Element = function () {};
global.MutationObserver = function () { this.observe = function () {}; };

let src = fs.readFileSync(new URL("../../app/tbc/static/i18n.js", import.meta.url), "utf8");
src = src.replace(
  "const initialize = () => {",
  "globalThis.__dump = { english, spanish, keyedMessages, englishPatterns: englishPatterns.map(([re, r]) => [re.source, r]), spanishPatterns: spanishPatterns.map(([re, r]) => [re.source, r]) }; const initialize = () => {"
);
src = src.replace(/\n\s*initialize\(\);?\s*\n?\s*\}\)\(\);?\s*$/, "\n})();");
eval(src);

fs.writeFileSync(
  new URL("./dicts.json", import.meta.url),
  JSON.stringify(globalThis.__dump, null, 2)
);
console.log("english:", Object.keys(globalThis.__dump.english).length);
console.log("spanish:", Object.keys(globalThis.__dump.spanish).length);
console.log("keyedMessages:", Object.keys(globalThis.__dump.keyedMessages).length);
console.log("englishPatterns:", globalThis.__dump.englishPatterns.length);
console.log("spanishPatterns:", globalThis.__dump.spanishPatterns.length);
