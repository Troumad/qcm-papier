const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const vm = require("node:vm");

function harness(response) {
  const source = fs.readFileSync("qcm_papier/web/static/app.js", "utf8");
  const context = vm.createContext({ window: {}, FormData, fetch: async () => response });
  vm.runInContext(source.slice(0, source.indexOf("let toastTimer;")), context);
  return vm.runInContext("api", context);
}
test("le téléchargement JSON conserve les octets et les en-têtes de sauvegarde", async () => {
  const content = '{"structure":[{"name":"Sujet corrigé"}]}';
  const response = new Response(content, { headers: {
    "Content-Type": "application/json", "X-Project-Token": "version-corrigee",
  } });
  const api = harness(response);
  const download = await api("GET", "/api/project/download", undefined, { raw: true });
  assert.equal(download.headers.get("X-Project-Token"), "version-corrigee");
  assert.equal(await (await download.blob()).text(), content);
});
test("les appels ordinaires continuent à décoder les objets JSON", async () => {
  const api = harness(Response.json({ name: "Sujet corrigé" }));
  assert.deepEqual(await api("GET", "/api/project"), { name: "Sujet corrigé" });
});
