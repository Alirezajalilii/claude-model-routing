"""Pure data functions behind the README charts: no I/O, no drawing.

Every number a chart shows comes from one of these functions, which read the rows of
docs/case-study/*.json and docs/cost/*.json that the caller loaded. render_charts.py draws
the results and owns the file access.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from typing import Dict, List, Mapping, Sequence, Tuple

import cost_estimate

ALL_SESSIONS = "All sessions"
HAIKU_HEAVY = "Haiku-heavy sessions"
REPO_RUN = "One logged run on this repository (15 tasks)"
ROLES = ("scout", "plan", "exec", "verify")
FAMILIES = ("haiku", "sonnet", "opus")
CONTEXT_ROLES = ("scout", "exec", "verify", "plan")
MAIN_LABEL = "main"
PROJECT_LABELS = tuple("P%02d" % number for number in range(1, 12))
HALF = 0.5


def half_up(value: float) -> int:
    """Round to an int, halves up (Python's round() goes to even)."""
    return int(math.floor(value + HALF))


def tier_rows(rows: Sequence[Mapping]) -> List[Mapping]:
    """Rows of the plugin's own tier agents (`mr:<role>-<model>-<effort>`)."""
    return [row for row in rows if str(row.get("agent_type", "")).startswith("mr:")]


def role_of(row: Mapping) -> str:
    return cost_estimate.group_of(str(row.get("agent_type", "")))


def family_of(row: Mapping) -> str:
    """Model family named in the agent type: `mr:exec-haiku-high` gives `haiku`."""
    name = str(row["agent_type"]).rsplit(":", 1)[-1]
    return name.split("-")[1]


def _count(row: Mapping) -> int:
    return row.get("agent_count", 1)


def _share(rows: Sequence[Mapping], family: str) -> float:
    total = sum(_count(row) for row in rows)
    return sum(_count(row) for row in rows if family_of(row) == family) / total


def _segment_of(rows: Sequence[Mapping]) -> str:
    execs = [row for row in rows if role_of(row) == "exec"]
    scouts = [row for row in rows if role_of(row) == "scout"]
    if not execs:
        return "none"
    if _share(execs, "sonnet") > HALF:
        return "B"
    if _share(execs, "haiku") > HALF and (not scouts or _share(scouts, "haiku") > HALF):
        return "A"
    return "C"


def session_segments(rows: Sequence[Mapping]) -> Dict[str, str]:
    """Segment of every session: A Haiku-heavy, B Sonnet-heavy, C other, `none` without executors.

    A: Haiku is above 50% of the executors by agent count and above 50% of the scouts (or there
    are no scouts). B: Sonnet is above 50% of the executors. Shares use the model in the agent type.
    """
    by_session: Dict[str, List[Mapping]] = {row["session"]: [] for row in rows}
    for row in tier_rows(rows):
        by_session[row["session"]].append(row)
    return {session: _segment_of(by_session[session]) for session in sorted(by_session)}


def _scenario(name: str, rows: Sequence[Mapping]) -> Tuple[str, float, float, float]:
    total = cost_estimate.estimate(list(rows), "5m")["total"]
    return (name, total["actual"], total["sonnet"], total["opus"])


def cost_scenarios(
    usage_rows: Sequence[Mapping], repo_rows: Sequence[Mapping]
) -> List[Tuple[str, float, float, float]]:
    """Three `(name, routed, all_sonnet, all_opus)` USD rows at list prices, 5-minute cache writes."""
    tier = tier_rows(usage_rows)
    segments = session_segments(usage_rows)
    haiku_heavy = [row for row in tier if segments[row["session"]] == "A"]
    return [
        _scenario(ALL_SESSIONS, tier),
        _scenario(HAIKU_HEAVY, haiku_heavy),
        _scenario(REPO_RUN, repo_rows),
    ]


def model_mix(rows: Sequence[Mapping]) -> Dict[str, Dict[str, int]]:
    """Agents per role and model family (by the agent type), families with no agents left out."""
    mix: Dict[str, Dict[str, int]] = {role: {} for role in ROLES}
    for row in tier_rows(rows):
        role, family = role_of(row), family_of(row)
        if role in mix:
            mix[role][family] = mix[role].get(family, 0) + _count(row)
    return {
        role: {family: mix[role][family] for family in FAMILIES if family in mix[role]}
        for role in ROLES
    }


def context_medians(peaks: Mapping) -> List[Tuple[str, int]]:
    """Median peak prompt tokens as `(label, median)` for scout, exec, verify, plan and main."""
    by_role: Dict[str, List[int]] = defaultdict(list)
    for role, _family, peak in peaks["agents"]:
        by_role[role].append(peak)
    medians = [(role, half_up(statistics.median(by_role[role]))) for role in CONTEXT_ROLES]
    medians.append((MAIN_LABEL, half_up(statistics.median(peaks["main"]))))
    return medians


def _saving_pct(routed: float, baseline: float) -> float:
    return round((baseline - routed) / baseline * 100, 1) + 0.0


def project_savings(rows: Sequence[Mapping]) -> List[Tuple[str, float, float]]:
    """`(label, saving vs all-Opus %, saving vs all-Sonnet %)` for P01 to P11, one decimal."""
    result = []
    tier = tier_rows(rows)
    for label in PROJECT_LABELS:
        total = cost_estimate.estimate([row for row in tier if row["label"] == label])["total"]
        result.append(
            (
                label,
                _saving_pct(total["actual"], total["opus"]),
                _saving_pct(total["actual"], total["sonnet"]),
            )
        )
    return result
