const assert = require("node:assert/strict");
const test = require("node:test");
const review = require("../../qcm_papier/web/static/review.js");
const good = { index: 0, failed: false, complete: true, identified: true, student_id: "p1", note: 2 };
const rows = [good, { ...good, index: 1, identified: false, student_id: "p2" },
  { ...good, index: 2, complete: false, note: -1 },
  { ...good, index: 3, student_id: null, identified: false, failed: true, note: null }];
test("les filtres distinguent échec, identité et copie incomplète", () => {
  assert.deepEqual(rows.filter((r) => review.matches(r, "review", rows)).map((r) => r.index), [0, 1, 2, 3]);
  assert.deepEqual(rows.filter((r) => review.matches(r, "unknown")).map((r) => r.index), [1, 3]);
  assert.deepEqual(rows.filter((r) => review.matches(r, "incomplete")).map((r) => r.index), [2]);
});
test("la prochaine anomalie boucle et gère une liste sans anomalie", () => {
  assert.equal(review.nextIssue(rows, 1), 2);
  assert.equal(review.nextIssue(rows, 3), 0);
  assert.equal(review.nextIssue([good], 0), null);
  assert.equal(review.nextIssue([], -1), null);
});
test("le récapitulatif compte les doublons séparément des pages", () => {
  assert.deepEqual(review.summary(rows), { pages: 4, review: 4, unknown: 2, incomplete: 1,
    failed: 1, negative: 1, duplicates: 1 });
});
