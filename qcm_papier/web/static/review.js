"use strict";
// Fonctions pures partagées par la liste, la navigation et le récapitulatif d'export.
(function (root) {
  function unknown(row) { return !row.student_id || !row.identified; }
  function needsReview(row, rows = []) {
    const duplicate = row.student_id && rows.filter((other) => other.student_id === row.student_id).length > 1;
    return Boolean(row.failed || !row.complete || unknown(row) || duplicate);
  }
  function matches(row, filter, rows = []) {
    if (filter === "review") return needsReview(row, rows);
    if (filter === "unknown") return unknown(row);
    if (filter === "incomplete") return !row.complete;
    return true;
  }
  function nextIssue(rows, current) {
    const issues = rows.filter((row) => needsReview(row, rows));
    return issues.find((row) => row.index > current)?.index ?? issues[0]?.index ?? null;
  }
  function summary(rows) {
    const counts = new Map();
    for (const row of rows) {
      if (row.student_id) counts.set(row.student_id, (counts.get(row.student_id) || 0) + 1);
    }
    return {
      pages: rows.length,
      review: rows.filter((row) => needsReview(row, rows)).length,
      unknown: rows.filter(unknown).length,
      incomplete: rows.filter((row) => !row.complete).length,
      failed: rows.filter((row) => row.failed).length,
      negative: rows.filter((row) => row.note !== null && row.note < 0).length,
      duplicates: [...counts.values()].filter((count) => count > 1).length,
    };
  }
  const api = { unknown, needsReview, matches, nextIssue, summary };
  if (typeof module !== "undefined") module.exports = api;
  else root.QCMReview = api;
})(typeof window !== "undefined" ? window : globalThis);
