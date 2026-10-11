import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "vitest";

// Query strings built by URLSearchParams, which encodes them already.
const QUERIES = new Set(["q", "dq", "wq", "feedQuery", "apiQuery(sp)"]);
const APP = join(__dirname, "..", "app");
const CALL = /\b(?:api|publicApi)(?:<[^(`]*>)?\(\s*/g;
// The whole first argument is one literal, followed by "," or ")".
const LITERAL = /^(`[^`]*`|"[^"]*"|'[^']*')\s*[,)]/;
const PATH = /\b(?:api|publicApi)(?:<[^(`]*>)?\(\s*`([^`]*)`/g;

/** True for exactly one seg(...) call: its "(" closes at the last character. */
const isSeg = (expr: string) => {
  if (!expr.startsWith("seg(")) return false;
  let depth = 0;
  for (let i = 3; i < expr.length; i++) {
    if (expr[i] === "(") depth += 1;
    if (expr[i] === ")") depth -= 1;
    if (depth === 0) return i === expr.length - 1;
  }
  return false;
};

test("every value in an API path goes through seg()", () => {
  const files = readdirSync(APP, { recursive: true, encoding: "utf8" }).filter(
    (f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f),
  );
  const bad: string[] = [];
  let templates = 0;
  for (const f of files) {
    const code = readFileSync(join(APP, f), "utf8")
      .split("\n")
      .filter((line) => !/^\s*(\/\/|\/\*|\*)/.test(line))
      .join("\n");
    for (const m of code.matchAll(CALL)) {
      if (!LITERAL.test(code.slice(m.index + m[0].length))) {
        bad.push(`${f}: path is not one literal`);
      }
    }
    for (const [, path] of code.matchAll(PATH)) {
      templates += 1;
      for (const [, expr] of path.matchAll(/\$\{([^}]*)\}/g)) {
        if (!isSeg(expr) && !QUERIES.has(expr)) bad.push(`${f}: \${${expr}}`);
      }
    }
  }
  expect(templates).toBeGreaterThanOrEqual(40);
  expect(bad).toEqual([]);
});

test("server actions read path values with formSeg()", () => {
  // String(form.get(...)) turns a missing field into "null", which seg()
  // passes; formSeg() refuses it. A field named by a variable
  // (String(form.get(k))) is caught too: label's actions read ids that way.
  const RAW =
    /String\(form\.get\("(?:[a-z_]*_id|type)"\)\)|String\(form\.get\(\w+\)\)|seg\(String\(/g;
  const files = readdirSync(APP, { recursive: true, encoding: "utf8" }).filter(
    (f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f),
  );
  const bad = files.flatMap((f) =>
    [...readFileSync(join(APP, f), "utf8").matchAll(RAW)].map(
      (m) => `${f}: ${m[0]}`,
    ),
  );
  expect(bad).toEqual([]);
});
