"""HTML rendering (extracted from build_report.py)."""
from __future__ import annotations

from datetime import date
from html import escape as _escape

from sprint_pulse.config import Config
from sprint_pulse.sprints import Sprint, TimeOffEntry, working_days


def esc(value: object) -> str:
    """HTML-escape a value for safe interpolation (text and attributes).

    The dashboard is hand-built HTML (no Jinja autoescape), and member names,
    time-off notes, and event titles are user-entered — so every dynamic value
    must pass through here to prevent markup corruption / stored XSS.
    """
    return _escape(str(value), quote=True)


def team_display(cfg: Config, sprint: Sprint) -> str:
    """The sprint's display/Jira name, e.g. 'Wisdom 2026-16'."""
    return f"{cfg.team_name} {sprint.id}"


CSS = """:root {
  --bg: #f7f8fa;
  --card: #ffffff;
  --border: #e5e7eb;
  --text: #111827;
  --muted: #6b7280;
  --pto: #fca5a5;
  --pto-text: #7f1d1d;
  --holiday: #93c5fd;
  --holiday-text: #1e3a8a;
  --partial: #fcd34d;
  --partial-text: #78350f;
  --tentative: repeating-linear-gradient(45deg, #fde68a, #fde68a 4px, #fef3c7 4px, #fef3c7 8px);
  --tentative-text: #78350f;
  --company: #c4b5fd;
  --company-text: #4c1d95;
}
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  background: var(--bg); color: var(--text); margin: 0; padding: 32px 24px; line-height: 1.45; }
h1 { margin: 0 0 4px; font-size: 24px; }
.subtitle { color: var(--muted); margin: 0 0 24px; font-size: 14px; }
.legend { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; padding: 12px 16px;
  background: var(--card); border: 1px solid var(--border); border-radius: 8px; font-size: 13px; }
.legend-item { display: flex; align-items: center; gap: 6px; }
.swatch { width: 18px; height: 18px; border-radius: 4px; border: 1px solid var(--border); }
.swatch.pto { background: var(--pto); }
.swatch.holiday { background: var(--holiday); }
.swatch.partial { background: var(--partial); }
.swatch.tentative { background: var(--tentative); }
.swatch.company { background: var(--company); }
.swatch.external { background: #e5e7eb; }
.swatch.tags { background: #1d4ed8; }
.swatch.gono { background: #b45309; }
.swatch.ga { background: #047857; }
.swatch.freeze { background: #6b7280; }
.swatch.test { background: #7c3aed; }
.legend-group { display: flex; gap: 14px; flex-wrap: wrap; align-items: center; }
.legend-group .group-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
  color: var(--muted); font-weight: 600; margin-right: 4px; }
.legend-divider { width: 1px; height: 24px; background: var(--border); }
section.sprint { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
  padding: 16px 20px; margin-bottom: 20px; overflow-x: auto; }
.sprint-header { display: flex; flex-direction: column; margin-bottom: 12px; }
.sprint-title { display: flex; justify-content: space-between; align-items: baseline; gap: 12px;
  flex-wrap: wrap; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
.sprint-title h2 { margin: 0; font-size: 18px; }
.sprint-title .dates { color: var(--muted); font-size: 14px; font-weight: 500; }
.sprint-info { display: flex; justify-content: space-between; gap: 24px; padding-top: 10px; flex-wrap: wrap; }
.sprint-info ul { margin: 0; padding-left: 20px; font-size: 13px; color: var(--muted); }
.sprint-info ul li { margin: 2px 0; }
.sprint-info ul li strong { color: var(--text); font-weight: 700; }
.sprint-info .tbd { color: #9ca3af; font-style: italic; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { border: 1px solid var(--border); padding: 6px 8px; text-align: center; min-width: 44px; }
th.name, td.name { text-align: left; min-width: 220px; white-space: nowrap; font-weight: 500; }
thead th { background: #f9fafb; font-weight: 600; font-size: 12px; color: var(--muted); }
thead th .dow { display: block; font-size: 10px; font-weight: 500; color: #9ca3af;
  text-transform: uppercase; letter-spacing: 0.5px; }
tfoot td { background: #f9fafb; font-weight: 600; }
tfoot td.zero { color: #d1d5db; }
tfoot td.peak { background: #fef3c7; color: #92400e; }
td.cell { font-weight: 600; font-size: 11px; }
td.pto { background: var(--pto); color: var(--pto-text); }
td.holiday { background: var(--holiday); color: var(--holiday-text); }
td.partial { background: var(--partial); color: var(--partial-text); }
td.tentative { background: var(--tentative); color: var(--tentative-text); }
td.company { background: var(--company); color: var(--company-text); }
td.external { background: #e5e7eb; }
tr.external-row td.name { color: var(--muted); font-style: italic; }
.orch { color: #9ca3af; font-size: 11px; font-weight: 400; margin-left: 4px; }
td.release { background: #1f2937; color: #f9fafb; font-weight: 700; font-size: 11px; }
td.release.ga { background: #047857; }
td.release.tags { background: #1d4ed8; }
td.release.gono { background: #b45309; }
td.release.freeze { background: #6b7280; }
td.release.test { background: #7c3aed; }
tr.release-row td.name { font-style: italic; color: var(--muted); font-size: 12px; background: #f9fafb; }
tr.release-row td { border-bottom: 2px solid var(--border); }
td.total { font-weight: 700; background: #f9fafb; }
td.total.zero { color: #d1d5db; font-weight: 400; }
.summary { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px 20px; }
.summary h2 { margin: 0 0 12px; font-size: 18px; }
.summary table { max-width: 620px; }

body { padding: 0; margin: 0; }
.layout { display: grid; grid-template-columns: 280px 1fr; min-height: 100vh; }
.sidebar { background: var(--card); border-right: 1px solid var(--border);
  padding: 24px 20px; position: sticky; top: 0; height: 100vh; overflow-y: auto; }
.sidebar header h1 { font-size: 18px; margin: 0 0 4px; }
.sidebar header p { color: var(--muted); margin: 0 0 24px; font-size: 13px; }
.sidebar h2.section-label { font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
  color: var(--muted); font-weight: 600; margin: 20px 0 8px; }
.sprint-nav ul { list-style: none; padding: 0; margin: 0; }
.sprint-nav li { margin: 2px 0; }
.sprint-nav button { display: flex; flex-direction: column; align-items: flex-start; gap: 2px;
  width: 100%; text-align: left; padding: 10px 12px; background: transparent;
  border: 1px solid transparent; border-radius: 6px; cursor: pointer; font-family: inherit;
  font-size: 13px; color: var(--text); }
.sprint-nav button:hover { background: #f3f4f6; }
.sprint-nav button.active { background: #eff6ff; border-color: #93c5fd; color: #1e3a8a; }
.sprint-nav .nav-name { font-weight: 600; }
.sprint-nav .nav-dates { font-size: 11px; color: var(--muted); }
.sprint-nav button.active .nav-dates { color: #1d4ed8; }
.nav-state { font-size: 10px; padding: 1px 6px; border-radius: 3px; text-transform: uppercase;
  letter-spacing: 0.5px; font-weight: 600; margin-top: 2px; }
.nav-state.active { background: #d1fae5; color: #065f46; }
.nav-state.future { background: #e0e7ff; color: #3730a3; }
.nav-state.closed { background: #f3f4f6; color: #6b7280; }
.summary-link { display: block; padding: 10px 12px; margin-top: 12px;
  color: var(--muted); font-size: 13px; cursor: pointer; background: transparent;
  border: 1px solid transparent; border-radius: 6px; width: 100%; text-align: left;
  font-family: inherit; }
.summary-link.active { color: #1e3a8a; background: #eff6ff; border-color: #93c5fd; }
.summary-link:hover { background: #f3f4f6; }
.sidebar .legend { margin: 8px 0 0; padding: 12px 14px; flex-direction: column; gap: 12px;
  font-size: 12px; }
.sidebar .legend-group { flex-direction: column; align-items: flex-start; gap: 4px; }
.sidebar .legend-divider { display: none; }
main { padding: 32px 32px 64px; overflow-x: auto; max-width: 100%; }
main > h1 { font-size: 22px; margin: 0 0 4px; }
main > .subtitle { margin: 0 0 24px; font-size: 13px; color: var(--muted); }
section.sprint { margin-bottom: 0; }"""


LEGEND = """<div class="legend">
  <div class="legend-group">
    <span class="group-label">Time off</span>
    <div class="legend-item"><div class="swatch pto"></div> P — PTO</div>
    <div class="legend-item"><div class="swatch holiday"></div> H — Regional / National holiday</div>
    <div class="legend-item"><div class="swatch company"></div> C — Company holiday</div>
    <div class="legend-item"><div class="swatch partial"></div> ~ — Partial availability</div>
    <div class="legend-item"><div class="swatch tentative"></div> ? — Tentative</div>
    <div class="legend-item"><div class="swatch external"></div> On Orchestration (not counted)</div>
  </div>
  <div class="legend-divider"></div>
  <div class="legend-group">
    <span class="group-label">AAP release</span>
    <div class="legend-item"><div class="swatch tags"></div> T — Git tags due</div>
    <div class="legend-item"><div class="swatch gono"></div> G — Go/No-Go</div>
    <div class="legend-item"><div class="swatch ga"></div> R — Target release</div>
    <div class="legend-item"><div class="swatch freeze"></div> F — Release freeze</div>
    <div class="legend-item"><div class="swatch test"></div> X — Testathon</div>
  </div>
</div>"""


DOW_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
TYPE_LETTERS = {"pto": "P", "holiday": "H", "company": "C", "partial": "~", "tentative": "?"}
TYPE_TITLES = {
    "pto": "PTO", "holiday": "Holiday", "company": "Company holiday",
    "partial": "Partially available", "tentative": "Tentative",
}
KIND_LETTERS = {"tags": "T", "gono": "G", "ga": "R", "freeze": "F", "test": "X"}
MONTH_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


def fmt_date(d: date) -> str:
    return f"{MONTH_ABBR[d.month]} {d.day}"


def derive_sprint_notes(sprint: Sprint) -> list[str]:
    return [f"{e.title} — {fmt_date(e.date)}" for e in sprint.events]


def _render_cell(person: str, d: date, by_person: dict, cfg: Config) -> tuple[str, int]:
    if person in cfg.orchestration:
        entries = by_person.get(person, {}).get(d, [])
        if entries:
            e = entries[0]
            cls = e.type
            letter = TYPE_LETTERS.get(cls, "?")
            title = e.notes or TYPE_TITLES[cls]
            return f'<td class="cell {cls}" title="{esc(title)}">{letter}</td>', 0
        return '<td class="external" title="On Orchestration"></td>', 0
    entries = by_person.get(person, {}).get(d, [])
    if not entries:
        return "<td></td>", 0
    e = entries[0]
    cls = e.type
    letter = TYPE_LETTERS.get(cls, "?")
    title = e.notes or TYPE_TITLES[cls]
    return f'<td class="cell {cls}" title="{esc(title)}">{letter}</td>', 1


def render_sprint(
    sprint: Sprint,
    cfg: Config,
    metrics: dict,
    state: str,
) -> tuple[str, dict[str, int]]:
    days = working_days(sprint.start, sprint.end)
    day_index = {d: i for i, d in enumerate(days)}

    by_person: dict[str, dict[date, list[TimeOffEntry]]] = {}
    for e in sprint.time_off:
        bp = by_person.setdefault(e.associate, {})
        for d in e.days:
            if sprint.start <= d <= sprint.end:
                bp.setdefault(d, []).append(e)

    days_out_by_person = {p: 0 for p in cfg.roster}
    rows_html: list[str] = []

    rel_cells = ["<td></td>"] * len(days)
    for ev in sprint.events:
        col = day_index.get(ev.date)
        if col is None:
            continue
        sub = ev.kind
        letter = KIND_LETTERS[ev.kind]
        rel_cells[col] = f'<td class="release {sub}" title="{esc(ev.title)}">{letter}</td>'
    rows_html.append(
        '<tr class="release-row"><td class="name">AAP release</td>'
        + "".join(rel_cells)
        + '<td>—</td></tr>'
    )

    day_totals = [0] * len(days)
    for person in cfg.roster:
        person_total = 0
        cells_html: list[str] = []
        for i, d in enumerate(days):
            cell_html, contrib = _render_cell(person, d, by_person, cfg)
            cells_html.append(cell_html)
            if person not in cfg.orchestration:
                person_total += contrib
                day_totals[i] += contrib
        days_out_by_person[person] = person_total
        if person in cfg.orchestration:
            total_cell = '<td class="total zero">0</td>'
        elif person_total == 0:
            total_cell = '<td class="total zero">0</td>'
        else:
            total_cell = f'<td class="total">{person_total}</td>'
        rows_html.append(
            f'<tr><td class="name">{esc(person)}</td>'
            + "".join(cells_html)
            + total_cell + "</tr>"
        )

    sprint_total = sum(day_totals)

    thead = '<tr><th class="name">Associate</th>'
    for d in days:
        thead += f'<th>{d.day}<span class="dow">{DOW_NAMES[d.weekday()]}</span></th>'
    thead += '<th>Total</th></tr>'

    peak_threshold = max(day_totals) if day_totals else 0
    tfoot_cells: list[str] = []
    for n in day_totals:
        if n == 0:
            tfoot_cells.append('<td class="zero">0</td>')
        elif n == peak_threshold and n >= max(2, peak_threshold):
            tfoot_cells.append(f'<td class="peak">{n}</td>')
        else:
            tfoot_cells.append(f'<td>{n}</td>')
    tfoot = (
        '<tr><td class="name">Day total</td>'
        + "".join(tfoot_cells)
        + f'<td>{sprint_total}</td></tr>'
    )

    # Capacity is 0 when there are no effective members yet (e.g. sprints
    # imported before the team is added) — show availability as n/a, don't divide.
    if cfg.capacity:
        avail_str = f"{(cfg.capacity - sprint_total) / cfg.capacity * 100:.1f}%"
    else:
        avail_str = "n/a"
    state_annot = ""
    if state == "active":
        state_annot = ' <span class="tbd">(active)</span>'
    elif state == "future":
        state_annot = ' <span class="tbd">(future)</span>'

    metrics_li = [
        f'<li><strong>{avail_str}</strong> availability</li>',
        f'<li>Jira tickets: <strong>{metrics["done_n"]}</strong> done / '
        f'<strong>{metrics["tot_n"]}</strong> total{state_annot}</li>',
        f'<li>Story points: <strong>{metrics["done_sp"]}</strong> done / '
        f'<strong>{metrics["tot_sp"]}</strong> total{state_annot}</li>',
    ]
    events_li = "".join(f"<li>{esc(n)}</li>" for n in derive_sprint_notes(sprint))

    info_html = (
        '<div class="sprint-info">'
        f'<ul class="metrics">{"".join(metrics_li)}</ul>'
        f'<ul class="events">{events_li}</ul>'
        '</div>'
    )

    date_range = (
        f"{fmt_date(sprint.start)} – {fmt_date(sprint.end)}"
        if sprint.start.month == sprint.end.month
        else f"{fmt_date(sprint.start)} – {fmt_date(sprint.end)}"
    )

    html = f"""<section class="sprint">
  <div class="sprint-header">
    <div class="sprint-title">
      <h2>{esc(team_display(cfg, sprint))}</h2>
      <span class="dates">{date_range}</span>
    </div>
    {info_html}
  </div>
  <table>
    <thead>{thead}</thead>
    <tbody>{''.join(rows_html)}</tbody>
    <tfoot>{tfoot}</tfoot>
  </table>
</section>"""
    return html, days_out_by_person


def render_summary(
    cfg: Config,
    per_sprint_days_out: list[dict[str, int]],
    sprint_ids: list[str],
) -> str:
    person_totals = {p: 0 for p in cfg.roster}
    sprint_totals = [0] * len(sprint_ids)
    for p in cfg.roster:
        for i, dpo in enumerate(per_sprint_days_out):
            person_totals[p] += dpo.get(p, 0)
            sprint_totals[i] += dpo.get(p, 0)

    active = sorted(
        (p for p in cfg.roster if p not in cfg.orchestration),
        key=lambda p: -person_totals[p],
    )
    orch = [p for p in cfg.roster if p in cfg.orchestration]

    rows: list[str] = []
    for p in active + orch:
        is_orch = p in cfg.orchestration
        cells: list[str] = []
        for i, dpo in enumerate(per_sprint_days_out):
            n = 0 if is_orch else dpo.get(p, 0)
            cells.append('<td class="zero">0</td>' if n == 0 else f"<td>{n}</td>")
        total = 0 if is_orch else person_totals[p]
        total_cell = (
            '<td class="total zero">0</td>'
            if total == 0 else f'<td class="total">{total}</td>'
        )
        name_html = (
            f'{esc(p)} <span class="orch">(Orchestration)</span>' if is_orch else esc(p)
        )
        tr_class = ' class="external-row"' if is_orch else ""
        rows.append(
            f'<tr{tr_class}><td class="name">{name_html}</td>'
            + "".join(cells) + total_cell + "</tr>"
        )

    grand = sum(sprint_totals)
    peak = max(sprint_totals) if sprint_totals else 0
    foot_cells: list[str] = []
    for n in sprint_totals:
        cls = ' class="peak"' if n == peak and n > 0 else ""
        foot_cells.append(f"<td{cls}>{n}</td>")

    head_cells = "".join(f"<th>{esc(sid)}</th>" for sid in sprint_ids)

    return f"""<section class="summary">
  <h2>Per-Associate Total</h2>
  <table>
    <thead>
      <tr><th class="name">Associate</th>{head_cells}<th>Total</th></tr>
    </thead>
    <tbody>{''.join(rows)}</tbody>
    <tfoot>
      <tr><td class="name">Sprint total</td>{''.join(foot_cells)}<td>{grand}</td></tr>
    </tfoot>
  </table>
</section>"""


def render_full_html(
    sprints_with_data: list[tuple[Sprint, dict, str]],
    cfg: Config,
) -> str:
    """sprints_with_data: list of (sprint, jira_metrics, jira_state)."""
    sprints_asc = sorted(sprints_with_data, key=lambda t: (t[0].start, t[0].end, t[0].id))
    sprints_desc = list(reversed(sprints_asc))

    sprint_html_by_id: dict[str, str] = {}
    days_out_by_sprint: dict[str, dict[str, int]] = {}
    for sprint, metrics, state in sprints_asc:
        html, dpo = render_sprint(sprint, cfg, metrics, state)
        html = html.replace(
            '<section class="sprint">',
            f'<section class="sprint" data-sprint="{sprint.id}" hidden>',
            1,
        )
        sprint_html_by_id[sprint.id] = html
        days_out_by_sprint[sprint.id] = dpo

    sprint_sections = "\n".join(sprint_html_by_id[s.id] for s, _, _ in sprints_desc)

    summary_html = render_summary(
        cfg,
        [days_out_by_sprint[s.id] for s, _, _ in sprints_asc],
        [s.id for s, _, _ in sprints_asc],
    ).replace(
        '<section class="summary">',
        '<section class="summary" hidden>',
        1,
    )

    default_sid = next(
        (s.id for s, _, st in sprints_desc if st == "active"),
        sprints_desc[0][0].id,
    )

    nav_items: list[str] = []
    for sprint, _, state in sprints_desc:
        date_range = f"{fmt_date(sprint.start)} – {fmt_date(sprint.end)}"
        nav_items.append(
            f'<li><button data-sprint="{esc(sprint.id)}">'
            f'<span class="nav-name">{esc(team_display(cfg, sprint))}</span>'
            f'<span class="nav-dates">{date_range}</span>'
            f'<span class="nav-state {state}">{state}</span>'
            f'</button></li>'
        )
    nav_html = "\n".join(nav_items)

    title_year = sprints_asc[0][0].start.year
    title_range = (
        f"{fmt_date(sprints_asc[0][0].start)}"
        f" – {fmt_date(sprints_asc[-1][0].end)}"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{esc(cfg.team_name)} Team — Time Off ({title_range}, {title_year})</title>
<style>{CSS}</style>
</head>
<body>
<div class="layout">
  <aside class="sidebar">
    <header>
      <h1>{esc(cfg.team_name)} Team</h1>
      <p>Time Off Report</p>
    </header>
    <h2 class="section-label">Sprints</h2>
    <nav class="sprint-nav">
      <ul>
{nav_html}
      </ul>
      <button class="summary-link" data-sprint="__summary__">All sprints summary</button>
    </nav>
    <h2 class="section-label">Legend</h2>
    {LEGEND}
  </aside>
  <main>
    <h1>{esc(cfg.team_name)} Team — Time Off</h1>
    <p class="subtitle">{title_range}, {title_year}</p>
{sprint_sections}
    {summary_html}
  </main>
</div>
<script>
function show(target) {{
  document.querySelectorAll('main section').forEach(s => {{
    const isSummary = s.classList.contains('summary');
    if (target === '__summary__') s.hidden = !isSummary;
    else s.hidden = isSummary || s.dataset.sprint !== target;
  }});
  document.querySelectorAll('.sprint-nav button, .summary-link').forEach(b => {{
    b.classList.toggle('active', b.dataset.sprint === target);
  }});
}}
document.querySelectorAll('.sprint-nav button, .summary-link').forEach(b => {{
  b.addEventListener('click', () => show(b.dataset.sprint));
}});
show('{default_sid}');
</script>
</body>
</html>
"""
