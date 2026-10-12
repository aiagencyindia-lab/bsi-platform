import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "vitest";

// Query strings built by apiQuery(), which encodes them with URLSearchParams.
// An exempt name passes only where its file has each statement it needs
// exactly once, and outside those statements the name appears only as
// `${name}`: no other binding, parameter, assignment or use. apiQuery(sp)
// inline is the encoder itself. Ceiling: lines the comment filter drops are
// not read, and apiQuery is matched by name, not resolved to lib/format.
type Need = readonly [name: string, statement: RegExp];
const fromApiQuery = (name: string): Need => [
  name,
  new RegExp(String.raw`const ${name} = apiQuery\([^()]*\);`, "g"),
];
const QUERIES = new Map<string, Need[]>([
  ["q", [fromApiQuery("q")]],
  ["dq", [fromApiQuery("dq")]],
  ["wq", [fromApiQuery("wq")]],
  [
    "feedQuery",
    [
      [
        "feedQuery",
        /const feedQuery = `\$\{fq\}\$\{fq \? "&" : "\?"\}days=\$\{FEED_DAYS\}`;/g,
      ],
      fromApiQuery("fq"),
      ["FEED_DAYS", /const FEED_DAYS = \d+;/g],
    ],
  ],
]);
const SRC = join(__dirname, "..");
const SOURCES = readdirSync(SRC, { recursive: true, encoding: "utf8" }).filter(
  (f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f),
);
// api.ts's own `function api<T>(path` is a definition, not a call.
const CALL = /(?<!function )\b(?:api|publicApi)(?:<[^(`]*>)?\(\s*/g;
// The whole first argument is one literal, followed by "," or ")".
const LITERAL = /^(`[^`]*`|"[^"]*"|'[^']*')\s*[,)]/;
const PATH = /(?<!function )\b(?:api|publicApi)(?:<[^(`]*>)?\(\s*`([^`]*)`/g;

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

/** True when code has each needed statement once and, outside them, each
 * needed name only inside `${...}` on its own. */
const encoded = (code: string, needs: Need[]) => {
  let rest = code;
  for (const [, statement] of needs) {
    if ([...code.matchAll(statement)].length !== 1) return false;
    rest = rest.replace(statement, "");
  }
  return needs.every(([name]) =>
    [...rest.matchAll(new RegExp(String.raw`\b${name}\b`, "g"))].every(
      (m) =>
        rest.slice(m.index - 2, m.index) === "${" &&
        rest[m.index + name.length] === "}",
    ),
  );
};

test("every value in an API path goes through seg()", () => {
  const bad: string[] = [];
  let templates = 0;
  for (const f of SOURCES) {
    const code = readFileSync(join(SRC, f), "utf8")
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
        if (isSeg(expr) || expr === "apiQuery(sp)") continue;
        const needs = QUERIES.get(expr);
        if (!needs) bad.push(`${f}: \${${expr}}`);
        else if (!encoded(code, needs)) {
          bad.push(`${f}: ${expr} is not built only by apiQuery()`);
        }
      }
    }
  }
  expect(templates).toBeGreaterThanOrEqual(40);
  expect(bad).toEqual([]);
});

test("path values are read with formSeg()", () => {
  // String(form.get(...)) turns a missing field into "null", which seg()
  // passes; formSeg() refuses it. So no code under src/ reads an id or type
  // field with .get() at all (FormData, URLSearchParams, Headers or Map
  // alike), whatever the receiver ((await req.formData()).get,
  // this.form.get), the quote style (template literals too) or a trailing
  // `!` or `as string`; nor String(<x>.get(<variable>)). The leading \b on
  // String and seg is a precaution: it keeps a future toString(...) line
  // from matching.
  const ID = String.raw`(?:"[a-z_]*_id"|'[a-z_]*_id'|\x60[a-z_]*_id\x60|"type"|'type'|\x60type\x60)`;
  const RAW = new RegExp(
    String.raw`\.get\(\s*${ID}\s*\)|\bString\([^\n]*?\.get\(\w+\)!?\)|\bseg\(String\(`,
    "g",
  );
  const bad = SOURCES.flatMap((f) =>
    [...readFileSync(join(SRC, f), "utf8").matchAll(RAW)].map(
      (m) => `${f}: ${m[0]}`,
    ),
  );
  expect(bad).toEqual([]);
});
