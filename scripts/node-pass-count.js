"use strict";

// Count declared test cases using the child processes' summaries. The final
// aggregate summary also counts successful file wrappers for empty files.
// Node's per-file counts already exclude suites, skipped tests and TODOs.
module.exports = async function* (events) {
  let passed = 0;
  for await (const { type, data } of events) {
    if (type === "test:summary" && data.file !== undefined) {
      passed += data.counts.passed;
    }
  }
  yield `${passed}\n`;
};
