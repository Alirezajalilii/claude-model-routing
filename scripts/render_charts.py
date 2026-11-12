#!/usr/bin/env python3
"""Draw the four README data charts as SVG files from the committed data.

`python3 scripts/render_charts.py` writes docs/assets/chart-cost.svg, chart-model-mix.svg,
chart-context.svg and chart-projects.svg from docs/case-study/*.json and docs/cost/*.json.
`--check` writes nothing, prints `stale: <file>` for each committed chart that differs from
what the data produces, and exits 1; `make lint` runs it so a chart never drifts from its numbers.

The data functions live in chart_data.py (re-exported here). The render functions are pure and
return SVG text; main is the only function that reads or writes files. Each SVG draws its own
opaque background in the palette of docs/assets/hero.svg, so it reads the same on a light and a
dark page, and no text sits over a bar or another shape.

The charts are drawn phone first: a 640 wide viewBox shown at its native 640 px (GitHub shrinks it
to a phone column, about 0.63), text of 22 units and up, titles of 28, and every label on the line
above its bar, so nothing is beside a bar and nothing is smaller than about 14 px on a phone.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Mapping, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

from chart_data import (  # noqa: F401  (re-exported: the data functions are part of this module's API)
    FAMILIES, ROLES, context_medians, cost_scenarios, half_up, model_mix, project_savings,
    session_segments,
)

WIDTH = 640
MARGIN = 40
RIGHT = WIDTH - MARGIN
BAR_SCALE = 560
PROJECT_SCALE = 360
ZERO_X = 200
TITLE_SIZE = 28
TEXT_SIZE = 22
TITLE_LEAD = 38
TEXT_LEAD = 30
SUBTITLE_GAP = 40
WRAP_FACTOR = 0.62
BAR_H = 24
BAR_GAP = 10
ROW_PITCH = 64
HEAD_TO_BAR = 38
BOTTOM = 24
CAPTION = (
    "Each group is drawn against its own all-Opus cost. "
    "Values are subagent spend at list prices."
)
PROJECTS_CAPTION = "Savings are subagent spend at list prices. Bars left of the line cost more."
FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"

BG = "#0f172a"
INK = "#f8fafc"
SOFT = "#cbd5e1"
MUTED = "#94a3b8"
RULE = "#1e293b"
AMBER, AMBER_TEXT = "#f59e0b", "#fbbf24"
BLUE, BLUE_TEXT = "#60a5fa", "#93c5fd"
VIOLET, VIOLET_TEXT = "#a78bfa", "#c4b5fd"
GREEN, GREEN_TEXT = "#34d399", "#6ee7b7"
ROSE, ROSE_TEXT = "#fb7185", "#fda4af"

FAMILY_FILL = {"haiku": GREEN, "sonnet": BLUE, "opus": VIOLET}
FAMILY_NAME = {"haiku": "Haiku", "sonnet": "Sonnet", "opus": "Opus"}
ROLE_NAME = {"scout": "Scout", "plan": "Plan", "exec": "Exec", "verify": "Verify", "main": "Main session"}
CHART_FILES = {
    "cost": "chart-cost.svg",
    "model_mix": "chart-model-mix.svg",
    "context": "chart-context.svg",
    "projects": "chart-projects.svg",
}
ASSETS_DIR = ("docs", "assets")
USAGE_FILE = ("docs", "case-study", "cross-project-usage.json")
PEAKS_FILE = ("docs", "case-study", "context-peaks.json")
REPO_RUN_FILE = ("docs", "cost", "2026-11-11-run.json")


# --- SVG building blocks ---------------------------------------------------------------------

def money(value: float) -> str:
    return f"${value:,.2f}"


def percent(value: float) -> str:
    """One decimal and a percent sign; ASCII minus, never `-0.0%`."""
    return f"{value + 0.0:.1f}%"


def _text(x: int, y: int, size: int, fill: str, content: str, weight: str = "",
          anchor: str = "") -> str:
    extra = (f' font-weight="{weight}"' if weight else "") + (f' text-anchor="{anchor}"' if anchor else "")
    return f'<text x="{x}" y="{y}" font-size="{size}"{extra} fill="{fill}">{escape(content)}</text>'


def _rect(x: int, y: int, width: int, height: int, fill: str, rect_id: str = "",
          rx: int = 4, stroke: str = "") -> str:
    ident = f' id="{rect_id}"' if rect_id else ""
    outline = f' stroke="{stroke}" stroke-width="1"' if stroke else ""
    return (f'<rect{ident} x="{x}" y="{y}" width="{width}" height="{height}" '
            f'rx="{rx}" fill="{fill}"{outline}/>')


def _wrap(content: str, size: int, width: int = BAR_SCALE) -> List[str]:
    """Greedy word wrap; a line's estimated width (0.62 of the size per character) stays within width."""
    limit = int(width / (size * WRAP_FACTOR))
    lines: List[str] = []
    for word in content.split():
        if lines and len(lines[-1]) + 1 + len(word) <= limit:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines


def _stack(lines: Sequence[str], y: int, size: int, lead: int, fill: str,
           weight: str = "") -> Tuple[List[str], int]:
    """Left-aligned lines from baseline y down; returns the elements and the last baseline."""
    items = [_text(MARGIN, y + index * lead, size, fill, line, weight=weight) for index, line in enumerate(lines)]
    return items, y + (len(lines) - 1) * lead


def _heading(title: str, subtitle: str) -> Tuple[List[str], int]:
    """Title (28) and a wrapped subtitle (22); returns the elements and the last baseline."""
    items, last = _stack(_wrap(title, TITLE_SIZE), 48, TITLE_SIZE, TITLE_LEAD, INK, weight="800")
    more, last = _stack(_wrap(subtitle, TEXT_SIZE), last + SUBTITLE_GAP, TEXT_SIZE, TEXT_LEAD, MUTED)
    return items + more, last


def _legend(items: Sequence[Tuple[str, str]], y: int) -> List[str]:
    """Swatch and label pairs in one row; the label sits to the right of its swatch."""
    lines, left = [], MARGIN
    for fill, label in items:
        lines.append(_rect(left, y - 18, 18, 18, fill, rx=3))
        lines.append(_text(left + 26, y, TEXT_SIZE, SOFT, label))
        left += 26 + int(len(label) * TEXT_SIZE * WRAP_FACTOR) + 28
    return lines


def _bar_row(label: str, value: str, fill: str, ink: str, width: int, rect_id: str, y: int,
             label_ink: str = SOFT, label_weight: str = "") -> List[str]:
    """Name left and value right on baseline y; the bar from x 40 sits just under that line."""
    return [
        _text(MARGIN, y, TEXT_SIZE, label_ink, label, weight=label_weight),
        _text(RIGHT, y, TEXT_SIZE, ink, value, weight="700", anchor="end"),
        _rect(MARGIN, y + BAR_GAP, width, BAR_H, fill, rect_id),
    ]


def _svg(height: int, title: str, desc: str, body: Sequence[str]) -> str:
    head = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" '
        f'width="{WIDTH}" height="{height}" role="img" aria-labelledby="chart-title chart-desc">',
        f'  <title id="chart-title">{escape(title)}</title>',
        f'  <desc id="chart-desc">{escape(desc)}</desc>',
        f'  {_rect(0, 0, WIDTH, height, BG, rect_id="bg", rx=18)}',
        f'  <g font-family="{FONT}">',
    ]
    return "\n".join(head + [f"    {line}" for line in body] + ["  </g>", "</svg>", ""])


# --- cost chart -------------------------------------------------------------------------------

GROUP_KEYS = ("all", "haiku", "repo")
COST_KINDS = (
    ("routed", "As routed", AMBER, AMBER_TEXT),
    ("sonnet", "All Sonnet 5.5", BLUE, BLUE_TEXT),
    ("opus", "All Opus 5.5", VIOLET, VIOLET_TEXT),
)


def _group_head(name: str, saving: str, rule_y: int) -> Tuple[List[str], int]:
    """Rule, then the group name (a trailing `(...)` wraps to a second line) and the saving on the last line."""
    head, _, tail = name.partition(" (")
    names = [head, "(" + tail] if tail else [head]
    first = rule_y + 40
    lines = [_rect(MARGIN, rule_y, WIDTH - 2 * MARGIN, 1, RULE, rx=0)]
    items, last = _stack(names, first, TEXT_SIZE, TEXT_LEAD, INK, weight="700")
    lines += items
    lines.append(_text(RIGHT, last, TEXT_SIZE, AMBER_TEXT, saving, weight="700", anchor="end"))
    return lines, last


def _cost_group(key: str, scenario: Tuple[str, float, float, float], end: int) -> Tuple[List[str], int, str]:
    name, routed, sonnet, opus = scenario
    values = (routed, sonnet, opus)
    saving = f"{half_up((sonnet - routed) / sonnet * 100)}% below all Sonnet"
    lines, y = _group_head(name, saving, end + 20)
    parts = []
    for index, ((kind, label, fill, ink), value) in enumerate(zip(COST_KINDS, values)):
        y += HEAD_TO_BAR if index == 0 else ROW_PITCH
        width = round(value / opus * BAR_SCALE)
        lines += _bar_row(label, money(value), fill, ink, width, f"cost-{key}-{kind}", y)
        parts.append(f"{label} {money(value)}")
    return lines, y + BAR_GAP + BAR_H, f"{name}: {', '.join(parts)}, {saving}."


def render_cost(scenarios: Sequence[Tuple[str, float, float, float]]) -> str:
    body, last = _heading("Routing beats all-Sonnet and all-Opus on cost", CAPTION)
    end, summaries = last + 6, []
    for key, scenario in zip(GROUP_KEYS, scenarios):
        lines, end, summary = _cost_group(key, scenario, end)
        body += lines
        summaries.append(summary)
    desc = "Horizontal bars in three groups. " + " ".join(summaries) + " " + CAPTION
    return _svg(end + BOTTOM, "Subagent cost as routed, at all Sonnet and at all Opus prices", desc, body)


# --- model mix chart --------------------------------------------------------------------------

MIX_BAR_H = 28
MIX_PITCH = 110


def _mix_segments(role: str, counts: Mapping[str, int], role_width: int, y: int) -> List[str]:
    families = list(counts)
    total = sum(counts.values())
    lines, x, used = [], MARGIN, 0
    for index, family in enumerate(families):
        last = index == len(families) - 1
        width = role_width - used if last else round(counts[family] / total * role_width)
        lines.append(_rect(x, y, width, MIX_BAR_H, FAMILY_FILL[family], f"mix-{role}-{family}", rx=0, stroke=BG))
        x, used = x + width, used + width
    return lines


def _mix_row(role: str, counts: Mapping[str, int], largest: int, y: int) -> Tuple[List[str], str]:
    """Role name and total on line y, the stacked bar under it, the per-model counts under the bar."""
    total = sum(counts.values())
    role_width = round(total / largest * BAR_SCALE)
    shown = ", ".join(f"{counts[f]} {FAMILY_NAME[f]}" for f in counts)
    per_model = ", ".join(f"{FAMILY_NAME[f]} {counts[f]}" for f in counts)
    lines = [
        _text(MARGIN, y, TEXT_SIZE, INK, ROLE_NAME[role], weight="700"),
        _text(RIGHT, y, TEXT_SIZE, SOFT, f"{total} agents", weight="700", anchor="end"),
    ]
    lines += _mix_segments(role, counts, role_width, y + BAR_GAP)
    lines.append(_text(MARGIN, y + BAR_GAP + MIX_BAR_H + TEXT_LEAD, TEXT_SIZE, SOFT, per_model))
    return lines, f"{ROLE_NAME[role]}: {shown}."


def render_model_mix(mix: Mapping[str, Mapping[str, int]]) -> str:
    title = "Haiku builds, Opus plans, Opus and Sonnet review"
    body, last = _heading(title, "Agents by role and model family.")
    legend_y = last + 44
    body += _legend([(FAMILY_FILL[f], FAMILY_NAME[f]) for f in FAMILIES], legend_y)
    largest = max(sum(counts.values()) for counts in mix.values())
    summaries, y = [], legend_y + 56
    for role in ROLES:
        lines, summary = _mix_row(role, mix[role], largest, y)
        body += lines
        summaries.append(summary)
        y += MIX_PITCH
    desc = ("One stacked horizontal bar per role, split by model family. "
            + " ".join(summaries) + " Segment colors: Haiku, Sonnet, Opus.")
    return _svg(y - MIX_PITCH + BAR_GAP + MIX_BAR_H + TEXT_LEAD + BOTTOM,
                "Agents by role and model family", desc, body)


# --- context chart ----------------------------------------------------------------------------

def _thousands(value: int) -> str:
    return f"{half_up(value / 1000)}K"


def render_context(medians: Sequence[Tuple[str, int]]) -> str:
    title = "Most agents work in far less context"
    subtitle = "Median peak prompt tokens per agent, by role, next to the main session."
    body, last = _heading(title, subtitle)
    top = max(value for _label, value in medians)
    summaries, y = [], last + 48
    for label, value in medians:
        main = label == "main"
        body += _bar_row(ROLE_NAME[label], _thousands(value), VIOLET if main else AMBER,
                         VIOLET_TEXT if main else AMBER_TEXT, round(value / top * BAR_SCALE),
                         f"ctx-{label}", y, label_ink=INK, label_weight="700")
        summaries.append(f"{ROLE_NAME[label]} {_thousands(value)}")
        y += ROW_PITCH
    desc = ("Horizontal bars of median peak prompt tokens, in thousands: "
            + ", ".join(summaries) + ".")
    return _svg(y - ROW_PITCH + BAR_GAP + BAR_H + BOTTOM, "Median peak context by role", desc, body)


# --- projects chart ---------------------------------------------------------------------------

PROJECT_PITCH = 84
PROJECT_BAR_H = 22
PROJECT_NOTE_GAP = 8


def _bar_length(pct: float) -> int:
    return round(abs(pct) / 100 * PROJECT_SCALE)


def _project_bar(label: str, kind: str, pct: float, y: int) -> List[str]:
    """One bar from the zero line (right for a saving, left for a cost); its value sits 8 past the outer end."""
    length = _bar_length(pct)
    fill = ROSE if pct < 0 else (VIOLET if kind == "opus" else BLUE)
    ink = ROSE_TEXT if pct < 0 else (VIOLET_TEXT if kind == "opus" else BLUE_TEXT)
    x = ZERO_X - length if pct < 0 else ZERO_X
    if pct < 0:
        note = _text(x - PROJECT_NOTE_GAP, y + 19, TEXT_SIZE, ink, percent(pct), anchor="end")
    else:
        note = _text(x + length + PROJECT_NOTE_GAP, y + 19, TEXT_SIZE, ink, percent(pct))
    return [_rect(x, y, length, PROJECT_BAR_H, fill, f"proj-{label}-{kind}", rx=0), note]


def _callouts(rows: Sequence[Tuple[str, float, float]], y: int) -> Tuple[List[str], List[str], int]:
    best = max(rows, key=lambda row: row[1])
    least = min(rows, key=lambda row: row[1])
    lowest = min(rows, key=lambda row: row[2])
    items = [
        (percent(best[1]), f"most saved against all-Opus ({best[0]})", AMBER_TEXT),
        (percent(least[1]), f"least saved against all-Opus ({least[0]})", VIOLET_TEXT),
        (percent(lowest[2]), f"lowest against all-Sonnet ({lowest[0]})", ROSE_TEXT),
    ]
    lines, notes = [], []
    for index, (big, small, ink) in enumerate(items):
        lines.append(_text(MARGIN, y + index * TEXT_LEAD, TEXT_SIZE, ink, f"{big} {small}"))
        notes.append(f"{big} {small}")
    return lines, notes, y + (len(items) - 1) * TEXT_LEAD


def render_projects(rows: Sequence[Tuple[str, float, float]]) -> str:
    title = "Cheaper than all-Opus on every project"
    body, last = _heading(title, PROJECTS_CAPTION)
    callouts, notes, last = _callouts(rows, last + 44)
    body += callouts
    swatches = [(VIOLET, "Against all-Opus"), (BLUE, "Against all-Sonnet")]
    body += _legend(swatches, last + 48)
    top = last + 48 + 36
    summaries, bars = [], []
    for index, (label, opus, sonnet) in enumerate(rows):
        y = top + index * PROJECT_PITCH
        bars.append(_text(MARGIN, y, TEXT_SIZE, INK, label, weight="700"))
        bars += _project_bar(label, "opus", opus, y + 6)
        bars += _project_bar(label, "sonnet", sonnet, y + 6 + PROJECT_BAR_H + 4)
        summaries.append(f"{label} {percent(opus)} against all-Opus, {percent(sonnet)} against all-Sonnet.")
    bottom = top + (len(rows) - 1) * PROJECT_PITCH + 6 + 2 * PROJECT_BAR_H + 4
    body.append(f'<line x1="{ZERO_X}" y1="{top - 2}" x2="{ZERO_X}" y2="{bottom + 4}" '
                f'stroke="{MUTED}" stroke-width="2"/>')
    body += bars
    desc = ("Saving per project, two bars each, drawn from a zero line; a bar left of the line costs "
            "more than that baseline. " + " ".join(summaries) + " " + " ".join(f"{n}." for n in notes)
            + " " + PROJECTS_CAPTION)
    return _svg(bottom + BOTTOM, "Saving per project against all-Opus and all-Sonnet", desc, body)


# --- files and command line -------------------------------------------------------------------

def render_all(root: Path) -> dict:
    """File name to SVG text for the four charts, from the data under root."""
    usage = json.loads(root.joinpath(*USAGE_FILE).read_text(encoding="utf-8"))
    peaks = json.loads(root.joinpath(*PEAKS_FILE).read_text(encoding="utf-8"))
    repo = json.loads(root.joinpath(*REPO_RUN_FILE).read_text(encoding="utf-8"))
    return {
        CHART_FILES["cost"]: render_cost(cost_scenarios(usage, repo)),
        CHART_FILES["model_mix"]: render_model_mix(model_mix(usage)),
        CHART_FILES["context"]: render_context(context_medians(peaks)),
        CHART_FILES["projects"]: render_projects(project_savings(usage)),
    }


def _stale(root: Path, charts: Mapping[str, str]) -> List[str]:
    stale = []
    for name, svg in charts.items():
        path = root.joinpath(*ASSETS_DIR, name)
        committed = path.read_bytes() if path.is_file() else None
        if committed != svg.encode("utf-8"):
            stale.append(name)
    return stale


def main(argv: Optional[List[str]] = None) -> int:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        prog="render_charts",
        description="Write the README data charts to docs/assets/chart-*.svg, or check them.",
    )
    parser.add_argument("--root", type=Path, default=default_root, help="repository root (default: this repository)")
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 if a committed chart is stale")
    args = parser.parse_args(argv)
    charts = render_all(args.root)
    if args.check:
        stale = _stale(args.root, charts)
        for name in stale:
            print(f"stale: {name}")
        return 1 if stale else 0
    target = args.root.joinpath(*ASSETS_DIR)
    target.mkdir(parents=True, exist_ok=True)
    for name, svg in charts.items():
        with open(target / name, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(svg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
