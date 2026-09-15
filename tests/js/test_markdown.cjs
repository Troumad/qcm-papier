const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const context = { window: {} };
const script = path.join(__dirname, "../../qcm_papier/web/static/markdown.js");
vm.runInNewContext(fs.readFileSync(script, "utf8"), context);
const render = context.window.QCMMarkdown.render;

test("l'aide affiche titres, listes et commandes sans interpréter le code", () => {
  const html = render("# Guide\n\n- Installer\n- Lancer\n\n```sh\npip install <paquet>\n```");
  assert.match(html, /<h1>Guide<\/h1>/);
  assert.match(html, /<ul><li>Installer<\/li><li>Lancer<\/li><\/ul>/);
  assert.match(html, /<pre><code>pip install &lt;paquet&gt;<\/code><\/pre>/);
});

test("l'aide échappe le HTML et refuse les liens exécutables", () => {
  const html = render('<img src=x onerror="alert(1)"> [piège](javascript:alert)');
  assert.ok(!html.includes("<img"));
  assert.ok(!html.includes("<a"));
  assert.match(html, /&lt;img/);
});

test("le code en ligne reste littéral et les liens HTTPS sont lisibles", () => {
  const html = render('`**littéral**` et **gras** [Tauri](https://v2.tauri.app/)');
  assert.match(html, /<code>\*\*littéral\*\*<\/code>/);
  assert.match(html, /<strong>gras<\/strong>/);
  assert.match(html, /href="https:\/\/v2.tauri.app\/"/);
});
