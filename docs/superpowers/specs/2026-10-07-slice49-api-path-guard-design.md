# Slice 49 design: values in API paths go through seg(), and api() refuses a path fetch would not send as written

## Context

Codebase facts: main `c45a729`, checked 2026-10-07.

The slice 48 final review deferred a minor: a server action puts `brand_id` from a hidden form field straight into the API path (findings-slice48 §3, R6). The same holds for every value the web app interpolates into an API path: 55 `api()`/`publicApi()` path templates in 28 files under `apps/web/src/app`. Server actions read `brand_id`, `task_id`, the report `type`, `run_id`, `rec_id`, `observation_id` and `entity_id` from form fields; Server Component pages use route params (`id`, `pid`, `oid`, `token`) and values from API answers (`o.brand_id`). `apps/web/src/lib/api.ts` builds `${API_URL}/v1${path}` and calls `fetch`; `publicApi()` does the same with no key.

Two ways a value can send a request to a different route:
- `fetch` normalizes the URL: a `.` or `..` segment (also spelled `%2e`, and with `\` read as `/`) is collapsed, so `..` reaches a different `/v1` route and `../..` can leave `/v1` (`/v1/brands/../../x` becomes `/x`).
- A `/` inside a value adds segments, and `%2F` does too, since uvicorn decodes the path before routing; for example `brand_id = "<B>/tasks/<T>"` in the reports branding action sends `PATCH /v1/brands/<B>/tasks/<T>`. Next passes route params to the page still percent-encoded, so `/b/..%2F..%2Fops` reaches a page with `id = "..%2F..%2Fops"`.

`encodeURIComponent` alone would not stop either: it leaves `.` unescaped, and `%2F` is decoded by the API server.

Who can set these values: form fields only through the signed-in operator's own post (Next checks the Origin of server actions); route params through any link the operator opens, which makes GET requests with the operator's own key. Either way the request carries the operator's key and the call site's method, so the change keeps requests on the intended route; it is not a privilege fix.

The two Route Handlers already validate their parameter before `fetch` (`products/export.csv`: a UUID regex; `r/[token]/pdf`: a token regex), and share tokens come from `secrets.token_urlsafe` (`A-Z a-z 0-9 _ -`). Report types are `cmo`, `seo`, `content`, `pr`, `agency`.

Classification: **bounded** (one shared helper and its call sites, no API change), said as the first line of the first brainstorming reply with the session model (Opus 5.5). The user's process asks for a spec and plan even for small changes, so the full process is followed.

Decisions approved in chat (2026-10-07), each after approaches with trade-offs and a recommendation written in a chat message:
1. One guard in `api()` and `publicApi()`; over validating each id at every action and page, or `encodeURIComponent` at each site.
2. On refusal, `notFound()` with a log line; over throwing an error.
3. After the spec review of `6a55903` showed a `/` or `%2F` inside a value passes that guard (the fact behind decision 1), re-asked: the guard plus `seg()` on every interpolated value; over the guard only with the gaps stated, or closing the minor as won't-fix.
4. After the spec review of `c2253d5`: both test hardenings, a stricter scan (a non-literal path argument fails; each `${…}` must be exactly one `seg(…)` call) and a guard refusal case with a query (`/brands/x?a=b'c`).

Design Sections 1 and 2 were shown in chat and approved, then revised for decision 3 and shown and approved again.

## Design

**`seg(value)`** (exported from `apps/web/src/lib/api.ts`) returns `value` when it is one or more letters, digits, `-` or `_`; otherwise it logs `console.error("API path value refused", value)` and calls `notFound()`. Every value interpolated into an `api()`/`publicApi()` path goes through it: route params, form fields, values from API answers, and values inside a hand-written query string (`prompt_id=${seg(pid)}`). Query strings built by `URLSearchParams` (`q`, `dq`, `wq`, `apiQuery(sp)`, and `feedQuery`, which is `apiQuery` output plus `days=` and the constant `FEED_DAYS`, joined with `&` or `?`) are left as they are; their output uses only characters the URL parser keeps. The public report page uses `seg(token)` in place of `encodeURIComponent(token)`. In recommendations, `rec()` returns the `rec_id` and both calls write the path with `seg()` on each value.

**`sendAsWritten(path)`**, the backstop, parses `path` against a dummy base and requires the parsed path plus query to equal `path`; otherwise it logs `console.error("API path refused", path)` and calls `notFound()`. `api()` calls it first, before reading the cookie (no test pins that order); `publicApi()` calls it first. It refuses `.`/`..` segments in any spelling, `\`, `#`, anything the parser re-encodes (a space, a non-ASCII letter, `'` in a query), and a bare trailing `?`.

Together they refuse `/`, `%2F`, `?`, `#`, `.`, `..` and spaces inside any interpolated value. A refusal shows the app's not-found page and logs the value or path; `fetch` is not called. In a server action this relies on Next handling `notFound()` there, which `api()` already relies on for an API 404; no test covers it.

Unchanged: the API, the Route Handlers, and `redirect()` targets (paths inside the web app, not API calls).

As a diff against main `c45a729` (generated from the proof below):

```diff
diff --git a/apps/web/src/app/(app)/b/[id]/alerts/actions.ts b/apps/web/src/app/(app)/b/[id]/alerts/actions.ts
--- a/apps/web/src/app/(app)/b/[id]/alerts/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/alerts/actions.ts
@@ -1,7 +1,7 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 
 export async function setWebhook(form: FormData) {
   const id = String(form.get("brand_id"));
@@ -14,7 +14,7 @@ export async function setWebhook(form: FormData) {
   const body: Record<string, string | null> = { webhook_url: clear ? null : value };
   if (clearSecret) body.webhook_secret = null;
   else if (secret !== "") body.webhook_secret = secret;
-  await api(`/brands/${id}`, {
+  await api(`/brands/${seg(id)}`, {
     method: "PATCH",
     headers: { "Content-Type": "application/json" },
     body: JSON.stringify(body),
@@ -25,7 +25,7 @@ export async function setWebhook(form: FormData) {
 
 export async function scanNow(form: FormData) {
   const id = String(form.get("brand_id"));
-  const r = await api<{ created: number }>(`/brands/${id}/alerts/scan`, {
+  const r = await api<{ created: number }>(`/brands/${seg(id)}/alerts/scan`, {
     method: "POST",
   });
   redirect(`/b/${id}/alerts?queued=${r.created > 0 ? "new" : "none"}`);
diff --git a/apps/web/src/app/(app)/b/[id]/alerts/page.tsx b/apps/web/src/app/(app)/b/[id]/alerts/page.tsx
--- a/apps/web/src/app/(app)/b/[id]/alerts/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/alerts/page.tsx
@@ -1,5 +1,5 @@
 import Link from "next/link";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import { ALERT_KIND, alertNote, lastDay, type Params } from "@/lib/format";
 import type { Alert, Brand } from "@/lib/types";
 import { scanNow, setWebhook } from "./actions";
@@ -27,8 +27,8 @@ export default async function Alerts({
   const { id } = await params;
   const sp = await searchParams;
   const [brand, alerts] = await Promise.all([
-    api<Brand>(`/brands/${id}`),
-    api<Alert[]>(`/brands/${id}/alerts`),
+    api<Brand>(`/brands/${seg(id)}`),
+    api<Alert[]>(`/brands/${seg(id)}/alerts`),
   ]);
   const msg = alertNote(sp.queued);
   return (
diff --git a/apps/web/src/app/(app)/b/[id]/citations/page.tsx b/apps/web/src/app/(app)/b/[id]/citations/page.tsx
--- a/apps/web/src/app/(app)/b/[id]/citations/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/citations/page.tsx
@@ -1,6 +1,6 @@
 import Link from "next/link";
 import { Filters } from "@/components/Filters";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import { apiQuery, type Params } from "@/lib/format";
 import type { Source } from "@/lib/types";
 
@@ -20,7 +20,7 @@ export default async function Citations({
 }) {
   const { id } = await params;
   const sp = await searchParams;
-  let rows = await api<Source[]>(`/brands/${id}/citations${apiQuery(sp)}`);
+  let rows = await api<Source[]>(`/brands/${seg(id)}/citations${apiQuery(sp)}`);
   const gapOnly = sp.gap === "1";
   if (gapOnly) rows = rows.filter((r) => r.gap);
   const sort =
diff --git a/apps/web/src/app/(app)/b/[id]/clusters/actions.ts b/apps/web/src/app/(app)/b/[id]/clusters/actions.ts
--- a/apps/web/src/app/(app)/b/[id]/clusters/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/clusters/actions.ts
@@ -1,12 +1,12 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import type { Queued } from "@/lib/types";
 
 export async function labelPrompts(form: FormData) {
   const id = String(form.get("brand_id"));
-  const job = await api<Queued>(`/brands/${id}/prompts/label`, {
+  const job = await api<Queued>(`/brands/${seg(id)}/prompts/label`, {
     method: "POST",
   });
   // The API returns this hour's job, which may already be done.
@@ -15,7 +15,7 @@ export async function labelPrompts(form: FormData) {
 
 export async function optimizeUrl(form: FormData) {
   const id = String(form.get("brand_id"));
-  const job = await api<Queued>(`/brands/${id}/pages/optimize`, {
+  const job = await api<Queued>(`/brands/${seg(id)}/pages/optimize`, {
     method: "POST",
     headers: { "Content-Type": "application/json" },
     body: JSON.stringify({
diff --git a/apps/web/src/app/(app)/b/[id]/clusters/page.tsx b/apps/web/src/app/(app)/b/[id]/clusters/page.tsx
--- a/apps/web/src/app/(app)/b/[id]/clusters/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/clusters/page.tsx
@@ -1,6 +1,6 @@
 import Link from "next/link";
 import { Filters } from "@/components/Filters";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import {
   apiQuery,
   ciText,
@@ -25,7 +25,7 @@ export default async function ClustersPage({
   const { id } = await params;
   const sp = await searchParams;
   // The API sorts clusters and brief sources; the page keeps its order.
-  const data = await api<Clusters>(`/brands/${id}/clusters/gaps${apiQuery(sp)}`);
+  const data = await api<Clusters>(`/brands/${seg(id)}/clusters/gaps${apiQuery(sp)}`);
   return (
     <>
       <Filters sp={sp} />
diff --git a/apps/web/src/app/(app)/b/[id]/competitors/actions.ts b/apps/web/src/app/(app)/b/[id]/competitors/actions.ts
--- a/apps/web/src/app/(app)/b/[id]/competitors/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/competitors/actions.ts
@@ -1,12 +1,12 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import type { Queued } from "@/lib/types";
 
 export async function crawlRivals(form: FormData) {
   const id = String(form.get("brand_id"));
-  const job = await api<Queued>(`/brands/${id}/competitors/crawl`, {
+  const job = await api<Queued>(`/brands/${seg(id)}/competitors/crawl`, {
     method: "POST",
   });
   // The API returns this hour's job, which may already be done.
diff --git a/apps/web/src/app/(app)/b/[id]/competitors/page.tsx b/apps/web/src/app/(app)/b/[id]/competitors/page.tsx
--- a/apps/web/src/app/(app)/b/[id]/competitors/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/competitors/page.tsx
@@ -1,7 +1,7 @@
 import Link from "next/link";
 import { Filters } from "@/components/Filters";
 import { CiBar } from "@/components/Tile";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import {
   apiQuery,
   ciText,
@@ -46,10 +46,10 @@ export default async function Competitors({
   const fq = apiQuery(sp, [], ["date_from"]);
   const feedQuery = `${fq}${fq ? "&" : "?"}days=${FEED_DAYS}`;
   const [rows, d, feed, site] = await Promise.all([
-    api<EntityMetrics[]>(`/brands/${id}/competitors/metrics${q}`),
-    api<EntityDeltas>(`/brands/${id}/competitors/deltas${wq}`),
-    api<Changes>(`/brands/${id}/competitors/changes${feedQuery}`),
-    api<SiteChanges>(`/brands/${id}/competitors/site-changes${feedQuery}`),
+    api<EntityMetrics[]>(`/brands/${seg(id)}/competitors/metrics${q}`),
+    api<EntityDeltas>(`/brands/${seg(id)}/competitors/deltas${wq}`),
+    api<Changes>(`/brands/${seg(id)}/competitors/changes${feedQuery}`),
+    api<SiteChanges>(`/brands/${seg(id)}/competitors/site-changes${feedQuery}`),
   ]);
   const deltaText = (eid: string, key: "mention_rate" | "sov") => {
     const x = d.deltas?.[eid]?.[key];
diff --git a/apps/web/src/app/(app)/b/[id]/label/actions.ts b/apps/web/src/app/(app)/b/[id]/label/actions.ts
--- a/apps/web/src/app/(app)/b/[id]/label/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/label/actions.ts
@@ -1,13 +1,13 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import type { LabelResult } from "@/lib/types";
 
 export async function saveLabel(form: FormData) {
   const get = (k: string) => String(form.get(k));
   const r = await api<LabelResult>(
-    `/observations/${get("observation_id")}/labels/${get("entity_id")}`,
+    `/observations/${seg(get("observation_id"))}/labels/${seg(get("entity_id"))}`,
     {
       method: "PUT",
       headers: { "Content-Type": "application/json" },
diff --git a/apps/web/src/app/(app)/b/[id]/label/page.tsx b/apps/web/src/app/(app)/b/[id]/label/page.tsx
--- a/apps/web/src/app/(app)/b/[id]/label/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/label/page.tsx
@@ -1,4 +1,4 @@
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import { ciText, highlight, pct, type Params } from "@/lib/format";
 import type { LabelQueue } from "@/lib/types";
 import { saveLabel } from "./actions";
@@ -19,7 +19,7 @@ export default async function Label({
 }) {
   const { id } = await params;
   const sp = await searchParams;
-  const q = await api<LabelQueue>(`/brands/${id}/labels/next`);
+  const q = await api<LabelQueue>(`/brands/${seg(id)}/labels/next`);
   const item = q.item;
   return (
     <>
diff --git a/apps/web/src/app/(app)/b/[id]/layout.tsx b/apps/web/src/app/(app)/b/[id]/layout.tsx
--- a/apps/web/src/app/(app)/b/[id]/layout.tsx
+++ b/apps/web/src/app/(app)/b/[id]/layout.tsx
@@ -1,6 +1,6 @@
 import type { ReactNode } from "react";
 import Link from "next/link";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import type { Brand } from "@/lib/types";
 
 export default async function BrandLayout({
@@ -11,7 +11,7 @@ export default async function BrandLayout({
   params: Promise<{ id: string }>;
 }) {
   const { id } = await params;
-  const brand = await api<Brand>(`/brands/${id}`);
+  const brand = await api<Brand>(`/brands/${seg(id)}`);
   return (
     <>
       <h1>{brand.name}</h1>
diff --git a/apps/web/src/app/(app)/b/[id]/page.tsx b/apps/web/src/app/(app)/b/[id]/page.tsx
--- a/apps/web/src/app/(app)/b/[id]/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/page.tsx
@@ -1,7 +1,7 @@
 import Link from "next/link";
 import { Filters } from "@/components/Filters";
 import { Tile } from "@/components/Tile";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import { apiQuery, KIND, pct, validDays, type Params } from "@/lib/format";
 import type { Deltas, Metrics, Recommendation, Sov } from "@/lib/types";
 
@@ -21,10 +21,10 @@ export default async function Overview({
   const days = valid ?? 7;
   const dq = apiQuery(sp, ["days"], valid ? ["date_from"] : ["date_from", "days"]);
   const [m, d, sov, recs] = await Promise.all([
-    api<Metrics>(`/brands/${id}/metrics${q}`),
-    api<Deltas>(`/brands/${id}/deltas${dq}`),
-    api<Sov>(`/brands/${id}/sov${q}`),
-    api<Recommendation[]>(`/brands/${id}/recommendations/top`),
+    api<Metrics>(`/brands/${seg(id)}/metrics${q}`),
+    api<Deltas>(`/brands/${seg(id)}/deltas${dq}`),
+    api<Sov>(`/brands/${seg(id)}/sov${q}`),
+    api<Recommendation[]>(`/brands/${seg(id)}/recommendations/top`),
   ]);
   const max = Math.max(...sov.entities.map((e) => e.share ?? 0), 0.0001);
   return (
diff --git a/apps/web/src/app/(app)/b/[id]/pages/page.tsx b/apps/web/src/app/(app)/b/[id]/pages/page.tsx
--- a/apps/web/src/app/(app)/b/[id]/pages/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/pages/page.tsx
@@ -1,5 +1,5 @@
 import Link from "next/link";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import { pageNote, type Params } from "@/lib/format";
 import type { PageAudit } from "@/lib/types";
 
@@ -21,7 +21,7 @@ export default async function Pages({
   const { id } = await params;
   const sp = await searchParams;
   // Newest first, latest per (cluster, url): the API orders it.
-  const audits = await api<PageAudit[]>(`/brands/${id}/pages`);
+  const audits = await api<PageAudit[]>(`/brands/${seg(id)}/pages`);
   return (
     <>
       {pageNote(sp.queued) && <p className="muted">{pageNote(sp.queued)}</p>}
diff --git a/apps/web/src/app/(app)/b/[id]/products/actions.ts b/apps/web/src/app/(app)/b/[id]/products/actions.ts
--- a/apps/web/src/app/(app)/b/[id]/products/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/products/actions.ts
@@ -1,7 +1,7 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import type { ImportResult, Queued } from "@/lib/types";
 
 const back = (id: string, status: string, extra = "") =>
@@ -18,7 +18,7 @@ export async function importCsv(form: FormData) {
   if (!(file instanceof File) || file.size === 0) return back(id, "nofile");
   let r: ImportResult;
   try {
-    r = await api<ImportResult>(`/brands/${id}/products/import/csv`, {
+    r = await api<ImportResult>(`/brands/${seg(id)}/products/import/csv`, {
       method: "POST",
       headers: { "Content-Type": "text/csv" },
       body: await file.text(),
@@ -33,7 +33,7 @@ export async function importCsv(form: FormData) {
 export async function importFeed(form: FormData) {
   const id = String(form.get("brand_id"));
   const url = String(form.get("url") ?? "").trim();
-  const job = await api<Queued>(`/brands/${id}/products/import/feed`, {
+  const job = await api<Queued>(`/brands/${seg(id)}/products/import/feed`, {
     method: "POST",
     headers: { "Content-Type": "application/json" },
     body: JSON.stringify({ url }),
@@ -45,7 +45,7 @@ export async function runProducts(form: FormData) {
   const id = String(form.get("brand_id"));
   let job: Queued;
   try {
-    job = await api<Queued>(`/brands/${id}/products/run`, { method: "POST" });
+    job = await api<Queued>(`/brands/${seg(id)}/products/run`, { method: "POST" });
   } catch (e) {
     if (is422(e)) return back(id, "empty");
     throw e;
@@ -55,6 +55,6 @@ export async function runProducts(form: FormData) {
 
 export async function clearProducts(form: FormData) {
   const id = String(form.get("brand_id"));
-  await api(`/brands/${id}/products`, { method: "DELETE" });
+  await api(`/brands/${seg(id)}/products`, { method: "DELETE" });
   back(id, "cleared");
 }
diff --git a/apps/web/src/app/(app)/b/[id]/products/page.tsx b/apps/web/src/app/(app)/b/[id]/products/page.tsx
--- a/apps/web/src/app/(app)/b/[id]/products/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/products/page.tsx
@@ -1,4 +1,4 @@
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import { droppedNote, productNote, type Params } from "@/lib/format";
 import type { Product, ProductRuns } from "@/lib/types";
 import { clearProducts, importCsv, importFeed, runProducts } from "./actions";
@@ -41,8 +41,8 @@ export default async function Products({
   const { id } = await params;
   const sp = await searchParams;
   const [products, runs] = await Promise.all([
-    api<Product[]>(`/brands/${id}/products`),
-    api<ProductRuns>(`/brands/${id}/products/runs`),
+    api<Product[]>(`/brands/${seg(id)}/products`),
+    api<ProductRuns>(`/brands/${seg(id)}/products/runs`),
   ]);
   let msg = productNote(sp.queued);
   if (msg && sp.queued === "imported" && typeof sp.n === "string") {
diff --git a/apps/web/src/app/(app)/b/[id]/prompts/[pid]/page.tsx b/apps/web/src/app/(app)/b/[id]/prompts/[pid]/page.tsx
--- a/apps/web/src/app/(app)/b/[id]/prompts/[pid]/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/prompts/[pid]/page.tsx
@@ -1,5 +1,5 @@
 import Link from "next/link";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import { usd } from "@/lib/format";
 import type { Observation, Prompt } from "@/lib/types";
 
@@ -11,8 +11,8 @@ export default async function PromptDetail({
   const { id, pid } = await params;
   // There is no GET /brands/{id}/prompts/{pid}; find it in the list instead.
   const [rows, prompts] = await Promise.all([
-    api<Observation[]>(`/observations?brand_id=${id}&prompt_id=${pid}&limit=200`),
-    api<Prompt[]>(`/brands/${id}/prompts`),
+    api<Observation[]>(`/observations?brand_id=${seg(id)}&prompt_id=${seg(pid)}&limit=200`),
+    api<Prompt[]>(`/brands/${seg(id)}/prompts`),
   ]);
   const prompt = prompts.find((p) => p.id === pid);
   return (
diff --git a/apps/web/src/app/(app)/b/[id]/prompts/page.tsx b/apps/web/src/app/(app)/b/[id]/prompts/page.tsx
--- a/apps/web/src/app/(app)/b/[id]/prompts/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/prompts/page.tsx
@@ -1,7 +1,7 @@
 import Link from "next/link";
 import { Filters } from "@/components/Filters";
 import { CiBar } from "@/components/Tile";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import { apiQuery, ciText, pct, pts, type Params } from "@/lib/format";
 import type { PromptMetrics } from "@/lib/types";
 
@@ -24,7 +24,7 @@ export default async function Prompts({
   const { id } = await params;
   const sp = await searchParams;
   const rows = await api<PromptMetrics[]>(
-    `/brands/${id}/prompts/metrics${apiQuery(sp)}`,
+    `/brands/${seg(id)}/prompts/metrics${apiQuery(sp)}`,
   );
   const sort = typeof sp.sort === "string" && sp.sort in KEYS ? sp.sort : "spread";
   const dir = sp.dir === "asc" ? 1 : -1;
diff --git a/apps/web/src/app/(app)/b/[id]/recommendations/actions.ts b/apps/web/src/app/(app)/b/[id]/recommendations/actions.ts
--- a/apps/web/src/app/(app)/b/[id]/recommendations/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/recommendations/actions.ts
@@ -1,29 +1,34 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 
 const brand = (form: FormData) => String(form.get("brand_id"));
-const rec = (form: FormData) =>
-  `/brands/${brand(form)}/recommendations/${String(form.get("rec_id"))}`;
+const rec = (form: FormData) => String(form.get("rec_id"));
 
 export async function generate(form: FormData) {
-  await api(`/brands/${brand(form)}/recommendations/generate`, {
+  await api(`/brands/${seg(brand(form))}/recommendations/generate`, {
     method: "POST",
   });
   redirect(`/b/${brand(form)}/recommendations`);
 }
 
 export async function accept(form: FormData) {
-  await api(`${rec(form)}/accept`, { method: "POST" });
+  await api(
+    `/brands/${seg(brand(form))}/recommendations/${seg(rec(form))}/accept`,
+    { method: "POST" },
+  );
   redirect(`/b/${brand(form)}/tasks`);
 }
 
 export async function dismiss(form: FormData) {
-  await api(`${rec(form)}/dismiss`, {
-    method: "POST",
-    headers: { "Content-Type": "application/json" },
-    body: JSON.stringify({ reason: String(form.get("reason") ?? "") }),
-  });
+  await api(
+    `/brands/${seg(brand(form))}/recommendations/${seg(rec(form))}/dismiss`,
+    {
+      method: "POST",
+      headers: { "Content-Type": "application/json" },
+      body: JSON.stringify({ reason: String(form.get("reason") ?? "") }),
+    },
+  );
   redirect(`/b/${brand(form)}/recommendations`);
 }
diff --git a/apps/web/src/app/(app)/b/[id]/recommendations/page.tsx b/apps/web/src/app/(app)/b/[id]/recommendations/page.tsx
--- a/apps/web/src/app/(app)/b/[id]/recommendations/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/recommendations/page.tsx
@@ -1,5 +1,5 @@
 import Link from "next/link";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import { RivalPages } from "@/components/RivalPages";
 import { KIND } from "@/lib/format";
 import type { Recommendation } from "@/lib/types";
@@ -20,7 +20,7 @@ export default async function Recommendations({
   params: Promise<{ id: string }>;
 }) {
   const { id } = await params;
-  const recs = await api<Recommendation[]>(`/brands/${id}/recommendations`);
+  const recs = await api<Recommendation[]>(`/brands/${seg(id)}/recommendations`);
   return (
     <>
       <form action={generate} className="row">
diff --git a/apps/web/src/app/(app)/b/[id]/reports/actions.ts b/apps/web/src/app/(app)/b/[id]/reports/actions.ts
--- a/apps/web/src/app/(app)/b/[id]/reports/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/reports/actions.ts
@@ -1,7 +1,7 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 
 const back = (id: string, status: string) =>
   redirect(`/b/${id}/reports?queued=${status}`);
@@ -9,7 +9,7 @@ const back = (id: string, status: string) =>
 export async function setCadence(form: FormData) {
   const id = String(form.get("brand_id"));
   const type = String(form.get("type"));
-  await api(`/brands/${id}/reports/${type}`, {
+  await api(`/brands/${seg(id)}/reports/${seg(type)}`, {
     method: "PUT",
     headers: { "Content-Type": "application/json" },
     body: JSON.stringify({ cadence: String(form.get("cadence")) }),
@@ -20,21 +20,25 @@ export async function setCadence(form: FormData) {
 export async function generateNow(form: FormData) {
   const id = String(form.get("brand_id"));
   const type = String(form.get("type"));
-  await api(`/brands/${id}/reports/${type}/runs`, { method: "POST" });
+  await api(`/brands/${seg(id)}/reports/${seg(type)}/runs`, { method: "POST" });
   back(id, "generated");
 }
 
 export async function share(form: FormData) {
   const id = String(form.get("brand_id"));
   const run = String(form.get("run_id"));
-  await api(`/brands/${id}/reports/runs/${run}/share`, { method: "POST" });
+  await api(`/brands/${seg(id)}/reports/runs/${seg(run)}/share`, {
+    method: "POST",
+  });
   back(id, "shared");
 }
 
 export async function revoke(form: FormData) {
   const id = String(form.get("brand_id"));
   const run = String(form.get("run_id"));
-  await api(`/brands/${id}/reports/runs/${run}/share`, { method: "DELETE" });
+  await api(`/brands/${seg(id)}/reports/runs/${seg(run)}/share`, {
+    method: "DELETE",
+  });
   back(id, "revoked");
 }
 
@@ -44,7 +48,7 @@ export async function setBranding(form: FormData) {
     const v = String(form.get(k) ?? "").trim();
     return v === "" ? null : v;
   };
-  await api(`/brands/${id}`, {
+  await api(`/brands/${seg(id)}`, {
     method: "PATCH",
     headers: { "Content-Type": "application/json" },
     body: JSON.stringify({
diff --git a/apps/web/src/app/(app)/b/[id]/reports/page.tsx b/apps/web/src/app/(app)/b/[id]/reports/page.tsx
--- a/apps/web/src/app/(app)/b/[id]/reports/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/reports/page.tsx
@@ -1,4 +1,4 @@
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import { REPORT_TYPE, reportNote, type Params } from "@/lib/format";
 import type { Brand, Report, ReportRun } from "@/lib/types";
 import {
@@ -21,9 +21,9 @@ export default async function Reports({
   const { id } = await params;
   const sp = await searchParams;
   const [brand, reports, runs] = await Promise.all([
-    api<Brand>(`/brands/${id}`),
-    api<Report[]>(`/brands/${id}/reports`),
-    api<ReportRun[]>(`/brands/${id}/reports/runs`),
+    api<Brand>(`/brands/${seg(id)}`),
+    api<Report[]>(`/brands/${seg(id)}/reports`),
+    api<ReportRun[]>(`/brands/${seg(id)}/reports/runs`),
   ]);
   const msg = reportNote(sp.queued);
   return (
diff --git a/apps/web/src/app/(app)/b/[id]/serp/actions.ts b/apps/web/src/app/(app)/b/[id]/serp/actions.ts
--- a/apps/web/src/app/(app)/b/[id]/serp/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/serp/actions.ts
@@ -1,12 +1,12 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import type { Queued } from "@/lib/types";
 
 export async function runSerpAudit(form: FormData) {
   const id = String(form.get("brand_id"));
-  const job = await api<Queued>(`/brands/${id}/audits/serp`, {
+  const job = await api<Queued>(`/brands/${seg(id)}/audits/serp`, {
     method: "POST",
   });
   // The API returns this hour's job, which may already be done.
@@ -16,7 +16,7 @@ export async function runSerpAudit(form: FormData) {
 export async function addDomain(form: FormData) {
   const id = String(form.get("brand_id"));
   const host = String(form.get("host") ?? "").trim();
-  await api(`/brands/${id}/domains`, {
+  await api(`/brands/${seg(id)}/domains`, {
     method: "POST",
     headers: { "Content-Type": "application/json" },
     body: JSON.stringify({ host }),
diff --git a/apps/web/src/app/(app)/b/[id]/serp/page.tsx b/apps/web/src/app/(app)/b/[id]/serp/page.tsx
--- a/apps/web/src/app/(app)/b/[id]/serp/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/serp/page.tsx
@@ -1,4 +1,4 @@
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import {
   auditNote,
   ownershipText,
@@ -22,9 +22,9 @@ export default async function Serp({
   const { id } = await params;
   const sp = await searchParams;
   const [{ job, audits }, brand, domains] = await Promise.all([
-    api<SerpAudits>(`/brands/${id}/audits/serp`),
-    api<Brand>(`/brands/${id}`),
-    api<Domain[]>(`/brands/${id}/domains`),
+    api<SerpAudits>(`/brands/${seg(id)}/audits/serp`),
+    api<Brand>(`/brands/${seg(id)}`),
+    api<Domain[]>(`/brands/${seg(id)}/domains`),
   ]);
   const status = serpStatus(job);
   return (
diff --git a/apps/web/src/app/(app)/b/[id]/site/actions.ts b/apps/web/src/app/(app)/b/[id]/site/actions.ts
--- a/apps/web/src/app/(app)/b/[id]/site/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/site/actions.ts
@@ -1,12 +1,12 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import type { Queued } from "@/lib/types";
 
 export async function runAudit(form: FormData) {
   const id = String(form.get("brand_id"));
-  const job = await api<Queued>(`/brands/${id}/audits/crawl`, {
+  const job = await api<Queued>(`/brands/${seg(id)}/audits/crawl`, {
     method: "POST",
   });
   // The API returns this hour's job, which may already be done.
diff --git a/apps/web/src/app/(app)/b/[id]/site/page.tsx b/apps/web/src/app/(app)/b/[id]/site/page.tsx
--- a/apps/web/src/app/(app)/b/[id]/site/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/site/page.tsx
@@ -1,4 +1,4 @@
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import { auditNote, type Params } from "@/lib/format";
 import type { SiteAudit } from "@/lib/types";
 import { runAudit } from "./actions";
@@ -12,7 +12,7 @@ export default async function Site({
 }) {
   const { id } = await params;
   const sp = await searchParams;
-  const audits = await api<SiteAudit[]>(`/brands/${id}/audits/crawl`);
+  const audits = await api<SiteAudit[]>(`/brands/${seg(id)}/audits/crawl`);
   return (
     <>
       <form action={runAudit} className="row">
diff --git a/apps/web/src/app/(app)/b/[id]/tasks/actions.ts b/apps/web/src/app/(app)/b/[id]/tasks/actions.ts
--- a/apps/web/src/app/(app)/b/[id]/tasks/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/tasks/actions.ts
@@ -1,7 +1,7 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 
 export async function updateTask(form: FormData) {
   const id = String(form.get("brand_id"));
@@ -12,7 +12,7 @@ export async function updateTask(form: FormData) {
   };
   const status = form.get("status");
   if (status) body.status = String(status);
-  await api(`/brands/${id}/tasks/${String(form.get("task_id"))}`, {
+  await api(`/brands/${seg(id)}/tasks/${seg(String(form.get("task_id")))}`, {
     method: "PATCH",
     headers: { "Content-Type": "application/json" },
     body: JSON.stringify(body),
diff --git a/apps/web/src/app/(app)/b/[id]/tasks/page.tsx b/apps/web/src/app/(app)/b/[id]/tasks/page.tsx
--- a/apps/web/src/app/(app)/b/[id]/tasks/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/tasks/page.tsx
@@ -1,4 +1,4 @@
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import { ciText, pct, pts, type Rate } from "@/lib/format";
 import type { Task } from "@/lib/types";
 import { updateTask } from "./actions";
@@ -29,7 +29,7 @@ export default async function Tasks({
   params: Promise<{ id: string }>;
 }) {
   const { id } = await params;
-  const tasks = await api<Task[]>(`/brands/${id}/tasks`);
+  const tasks = await api<Task[]>(`/brands/${seg(id)}/tasks`);
   return (
     <>
       {tasks.length === 0 && (
diff --git a/apps/web/src/app/(app)/o/[oid]/page.tsx b/apps/web/src/app/(app)/o/[oid]/page.tsx
--- a/apps/web/src/app/(app)/o/[oid]/page.tsx
+++ b/apps/web/src/app/(app)/o/[oid]/page.tsx
@@ -1,5 +1,5 @@
 import Link from "next/link";
-import { api } from "@/lib/api";
+import { api, seg } from "@/lib/api";
 import { highlight, usd } from "@/lib/format";
 import type { Brand, Competitor, ObservationDetail } from "@/lib/types";
 
@@ -9,10 +9,10 @@ export default async function ObservationPage({
   params: Promise<{ oid: string }>;
 }) {
   const { oid } = await params;
-  const o = await api<ObservationDetail>(`/observations/${oid}`);
+  const o = await api<ObservationDetail>(`/observations/${seg(oid)}`);
   const [brand, rivals] = await Promise.all([
-    api<Brand>(`/brands/${o.brand_id}`),
-    api<Competitor[]>(`/brands/${o.brand_id}/competitors`),
+    api<Brand>(`/brands/${seg(o.brand_id)}`),
+    api<Competitor[]>(`/brands/${seg(o.brand_id)}/competitors`),
   ]);
   const names = new Map<string, string>([
     [brand.id, brand.name],
diff --git a/apps/web/src/app/r/[token]/page.tsx b/apps/web/src/app/r/[token]/page.tsx
--- a/apps/web/src/app/r/[token]/page.tsx
+++ b/apps/web/src/app/r/[token]/page.tsx
@@ -1,12 +1,12 @@
 import type { Metadata } from "next";
 import { ReportBody } from "@/components/ReportBody";
-import { publicApi } from "@/lib/api";
+import { publicApi, seg } from "@/lib/api";
 import type { ReportRunDetail } from "@/lib/types";
 
 type Props = { params: Promise<{ token: string }> };
 
 const load = async (params: Props["params"]) =>
-  publicApi<ReportRunDetail>(`/r/${encodeURIComponent((await params).token)}`);
+  publicApi<ReportRunDetail>(`/r/${seg((await params).token)}`);
 
 // White-label: override the root layout's title, which names the product.
 // Next memoizes the identical GET within one request, so this is not a
diff --git a/apps/web/src/lib/api-paths.test.ts b/apps/web/src/lib/api-paths.test.ts
new file mode 100644
--- /dev/null
+++ b/apps/web/src/lib/api-paths.test.ts
@@ -0,0 +1,50 @@
+import { readdirSync, readFileSync } from "node:fs";
+import { join } from "node:path";
+import { expect, test } from "vitest";
+
+// Query strings built by URLSearchParams, which encodes them already.
+const QUERIES = new Set(["q", "dq", "wq", "feedQuery", "apiQuery(sp)"]);
+const APP = join(__dirname, "..", "app");
+const CALL = /\b(?:api|publicApi)(?:<[^(`]*>)?\(\s*/g;
+// The whole first argument is one literal, followed by "," or ")".
+const LITERAL = /^(`[^`]*`|"[^"]*"|'[^']*')\s*[,)]/;
+const PATH = /\b(?:api|publicApi)(?:<[^(`]*>)?\(\s*`([^`]*)`/g;
+
+/** True for exactly one seg(...) call: its "(" closes at the last character. */
+const isSeg = (expr: string) => {
+  if (!expr.startsWith("seg(")) return false;
+  let depth = 0;
+  for (let i = 3; i < expr.length; i++) {
+    if (expr[i] === "(") depth += 1;
+    if (expr[i] === ")") depth -= 1;
+    if (depth === 0) return i === expr.length - 1;
+  }
+  return false;
+};
+
+test("every value in an API path goes through seg()", () => {
+  const files = readdirSync(APP, { recursive: true, encoding: "utf8" }).filter(
+    (f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f),
+  );
+  const bad: string[] = [];
+  let templates = 0;
+  for (const f of files) {
+    const code = readFileSync(join(APP, f), "utf8")
+      .split("\n")
+      .filter((line) => !/^\s*(\/\/|\/\*|\*)/.test(line))
+      .join("\n");
+    for (const m of code.matchAll(CALL)) {
+      if (!LITERAL.test(code.slice(m.index + m[0].length))) {
+        bad.push(`${f}: path is not one literal`);
+      }
+    }
+    for (const [, path] of code.matchAll(PATH)) {
+      templates += 1;
+      for (const [, expr] of path.matchAll(/\$\{([^}]*)\}/g)) {
+        if (!isSeg(expr) && !QUERIES.has(expr)) bad.push(`${f}: \${${expr}}`);
+      }
+    }
+  }
+  expect(templates).toBeGreaterThanOrEqual(40);
+  expect(bad).toEqual([]);
+});
diff --git a/apps/web/src/lib/api.test.ts b/apps/web/src/lib/api.test.ts
--- a/apps/web/src/lib/api.test.ts
+++ b/apps/web/src/lib/api.test.ts
@@ -9,7 +9,8 @@ vi.mock("next/navigation", () => ({
   redirect: vi.fn(),
 }));
 
-const { publicApi } = await import("./api");
+const { api, publicApi, seg } = await import("./api");
+const { cookies } = await import("next/headers");
 
 const stub = (status: number) =>
   vi.stubGlobal(
@@ -17,7 +18,15 @@ const stub = (status: number) =>
     vi.fn(async () => new Response("{}", { status })),
   );
 
-afterEach(() => vi.unstubAllGlobals());
+afterEach(() => {
+  vi.unstubAllGlobals();
+  vi.restoreAllMocks();
+});
+
+const signedIn = () =>
+  vi.mocked(cookies).mockResolvedValue({
+    get: () => ({ value: "bsi_key_1" }),
+  } as never);
 
 test.each([404, 422])("publicApi maps %i to notFound", async (status) => {
   stub(status);
@@ -30,3 +39,62 @@ test("publicApi throws a plain error on 5xx and sends no auth", async () => {
   const init = vi.mocked(fetch).mock.calls[0][1];
   expect(init).toEqual({ cache: "no-store" });
 });
+
+test.each([
+  "/brands/../x",
+  "/brands/./x",
+  "/brands/%2e%2E/x",
+  "/brands/..\\x",
+  "/brands/x#y",
+  "/brands/x y",
+  "/brands/x?",
+  "/brands/x?a=b'c",
+])("api refuses %s without calling the API", async (path) => {
+  signedIn();
+  const log = vi.spyOn(console, "error").mockImplementation(() => {});
+  const fetchMock = vi.fn();
+  vi.stubGlobal("fetch", fetchMock);
+  await expect(api(path)).rejects.toThrow("NOT_FOUND");
+  expect(fetchMock).not.toHaveBeenCalled();
+  expect(log).toHaveBeenCalledWith("API path refused", path);
+});
+
+test("api sends a path with a query string as written", async () => {
+  signedIn();
+  vi.stubGlobal(
+    "fetch",
+    vi.fn(async () => new Response("{}", { status: 200 })),
+  );
+  const path = "/brands/1eb6c00a-4b18-4512-b515-dd1d8039511f/sov?days=14";
+  await api(path);
+  expect(vi.mocked(fetch).mock.calls[0][0]).toBe(
+    `http://localhost:8000/v1${path}`,
+  );
+});
+
+test("publicApi refuses a dot segment", async () => {
+  vi.spyOn(console, "error").mockImplementation(() => {});
+  const fetchMock = vi.fn();
+  vi.stubGlobal("fetch", fetchMock);
+  await expect(publicApi("/r/..")).rejects.toThrow("NOT_FOUND");
+  expect(fetchMock).not.toHaveBeenCalled();
+});
+
+test("seg returns a UUID, a report type and a share token unchanged", () => {
+  for (const v of [
+    "1eb6c00a-4b18-4512-b515-dd1d8039511f",
+    "cmo",
+    "Ab3_-xYz9Ab3_-xYz9Ab3",
+  ]) {
+    expect(seg(v)).toBe(v);
+  }
+});
+
+test.each(["", "..", "a/b", "a%2Fb", "a?b", "a#b", "a b"])(
+  "seg refuses %j",
+  (value) => {
+    const log = vi.spyOn(console, "error").mockImplementation(() => {});
+    expect(() => seg(value)).toThrow("NOT_FOUND");
+    expect(log).toHaveBeenCalledWith("API path value refused", value);
+  },
+);
diff --git a/apps/web/src/lib/api.ts b/apps/web/src/lib/api.ts
--- a/apps/web/src/lib/api.ts
+++ b/apps/web/src/lib/api.ts
@@ -6,8 +6,27 @@ import { COOKIE } from "./cookie";
 export const API_URL = process.env.API_URL ?? "http://localhost:8000";
 export { COOKIE };
 
+// ponytail: a backstop for anything a call site misses. It refuses dot
+// segments in any spelling, '\', '#' and anything the URL parser would
+// re-encode; a '/', '%2F' or '?' inside a value passes it, and seg() at each
+// call site refuses those.
+function sendAsWritten(path: string) {
+  const u = new URL(path, "http://api.invalid");
+  if (u.pathname + u.search === path) return;
+  console.error("API path refused", path);
+  notFound();
+}
+
+/** One path segment from a route param, form field or API value. */
+export function seg(value: string): string {
+  if (/^[A-Za-z0-9_-]+$/.test(value)) return value;
+  console.error("API path value refused", value);
+  notFound();
+}
+
 /** Server-side call to /v1. The key comes from the httpOnly cookie. */
 export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
+  sendAsWritten(path);
   const key = (await cookies()).get(COOKIE)?.value;
   if (!key) redirect("/login");
   const res = await fetch(`${API_URL}/v1${path}`, {
@@ -47,6 +66,7 @@ export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
 
 /** Server-side call to a public /v1 route: no cookie, no key. */
 export async function publicApi<T>(path: string): Promise<T> {
+  sendAsWritten(path);
   const res = await fetch(`${API_URL}/v1${path}`, { cache: "no-store" });
   // 422 = malformed token (e.g. a link truncated by a mail client): to the
   // reader that is just a link that doesn't exist.
```

## Testing

`apps/web/src/lib/api.test.ts` gains (R1):
- `api refuses %s without calling the API`, for `/brands/../x`, `/brands/./x`, `/brands/%2e%2E/x`, `/brands/..\x`, `/brands/x#y`, `/brands/x y`, `/brands/x?`, `/brands/x?a=b'c`: signed in, `api(path)` rejects with the mocked `notFound`'s `NOT_FOUND`, `fetch` is not called, and `console.error` is called with `"API path refused"` and the path.
- `api sends a path with a query string as written`: `/brands/1eb6c00a-4b18-4512-b515-dd1d8039511f/sov?days=14` reaches `fetch` as `http://localhost:8000/v1` plus that path.
- `publicApi refuses a dot segment`: `/r/..` rejects with `NOT_FOUND` and `fetch` is not called (the log line is not asserted; the function is shared).
- `seg returns a UUID, a report type and a share token unchanged`.
- `seg refuses %j`, for `""`, `..`, `a/b`, `a%2Fb`, `a?b`, `a#b`, `a b`: it throws `NOT_FOUND` and logs `"API path value refused"` with the value.

New `apps/web/src/lib/api-paths.test.ts`, `every value in an API path goes through seg()`: it reads every non-test `.ts`/`.tsx` file under `src/app`, skipping comment lines; fails for any `api(`/`publicApi(` call (generics allowed) whose whole first argument is not one quoted or template literal followed by `,` or `)` (so a literal joined with `+` fails); finds each path template (a regex that spans lines), requires at least 40 of them (55 today), and fails, naming the file and expression, for any `${…}` that is neither exactly one `seg(…)` call (its `(` closes at the last character) nor one of `q`, `dq`, `wq`, `feedQuery`, `apiQuery(sp)`. Not scanned: files outside `src/app` (none calls `api()` today), and a raw value later stored in one of the five query variables. Comment skipping is by line: a code line starting with `*`, or with `/* … */` before code, is skipped; a block-comment line not starting with `*` is scanned, so an `api(` inside it is checked like code and can also add to the template count. None occurs today.

No test checks that every real path passes at run time (R2). Expected gates: web 71 vitest (52 on main plus 19), lint, typecheck and build pass; backend unchanged at `1753 passed, 2 deselected`.

### Proof

Run 2026-10-07 in the scratchpad on a copy of main's `apps/web` (`git archive`), with the repo's `node_modules` linked.

- Red, main's code with the two new test files: `Tests  18 failed | 4 passed (22)`: the 8 guard refusal cases, `publicApi refuses a dot segment`, the 8 `seg` tests (`seg` does not exist on main) and the scan test, which lists every unwrapped value; the 4 passing are the 3 existing tests and the query-string test.
- Green, patched: the two files give `Tests  22 passed (22)`; typecheck, lint, test (`Tests  71 passed (71)`) and build (`Compiled successfully`) exit 0, with no `API path refused` or `API path value refused` line in the output. The gate's `gen:check` was not run: the copy has no backend (`scripts/export_openapi.py`). No API file changes.
- Prettier is not in the gate. `api.ts` and both test files pass `prettier --check`. Of the 28 changed call-site files, 11 were Prettier-clean on main and all 11 stay clean (`recommendations/actions.ts` and `reports/actions.ts` rewrapped); the other 17 were not clean on main and are left as edited (R3, corrected).
- Outside `seg(` wraps and imports, the call-site diff is Prettier rewrapping and the inlined recommendation paths.

Each change below fails tests (counts from the two files, 22 tests):

| Mutant | Change | Result | Failing |
|---|---|---|---|
| M1 | no guard in `api()` | `8 failed | 14 passed (22)` | the 8 guard refusal cases |
| M2 | no guard in `publicApi()` | `1 failed | 21 passed (22)` | `publicApi refuses a dot segment` |
| M3 | the query string left out of the guard's comparison | `1 failed | 21 passed (22)` | `api sends a path with a query string as written` |
| M4 | `api()`'s guard moved after `fetch` | `8 failed | 14 passed (22)` | the 8 guard refusal cases (`fetch` was called) |
| M5 | no guard log line | `8 failed | 14 passed (22)` | the 8 guard refusal cases |
| M6 | `seg()` accepts `/` | `1 failed | 21 passed (22)` | `seg refuses "a/b"` |
| M7 | no `seg()` log line | `7 failed | 15 passed (22)` | the 7 `seg` refusal cases |
| M8 | `addDomain`'s path left unwrapped | `1 failed | 21 passed (22)` | `every value in an API path goes through seg()` |
| M9 | `q` missing from the scan's allowlist | `1 failed | 21 passed (22)` | `every value in an API path goes through seg()` |
| M10 | the scan's path regex finds nothing | `1 failed | 21 passed (22)` | `every value in an API path goes through seg()` |
| M11 | `addDomain`'s path built in a variable | `1 failed | 21 passed (22)` | `every value in an API path goes through seg()` |
| M12 | `addDomain`'s value written `${seg(id) + host}` | `1 failed | 21 passed (22)` | `every value in an API path goes through seg()` |
| M13 | the guard ignores the query but refuses a bare `?` | `1 failed | 21 passed (22)` | `api refuses /brands/x?a=b'c without calling the API` |
| M14 | `addDomain`'s path written `"/brands/" + id + "/domains"` | `1 failed | 21 passed (22)` | `every value in an API path goes through seg()` |
| M15 | `addDomain`'s path written as a template joined with `+` | `1 failed | 21 passed (22)` | `every value in an API path goes through seg()` |

## Rulings

Quoted from the ledger (R2's "about 40" was written before the 55 templates were counted, R4):

> Ruling: R1. Decided: the refusal tests sign in with a mocked cookie (a signedIn() helper) and silence console.error with vi.spyOn, and afterEach calls vi.restoreAllMocks(); none of this was in the Section 2 text. Found by: the controller, running the proof: without a cookie, mutant M4 (the guard moved after fetch) failed only because api() crashed reading an undefined cookie store, not on the "fetch not called" assertion. Why: each mutant then fails on the assertion that names its fault, and the gate output stays free of "API path refused" lines. Cost if wrong: an unexpected console.error in those tests would be hidden. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R2. Decided: no test checks that every real call site's path passes the guard; the paths are built from UUIDs (route params and hidden form fields), report type slugs and URLSearchParams query strings, which the URL parser leaves unchanged, and the one query-string test pins that case. Found by: the controller, writing the design (named in Section 2). Why: the call sites are about 40 Server Component and server action paths with no page-test harness in the repo. Cost if wrong: a page whose path the URL parser re-encodes would show the not-found page, with "API path refused" and the path in the web server log. How named: in chat, 2026-10-07, in Section 2 and after the proof run.

> Ruling: R3. Decided: the proof departs from the revised Section 2 text in four ways: 28 call-site files changed, not "about 25"/26 (the count missed two); the recommendations helper rec() now returns only the rec_id and both calls inline the path with seg() on each value, so the scan test sees seg(...) at every interpolation; the seg refusal test titles use %j so the empty string shows; recommendations/actions.ts and reports/actions.ts, Prettier-clean on main, are rewrapped by Prettier after the edit (the other changed files were not Prettier-clean on main and are left as edited). Found by: the controller, running the proof. Why: facts of the edit, not design changes. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R4. Decided: the spec review's other findings are fixed in the rewritten spec: route params can be set by any link (GET-only, the operator's own key) (Important 3); the live check is possible read-only from the address bar, and is offered after merge, asked first (Important 2); `../..` can leave /v1 (Minor 4); the counts are 55 path templates in 28 files (Minor 5); the value lists name observation_id, entity_id, rec_id and pid (Minor 6); the claim that api() checks before reading the cookie is kept and pinned by no test, stated as such (Minor 7); the publicApi refusal test does not assert the log line, stated (Minor 8); the "?" gap no longer exists for interpolated values, since seg() refuses "?" (Minor 9). Found by: the spec reviewer (Opus 5.5, ad3141fc576bdde33), 2026-10-07. Why: wrong or incomplete statements of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R5. Decided: the second spec review's other findings are fixed: the Proof and R3's Prettier statement is corrected by a Correction to R3 line (11 changed call-site files were Prettier-clean on main and stay clean, 2 of them rewrapped; 17 were not clean on main) (Important 1); R2's "about 40" gets a note that 55 path templates were counted later (R4) (Minor 3); the live check is called "page views only", not read-only, since each view writes api_key.last_used_at (Minor 4); feedQuery is described as apiQuery output plus "&days=" and the constant FEED_DAYS (Minor 5); the ponytail comment on sendAsWritten says seg() at each call site refuses "/", "%2F" and "?" (Minor 6); the Design says a refusal in a server action relies on Next handling notFound() there, which api() already relies on for an API 404 (Minor 7). Found by: the spec reviewer (Opus 5.5, a015dcf18c3d22bd2), 2026-10-07. Why: wrong or incomplete statements of mine, one in a code comment. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the second spec review.

> Correction to R3 (2026-10-07, from the second spec review): 11 of the 28 changed call-site files were Prettier-clean on main and all 11 stay clean (recommendations/actions.ts and reports/actions.ts rewrapped); the other 17 were not clean on main and are left as edited.

> Ruling: R6. Decided: the spec re-review's findings are fixed: the scan test now requires the whole first argument of each api()/publicApi() call to be one quoted or template literal followed by "," or ")", so a literal joined with "+" fails, as the user's "Harden scan" choice said (Important 1; mutants M14 and M15 added); feedQuery is described as apiQuery output plus "days=" and the constant FEED_DAYS, joined with "&" or "?" (Minor 1); the spec states the comment skipping's limits (a code line starting with "*" or "/* … */" is skipped; a block-comment line not starting with "*" is scanned, which can only fail the test) (Minor 2). Found by: the spec re-reviewer (Opus 5.5, a698f8d3a147689af), 2026-10-07. Why: the test fell short of the user's approved choice, and two statements were inexact. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the re-review.

> Ruling: R7. Decided: the R6 commit's regression is fixed: the proof's api.ts had been restored after the R6 mutant run from a copy taken before R5's comment change, which put back the old ponytail comment on sendAsWritten; the R5 wording ("a '/', '%2F' or '?' inside a value passes it, and seg() at each call site refuses those") is restored in the proof and the spec's diff, and the other proof files were checked against their latest versions (Important 1); the comment-limits text says a scanned block-comment line could also add to the template count, not only fail the test (Minor 2). Found by: the spec re-reviewer (Opus 5.5, a63daf67355d2d13a), 2026-10-07. Why: a regression from my own file restore, and an overstatement. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the re-review.

> Ruling: R8. Decided: the 9daba5a re-review's Minor 1 (the api.ts hunk headers changed with the content; the reviewer said no action needed) is left, unrecorded by R7 until now; the 90ee504 re-review's Minor 2 (a scanned block-comment line holding an unclosed api(` could also hide a later template from the scan; none exists today) is deferred. Found by: the spec re-reviewer (Opus 5.5, a0abfd1c7e77ff3bb), 2026-10-07. Why: Minor 1 needs no change; Minor 2 needs a contrived comment that no file has. Cost if wrong: such a comment, if ever written, could let one unwrapped value past the scan; seg() at that call site and the api() guard still apply at run time only if the value is wrapped or would be re-encoded. How named: in chat, 2026-10-07, after the re-review.

> Correction to R8 (2026-10-07, from the plan review): a scanned block-comment line holding an unclosed api(` hides the next template's values from the PATH check, but the test still fails on "path is not one literal" unless the next backtick after it is followed by "," or ")"; and the api() guard refuses dot segments, "\", "#" and re-encoded characters, not only re-encoded ones. The deferred minor quoted with R8 overstates the risk in the same way.

> Ruling: R9. Decided: the plan review's Minor 1 is fixed by the Correction to R8 line; Minor 2 is fixed: the Task 2 commit message says the scan "fails if a value in an src/app path template skips it"; Minor 3 (Task 1's commit step stages again, Task 2's relies on Step 5) is left as harmless. Found by: the plan reviewer (Opus 5.5, adbe523df7912402a), 2026-10-07. Why: an overstated risk and an overstated commit message of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the plan review.

> Ruling: R10. Decided: the plan re-review's Minor 1 is fixed: the plan's Architecture line says the scan test "fails if a value in an src/app path template skips seg()"; its Minor 2 (the Correction to R8 does not list the bare trailing "?" and simplifies the whitespace before "," or ")") is left, since nothing it says is false. No further review round: the commit changes one sentence. Found by: the plan re-reviewer (Opus 5.5, acc9e70f6a69ca2f7), 2026-10-07. Why: the same overstatement R9 fixed in the commit message. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the plan re-review.

Rulings made after the final review (R11 added by the first post-merge docs commit, R12 by the second), quoted from the ledger:

> Ruling: R11. Decided: no final fix wave. Minor 1 (the spec's Deferred minors list quotes only the spec-phase minor) is fixed by the post-merge docs commit, which adds the four task-review minors, and the PR body lists all five; Minor 2 (the refusal log lines record the value or path uncapped) is deferred; Minor 3 (the scan drops code lines that start with a comment marker) is the limit the spec already states. Found by: the final reviewer (Opus 5.5, a9f3c63a8276cb04c), 2026-10-07. Why: "Ready to merge? Yes" with no Critical or Important finding, and every deferred minor triaged "Not before merge". Cost if wrong: a very long tampered value is logged in full (log noise only). How named: in chat, 2026-10-07, before the gates and the finishing menu.

> Ruling: R12. Decided: the docs review's three minors are fixed: R11 and the five later deferred minors are credited to the first post-merge docs commit, in the findings and the spec (Minor 1); the paraphrased grep decision says the grep blocked "PR #100", as the ledger does, without the added "docs commit" detail (Minor 2); the findings and the spec say the live check was offered after PR #100 opened, before its merge, not after merge as the spec planned (Minor 3). Found by: the docs reviewer (Opus 5.5, a588d4b509344bc75), 2026-10-07. Why: inexact statements of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, before the fix commit.

## Deferred minors

Every deferred minor, quoted from the ledger (the last five added by the first post-merge docs commit):

- "minor (deferred): spec re-review (90ee504) minor 2, a scanned block-comment line holding an unclosed api(` could make the scan's PATH regex run on to the next real template and hide its interpolations; none exists today (R8)."
- "Task 1: minor (deferred): publicApi refuses a dot segment stubs console.error but does not assert the "API path refused" log line (plan-mandated, stated in the spec)."
- "Task 1: minor (deferred): vi.restoreAllMocks() does not clear the cookies mockResolvedValue between tests; harmless, since every test that needs a cookie calls signedIn()."
- "Task 2: minor (deferred): the scan's QUERIES allowlist exempts q, dq, wq, feedQuery and apiQuery(sp) by name, so a raw value later stored in one of them would pass (plan-mandated, stated in the spec)."
- "Task 2: minor (deferred): the scan reads only src/app; no api()/publicApi() caller exists outside it today (plan-mandated, stated in the spec)."
- "minor (deferred): final review minor 2, the refusal log lines in seg() and sendAsWritten record the raw value or path with no length cap (R11)."

## Live check

Not run: offered in chat on 2026-10-07 after PR #100 opened (before its merge, not after it as planned), and not taken up, as the ledger records (added by the first post-merge docs commit; docs/findings-slice49.md §2). As approved: optional (page views only), asked first after merge: on dev, with uvicorn and `next dev` running, open `/b/<uuid>/prompts/a'b` (today an API 422 error page; with this change the not-found page and "API path value refused" in the web server log). Each page view authenticates with the API key, which writes `api_key.last_used_at`.
