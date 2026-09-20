"""A self-contained review page, generated from the curation queue.

Ninety-five proposals reviewed through `fermdb query review` one at a time is a lot of scrolling,
and the expensive part is not the decision — it is holding the paper's sentence, the proposed
fields and the consequence of accepting in view at once. That is a layout problem, so it gets a
page.

**The page never writes to the atlas.** PLAN.md D.3 puts the interface above the query layer and
names the violation to guard against — the UI reaching past it — and a browser cannot reach a
local SQLite file anyway. So decisions accumulate in the page and come out as the exact
`fermdb curate` commands to run. The person stays the actor, the audit log still records a human,
and nothing can be promoted by clicking.

Three choices worth stating:

* **Keyboard first.** Ninety-five items is enough that reaching for a mouse each time is the
  slowest part. `j`/`k` move, `a`/`r`/`e` decide, `u` undoes.
* **Grouped by paper, strains first within each.** That is not cosmetic: a measurement cannot be
  promoted before its strain exists, so reviewing in this order means the generated commands can
  actually run in the order they are printed.
* **Decisions survive a closed tab.** They go to `localStorage`, which is per-browser and never
  leaves the machine — exactly what it is for. Every read and write is wrapped, because a private
  window or blocked site data makes it throw, and losing an hour of review to that would be worse
  than not offering it.

The page embeds its data at generation time, so it works offline and keeps working if the
database moves. It is a snapshot: regenerate after promoting to see what is left.
"""

from __future__ import annotations

import html
import json
import sqlite3
from collections.abc import Sequence
from typing import Any, Final

from ..config import Settings
from .review import ReviewPacket, review_packet

__all__ = ["KIND_ORDER", "build_review_page", "packets_for_review"]

#: Review order within a paper. Strains first because promotion depends on it: a measurement
#: names its strain by name and cannot be written until that strain is a row.
KIND_ORDER: Final[tuple[str, ...]] = (
    "strains",
    "measurements",
    "co_reported_higher_alcohols",
    "modifications",
    "bottlenecks",
    "conditions",
    "pathway_configurations",
)


def packets_for_review(
    conn: sqlite3.Connection,
    *,
    settings: Settings | None = None,
    status: str = "pending",
    supplied: dict[str, Any] | None = None,
) -> tuple[ReviewPacket, ...]:
    """Every task in ``status``, ordered by paper then by promotion dependency."""
    settings = settings or Settings.load()
    rows = conn.execute(
        "SELECT id, publication_id, record_kind FROM curation_task WHERE status = ?", (status,)
    ).fetchall()
    order = {kind: index for index, kind in enumerate(KIND_ORDER)}
    ordered = sorted(
        rows,
        key=lambda r: (
            str(r["publication_id"]),
            order.get(str(r["record_kind"]), len(order)),
            str(r["id"]),
        ),
    )
    return tuple(
        review_packet(conn, str(r["id"]), settings=settings, supplied=supplied) for r in ordered
    )


def _titles(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        str(r["id"]): str(r["title"] or r["id"])
        for r in conn.execute("SELECT id, title FROM publication")
    }


def _payload(packets: Sequence[ReviewPacket], titles: dict[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for packet in packets:
        pub = packet.citation.source_id
        out.append(
            {
                "task_id": packet.task_id,
                "kind": packet.record_kind,
                "path": packet.record_path,
                "publication_id": pub,
                "title": titles.get(pub, pub),
                "span_status": packet.span.status,
                "span_detail": packet.span.verdict.detail,
                "before": packet.span.before,
                "quote": packet.span.quote_in_source,
                "after": packet.span.after,
                "fields": [
                    {"name": f.name, "display": f.value.display, "known": f.value.is_known}
                    for f in packet.fields
                ],
                "plan": packet.plan.note,
                "warnings": [{"code": w.code, "message": w.message} for w in packet.warnings],
            }
        )
    return out


_TEMPLATE: Final[str] = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>fermdb review &mdash; __COUNT__ proposals</title>
<style>
:root{
  --paper:#F6F8F7;--surface:#fff;--sunk:#EDF1EF;--ink:#131C1B;--ink2:#3C4947;--ink3:#6C7A77;
  --rule:#D8E0DD;--rule2:#C2CDC9;--accent:#A8641F;
  --ok:#2E6B4E;--ok-s:#E1EFE7;--no:#9A3B32;--no-s:#F6E4E1;--edit:#8A6A2F;--edit-s:#F6EEDC;
  --mono:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace;
  --sans:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif;
}
@media (prefers-color-scheme:dark){:root{
  --paper:#0F1615;--surface:#161F1E;--sunk:#1C2725;--ink:#E8EDEB;--ink2:#B4C0BD;--ink3:#87938F;
  --rule:#2A3634;--rule2:#3A4846;--accent:#D69A5C;
  --ok:#6FB78F;--ok-s:#17281F;--no:#D98A80;--no-s:#2B1B19;--edit:#C9A45F;--edit-s:#2A2318;}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 var(--sans);}
header{position:sticky;top:0;z-index:5;background:var(--surface);
  border-bottom:1px solid var(--rule);
  padding:12px 20px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
header h1{font-size:15px;margin:0;font-weight:600;letter-spacing:.01em}
.counts{font-family:var(--mono);font-size:12.5px;color:var(--ink3);display:flex;gap:14px;
  flex-wrap:wrap}
.counts b{font-weight:500}
.bar{flex:1;min-width:120px;height:6px;background:var(--sunk);border-radius:3px;overflow:hidden;
  display:flex}
.bar i{display:block;height:100%}
button{font:inherit;font-size:13px;padding:5px 11px;border:1px solid var(--rule2);
  background:var(--surface);
  color:var(--ink);border-radius:3px;cursor:pointer}
button:hover{border-color:var(--accent)}
button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
main{max-width:940px;margin:0 auto;padding:22px 20px 120px}
.paper{margin:30px 0 12px;padding-bottom:8px;border-bottom:1px solid var(--rule)}
.paper h2{font-size:15px;margin:0 0 3px;font-weight:600}
.paper .doi{font-family:var(--mono);font-size:11.5px;color:var(--ink3)}
.card{background:var(--surface);border:1px solid var(--rule);border-radius:4px;
  padding:16px 18px;margin:10px 0}
.card.sel{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.card.done-a{border-left:4px solid var(--ok)}
.card.done-r{border-left:4px solid var(--no);opacity:.62}
.card.done-e{border-left:4px solid var(--edit)}
.hd{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:10px}
.kind{font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;
  background:var(--sunk);color:var(--ink3);padding:2px 7px;border-radius:2px}
.path{font-family:var(--mono);font-size:11.5px;color:var(--ink3)}
.verdict{font-family:var(--mono);font-size:10.5px;margin-left:auto;padding:2px 7px;
  border-radius:2px}
.v-a{background:var(--ok-s);color:var(--ok)}.v-r{background:var(--no-s);color:var(--no)}
.v-e{background:var(--edit-s);color:var(--edit)}
blockquote{margin:0 0 12px;padding:12px 14px;background:var(--sunk);border-radius:3px;
  font-size:14px;line-height:1.62;color:var(--ink2)}
blockquote mark{background:transparent;color:var(--ink);font-weight:600;
  box-shadow:inset 0 -.55em 0 color-mix(in srgb,var(--accent) 24%,transparent)}
.fields{display:grid;grid-template-columns:auto 1fr;gap:3px 14px;font-size:13.5px;margin:0 0 10px}
.fields dt{font-family:var(--mono);font-size:11px;color:var(--ink3)}
.fields dd{margin:0}
.fields dd.absent{color:var(--ink3);font-style:italic}
.plan{font-size:12.5px;color:var(--ink3);font-family:var(--mono);margin-bottom:10px}
.warn{background:var(--edit-s);border-left:3px solid var(--edit);padding:9px 12px;border-radius:3px;
  font-size:13px;margin-bottom:10px;color:var(--ink2)}
.warn b{font-family:var(--mono);font-size:11px;color:var(--edit);display:block;margin-bottom:2px}
.acts{display:flex;gap:7px;flex-wrap:wrap}
.acts button.a:hover{border-color:var(--ok);color:var(--ok)}
.acts button.r:hover{border-color:var(--no);color:var(--no)}
footer{position:fixed;bottom:0;left:0;right:0;background:var(--surface);
  border-top:1px solid var(--rule);
  padding:10px 20px;display:flex;gap:12px;align-items:center;flex-wrap:wrap;font-size:12.5px}
kbd{font-family:var(--mono);font-size:11px;background:var(--sunk);border:1px solid var(--rule2);
  border-radius:3px;padding:1px 5px}
dialog{border:1px solid var(--rule2);border-radius:5px;background:var(--surface);color:var(--ink);
  max-width:860px;width:92vw;padding:0}
dialog::backdrop{background:rgba(0,0,0,.45)}
dialog .dh{padding:14px 18px;border-bottom:1px solid var(--rule);display:flex;
  align-items:center;gap:12px}
dialog h3{margin:0;font-size:14px}
dialog pre{margin:0;padding:16px 18px;font-family:var(--mono);font-size:12px;line-height:1.65;
  white-space:pre-wrap;word-break:break-all;max-height:56vh;overflow:auto;background:var(--sunk)}
.hint{color:var(--ink3)}
@media(max-width:620px){.fields{grid-template-columns:1fr}.fields dt{margin-top:7px}}
</style></head><body>
<header>
  <h1>fermdb review</h1>
  <div class="bar" id="bar"></div>
  <div class="counts" id="counts"></div>
  <button id="cmds">Show commands</button>
  <button id="reset">Reset</button>
</header>
<main id="list"></main>
<footer>
  <span class="hint">
    <kbd>j</kbd>/<kbd>k</kbd> move &nbsp; <kbd>a</kbd> accept &nbsp; <kbd>r</kbd> reject &nbsp;
    <kbd>e</kbd> edit &nbsp; <kbd>u</kbd> undo &nbsp; <kbd>c</kbd> commands
  </span>
  <span class="hint" style="margin-left:auto">Decisions stay in this browser. Nothing is written to the atlas.</span>
</footer>
<dialog id="dlg">
  <div class="dh"><h3>Run these, in order</h3>
    <button id="copy" style="margin-left:auto">Copy</button>
    <button id="close">Close</button></div>
  <pre id="out"></pre>
</dialog>
<script>
const DATA = __DATA__;
const CURATOR = __CURATOR__;
const KEY = "fermdb.review.v1";
let decisions = {};
try { decisions = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { decisions = {}; }
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(decisions)); } catch (e) {} };
let cursor = 0;
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function render() {
  const list = document.getElementById("list");
  list.innerHTML = "";
  let lastPub = null;
  DATA.forEach((d, i) => {
    if (d.publication_id !== lastPub) {
      lastPub = d.publication_id;
      const h = document.createElement("div");
      h.className = "paper";
      h.innerHTML = `<h2>${esc(d.title)}</h2><div class="doi">${esc(d.publication_id)}</div>`;
      list.appendChild(h);
    }
    const v = decisions[d.task_id];
    const card = document.createElement("article");
    card.className = "card" + (i === cursor ? " sel" : "") +
      (v ? " done-" + v.verdict[0] : "");
    card.id = "c" + i;
    card.innerHTML = `
      <div class="hd">
        <span class="kind">${esc(d.kind)}</span>
        <span class="path">${esc(d.path)}</span>
        ${v ? `<span class="verdict v-${v.verdict[0]}">${esc(v.verdict)}</span>` : ""}
      </div>
      ${d.quote ? `<blockquote>${esc(d.before)}<mark>${esc(d.quote)}</mark>${esc(d.after)}</blockquote>`
        : `<blockquote><em>span ${esc(d.span_status)}: ${esc(d.span_detail)}</em></blockquote>`}
      ${d.warnings.map(w => `<div class="warn"><b>${esc(w.code)}</b>${esc(w.message)}</div>`).join("")}
      <dl class="fields">${d.fields.map(f =>
        `<dt>${esc(f.name)}</dt><dd class="${f.known ? "" : "absent"}">${esc(f.display)}</dd>`).join("")}</dl>
      <div class="plan">on accept &rarr; ${esc(d.plan)}</div>
      <div class="acts">
        <button class="a" data-i="${i}" data-v="accept">Accept</button>
        <button class="r" data-i="${i}" data-v="reject">Reject</button>
        <button data-i="${i}" data-v="edit">Needs edit</button>
        ${v ? `<button data-i="${i}" data-v="">Undo</button>` : ""}
      </div>`;
    list.appendChild(card);
  });
  counts();
}

function counts() {
  const n = { accept: 0, reject: 0, edit: 0 };
  Object.values(decisions).forEach(d => { if (n[d.verdict] !== undefined) n[d.verdict]++; });
  const done = n.accept + n.reject + n.edit;
  document.getElementById("counts").innerHTML =
    `<span><b>${done}</b>/${DATA.length} reviewed</span>` +
    `<span style="color:var(--ok)"><b>${n.accept}</b> accept</span>` +
    `<span style="color:var(--no)"><b>${n.reject}</b> reject</span>` +
    `<span style="color:var(--edit)"><b>${n.edit}</b> edit</span>`;
  const pct = k => (100 * k / DATA.length).toFixed(2) + "%";
  document.getElementById("bar").innerHTML =
    `<i style="width:${pct(n.accept)};background:var(--ok)"></i>` +
    `<i style="width:${pct(n.reject)};background:var(--no)"></i>` +
    `<i style="width:${pct(n.edit)};background:var(--edit)"></i>`;
}

function decide(i, verdict) {
  const d = DATA[i];
  if (!verdict) { delete decisions[d.task_id]; } else { decisions[d.task_id] = { verdict }; }
  save();
  if (verdict && i === cursor && cursor < DATA.length - 1) cursor++;
  render();
  document.getElementById("c" + cursor)?.scrollIntoView({ block: "center", behavior: "smooth" });
}

function commands() {
  const lines = ["# Generated by fermdb query review --html. Run from the repo root.", ""];
  const reason = 'reviewed in the review page';
  let any = false;
  for (const d of DATA) {
    const v = decisions[d.task_id];
    if (!v) continue;
    any = true;
    if (v.verdict === "accept") {
      lines.push(`fermdb curate accept --task ${
  d.task_id} --curator ${CURATOR} --reason "${reason}"`);
    } else if (v.verdict === "reject") {
      lines.push(`fermdb curate reject --task ${
  d.task_id} --curator ${CURATOR} --reason "${reason}"`);
    } else {
      lines.push(`# EDIT NEEDED, no command generated: ${d.task_id} (${d.kind} ${d.path})`);
      lines.push(`#   correcting a record needs the corrected payload, so use the Python API`);
      lines.push(`#   fermdb.curate.edit(conn, "${
  d.task_id}", curator=..., reason=..., edited_payload={...})`);
    }
  }
  if (!any) lines.push("# nothing decided yet");
  lines.push("", "# Then promote what can be promoted (dry run first):",
    `fermdb curate promote --curator ${CURATOR} --organism YAA:ORG:saccharomyces-cerevisiae-s288c --dry-run`);
  document.getElementById("out").textContent = lines.join("\\n");
  document.getElementById("dlg").showModal();
}

document.addEventListener("click", e => {
  const b = e.target.closest("button[data-i]");
  if (b) { decide(+b.dataset.i, b.dataset.v); return; }
  if (e.target.id === "cmds") commands();
  if (e.target.id === "close") document.getElementById("dlg").close();
  if (e.target.id === "copy") {
    navigator.clipboard?.writeText(document.getElementById("out").textContent);
    e.target.textContent = "Copied";
    setTimeout(() => { e.target.textContent = "Copy"; }, 1200);
  }
  if (e.target.id === "reset" &&
      confirm("Clear every decision recorded in this browser? The atlas is untouched either way.")) {
    decisions = {}; save(); render();
  }
});

document.addEventListener("keydown", e => {
  if (e.target.matches("input,textarea") || document.getElementById("dlg").open) {
    if (e.key === "Escape") document.getElementById("dlg").close();
    return;
  }
  const k = e.key.toLowerCase();
  if (k === "j" || k === "arrowdown") { cursor = Math.min(cursor + 1, DATA.length - 1); render(); }
  else if (k === "k" || k === "arrowup") { cursor = Math.max(cursor - 1, 0); render(); }
  else if (k === "a") decide(cursor, "accept");
  else if (k === "r") decide(cursor, "reject");
  else if (k === "e") decide(cursor, "edit");
  else if (k === "u") decide(cursor, "");
  else if (k === "c") { commands(); return; }
  else return;
  e.preventDefault();
  document.getElementById("c" + cursor)?.scrollIntoView({ block: "center" });
});

render();
</script></body></html>
"""


def build_review_page(
    conn: sqlite3.Connection,
    *,
    settings: Settings | None = None,
    curator: str = "curator",
    status: str = "pending",
    supplied: dict[str, Any] | None = None,
) -> str:
    """The whole review page as one HTML string, data embedded.

    Self-contained on purpose: it has to keep working with the database closed, on a laptop, on a
    plane. It is a snapshot of the queue at generation time — regenerate after promoting.
    """
    settings = settings or Settings.load()
    packets = packets_for_review(conn, settings=settings, status=status, supplied=supplied)
    data = _payload(packets, _titles(conn))
    return (
        _TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))
        .replace("__CURATOR__", json.dumps(curator))
        .replace("__COUNT__", html.escape(str(len(data))))
    )
