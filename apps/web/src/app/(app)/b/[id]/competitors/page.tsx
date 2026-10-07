import Link from "next/link";
import { Filters } from "@/components/Filters";
import { CiBar } from "@/components/Tile";
import { api, seg } from "@/lib/api";
import {
  apiQuery,
  ciText,
  crawlNote,
  lastDay,
  pct,
  pts,
  validDays,
  type Params,
} from "@/lib/format";
import type { Changes, EntityDeltas, EntityMetrics, SiteChanges } from "@/lib/types";
import { crawlRivals } from "./actions";

// The change feed always reads a fixed window; the days filter sets only
// the leaderboard deltas.
const FEED_DAYS = 14;

// Formatting only: the API sets the window. Starts are inclusive; ends
// are exclusive, so a range prints lastDay(end).
const date = (v: string) => new Date(v).toISOString().slice(0, 10);

const isWeb = (u: string) => u.startsWith("https://") || u.startsWith("http://");

const num = (v: number | null | undefined, digits = 1) =>
  v == null ? "—" : v.toFixed(digits);

export default async function Competitors({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const q = apiQuery(sp);
  // Window routes take days and date_to; they refuse date_from. An
  // invalid days is left out, so the API's default (7) applies.
  const valid = validDays(sp);
  const days = valid ?? 7;
  const wq = apiQuery(sp, ["days"], valid ? ["date_from"] : ["date_from", "days"]);
  const fq = apiQuery(sp, [], ["date_from"]);
  const feedQuery = `${fq}${fq ? "&" : "?"}days=${FEED_DAYS}`;
  const [rows, d, feed, site] = await Promise.all([
    api<EntityMetrics[]>(`/brands/${seg(id)}/competitors/metrics${q}`),
    api<EntityDeltas>(`/brands/${seg(id)}/competitors/deltas${wq}`),
    api<Changes>(`/brands/${seg(id)}/competitors/changes${feedQuery}`),
    api<SiteChanges>(`/brands/${seg(id)}/competitors/site-changes${feedQuery}`),
  ]);
  const deltaText = (eid: string, key: "mention_rate" | "sov") => {
    const x = d.deltas?.[eid]?.[key];
    if (!x) return null;
    const sig = x.label === "increase" || x.label === "decrease";
    return (
      <div className={sig ? (x.label === "increase" ? "up" : "down") : "muted"}>
        {sig ? `${pts(x.value)} vs previous ${days} days` : x.label}
      </div>
    );
  };
  return (
    <>
      <Filters sp={sp} days />
      <h2>Leaderboard</h2>
      {!d.comparable && <p className="muted">Deltas hidden: {d.reason}</p>}
      <table>
        <thead>
          <tr>
            <th>Entity</th>
            <th>Mention rate</th>
            <th>Recommended</th>
            <th>Share of voice</th>
            <th>Coverage</th>
            <th>Cited</th>
            <th>Avg position</th>
            <th>Sentiment</th>
            <th>Cited alongside</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.entity_id}>
              <td>
                {r.name} {r.type === "brand" && <span className="tag">you</span>}
              </td>
              <td>
                {pct(r.mention_rate.value)}
                <CiBar r={r.mention_rate} />
                <div className="muted">{ciText(r.mention_rate)}</div>
                {deltaText(r.entity_id, "mention_rate")}
              </td>
              <td>
                {pct(r.recommendation_rate.value)}{" "}
                {r.recommendation_rate.experimental && (
                  <span className="tag">experimental</span>
                )}
              </td>
              <td>
                {pct(r.sov.value)}
                <div className="muted">{ciText(r.sov)}</div>
                {deltaText(r.entity_id, "sov")}
              </td>
              <td>{pct(r.prompt_coverage.value)}</td>
              <td>{pct(r.citation_rate.value)}</td>
              <td>{num(r.avg_position.value)}</td>
              <td title={`+${pct(r.sentiment.positive.value)} / −${pct(r.sentiment.negative.value)}`}>
                {num(r.sentiment.index, 2)}
              </td>
              <td className="muted">
                {r.citing_domains.map((c) => `${c.domain} (${c.answers})`).join(", ") || "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <h2>Visibility changes</h2>
      <p className="muted">
        A rival that gained or lost at least 10 points on at least 10 prompts
        between {date(feed.window.before_from)}–{lastDay(feed.window.split)} and{" "}
        {date(feed.window.split)}–{lastDay(feed.window.to)}, with a significant
        pooled change. {feed.prompts} prompts have answers in both windows.
      </p>
      {feed.changes.length === 0 && (
        <p className="muted">
          {feed.reason ??
            "No competitor moved at least 10 points on at least 10 prompts with a significant pooled change."}
        </p>
      )}
      {feed.changes.map((c) => (
        <div className="card" key={`${c.competitor_id}-${c.direction}`}>
          <h3>
            {c.name} <span className={`tag ${c.direction === "up" ? "up" : "down"}`}>{c.direction}</span>
          </h3>
          <p>
            {pct(c.before.value)} → {pct(c.after.value)} ({pts(c.delta.value)},{" "}
            {pts(c.delta.ci_low)} to {pts(c.delta.ci_high)}) over {c.prompts.length} prompts ·
            engines {c.engines.join(", ") || "—"}
          </p>
          {c.new_citing_domains.length > 0 && (
            <p className="muted">New citing domains: {c.new_citing_domains.join(", ")}</p>
          )}
          {c.new_pages.length > 0 && (
            <p className="muted">
              New pages on their site (up to 20 shown):{" "}
              {c.new_pages.map((u) =>
                isWeb(u) ? (
                  <a key={u} href={u} rel="noreferrer" style={{ marginRight: 6 }}>
                    {u}
                  </a>
                ) : null,
              )}
            </p>
          )}
          {c.new_types.length > 0 && (
            <p className="muted">New structured data: {c.new_types.join(", ")}</p>
          )}
          <ul>
            {c.prompts.map((p) => (
              <li key={p.prompt_id}>
                {p.text}: {pct(p.before.value)} → {pct(p.after.value)}
              </li>
            ))}
          </ul>
          <p className="muted">
            Evidence:{" "}
            {c.observation_ids.length === 0 && "—"}
            {c.observation_ids.map((o) => (
              <Link key={o} href={`/o/${o}`} style={{ marginRight: 6 }}>
                {o.slice(0, 8)}
              </Link>
            ))}
          </p>
        </div>
      ))}
      <h2 id="site">Competitor site changes</h2>
      <form action={crawlRivals} className="row">
        <input type="hidden" name="brand_id" value={id} />
        <button className="primary">Crawl competitor sites now</button>
        {crawlNote(sp.queued) && <span className="muted">{crawlNote(sp.queued)}</span>}
      </form>
      <p className="muted">
        Pages first listed in a competitor&apos;s sitemap and structured data
        first seen between {date(site.window.start)} and {lastDay(site.window.to)}.
        A domain&apos;s first crawl is its baseline and never counts as new.
      </p>
      {site.competitors.every((r) => r.crawls.length === 0) && (
        <p className="muted">
          No crawl yet. Competitor domains are crawled weekly; declare domains
          on each competitor to include them.
        </p>
      )}
      {site.competitors.map((r) => (
        <div className="card" key={r.competitor_id}>
          <h3>{r.name}</h3>
          {r.crawls.length === 0 && <p className="muted">No domain crawled yet.</p>}
          {r.crawls.map((c) => (
            <p key={c.domain} className="muted">
              {c.domain}: crawled {date(c.crawled_at)} · {c.urls_seen} URLs ·{" "}
              {c.complete ? "complete" : "incomplete"}
              {c.errors.length > 0 && ` · ${c.errors.join("; ")}`}
            </p>
          ))}
          <p>{r.new_pages_total} new pages</p>
          {r.new_pages.length > 0 && (
            <ul>
              {r.new_pages.map((p) => (
                <li key={p.url}>
                  {isWeb(p.url) ? (
                    <a href={p.url} rel="noreferrer">{p.url}</a>
                  ) : (
                    p.url
                  )}{" "}
                  {p.types.map((t) => (
                    <span key={t} className="tag">{t}</span>
                  ))}
                </li>
              ))}
            </ul>
          )}
          {r.new_types.length > 0 && (
            <p>
              New structured data:{" "}
              {r.new_types.map((t) =>
                isWeb(t.url) ? (
                  <a key={t.type} href={t.url} rel="noreferrer" className="tag">
                    {t.type}
                  </a>
                ) : (
                  <span key={t.type} className="tag">{t.type}</span>
                ),
              )}
            </p>
          )}
        </div>
      ))}
    </>
  );
}
