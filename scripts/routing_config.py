"""Loader and validator for config/routing.json, the single source of truth."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "routing.json"
MODEL_FAMILIES = ("haiku", "sonnet", "opus", "fable")
TIER_FAMILIES = ("haiku", "sonnet", "opus")
EFFORTS = ("low", "medium", "high", "xhigh")
ROLES = ("scout", "planner", "executor", "verifier")
NESTING_TOOLS = ("Agent", "TeamCreate", "TeamDelete", "SendMessage")
REQUIRED_TOOLS = ("Read", "Write", "Skill")
BACKGROUND_TOOLS = ("Monitor", "TaskStop")

INT_TUNABLES = {
    "planner_evidence_budget": 1,
    "calibration_first_tasks": 1,
    "max_fix_rounds_per_tier": 1,
    "max_executor_escalations": 1,
    "max_evidence_rounds": 1,
    "skill_cap_haiku": 0,
    "skill_cap_other": 0,
    "haiku_prompt_flag_tokens": 1,
    "status_line_max_chars": 1,
}
RATE_TUNABLES = (
    "calibration_sample_rate",
    "calibration_low_defect_rate",
    "calibration_reduced_sample_rate",
    "calibration_high_defect_rate",
)
SLUG = re.compile(r"^[a-z0-9-]+$")
RESERVED_PLUGIN_PREFIXES = ("claude-", "anthropic-", "anthropics-", "cc-plugin-")
STALL_WATCH_INTS = {
    "repeat_window": 2,
    "repeat_limit": 2,
    "read_only_streak_limit": 1,
    "max_nudges": 0,
    "state_max_age_hours": 1,
}
STALL_WATCH_LISTS = ("change_tools", "handback_tools", "read_only_tools", "read_only_bash_prefixes")
STALL_WATCH_KEYS = ("enabled", "roles", "ignored_tools") + STALL_WATCH_LISTS + tuple(STALL_WATCH_INTS)


class ConfigError(Exception):
    """Raised when the routing configuration cannot be loaded or is invalid."""


@dataclass(frozen=True)
class Role:
    name: str
    prefix: str
    tools: tuple
    disallowed_tools: tuple
    uses_advisor: bool


@dataclass(frozen=True)
class Tier:
    name: str
    role: str
    model: str
    effort: str
    description: str
    family: str


@dataclass(frozen=True)
class DispatcherPart:
    title: str
    sections: tuple


@dataclass(frozen=True)
class StallWatch:
    enabled: bool
    roles: tuple
    ignored_tools: tuple
    change_tools: tuple
    handback_tools: tuple
    read_only_tools: tuple
    read_only_bash_prefixes: tuple
    repeat_window: int
    repeat_limit: int
    read_only_streak_limit: int
    max_nudges: int
    state_max_age_hours: int


@dataclass(frozen=True)
class RoutingConfig:
    plugin_name: str
    dispatcher_model_family: str
    dispatcher_effort: str
    tunables: Mapping
    roles: Mapping
    tiers: tuple
    extra_rules_by_model: Mapping
    audit_flag_every_use: tuple
    plan_path_pattern: str
    policy_sections: tuple
    dispatcher_parts: tuple
    agent_frontmatter: tuple = ()
    agent_frontmatter_by_model: Mapping = field(default_factory=dict)
    dispatch_allow_agents: tuple = ()
    dispatch_blocked_output_names: str = ""
    stall_watch: Optional[StallWatch] = None


def model_family(model: Optional[str]) -> Optional[str]:
    """Return the model family named inside a model alias or id, else None."""
    if not isinstance(model, str):
        return None
    lowered = model.lower()
    for family in MODEL_FAMILIES:
        if family in lowered:
            return family
    return None


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_tunables(tunables: Any) -> list:
    if not isinstance(tunables, dict):
        return ["tunables: must be an object"]
    errors = []
    for key, minimum in INT_TUNABLES.items():
        value = tunables.get(key)
        if key not in tunables:
            errors.append(f"tunables.{key}: missing")
        elif not _is_int(value) or value < minimum:
            errors.append(f"tunables.{key}: must be an integer >= {minimum}")
    for key in RATE_TUNABLES:
        value = tunables.get(key)
        if key not in tunables:
            errors.append(f"tunables.{key}: missing")
        elif not _is_number(value) or not 0 < value <= 1:
            errors.append(f"tunables.{key}: must be a number with 0 < rate <= 1")
    low = tunables.get("calibration_low_defect_rate")
    high = tunables.get("calibration_high_defect_rate")
    if _is_number(low) and _is_number(high) and not low < high:
        errors.append(
            "tunables.calibration_low_defect_rate: must be below "
            "calibration_high_defect_rate"
        )
    return errors


def _tool_list_errors(name: str, tools: list, disallowed: list) -> list:
    errors = []
    for tool in REQUIRED_TOOLS:
        if tool not in tools:
            errors.append(f"roles.{name}.tools: must contain {tool}")
    if "Bash" in tools:
        for tool in BACKGROUND_TOOLS:
            if tool not in tools:
                errors.append(f"roles.{name}.tools: must contain {tool} when it contains Bash")
    for tool in NESTING_TOOLS:
        if tool in tools:
            errors.append(f"roles.{name}.tools: must not contain {tool}")
    for tool in tools:
        if tool in disallowed:
            errors.append(f"roles.{name}: {tool} is in both tools and disallowed_tools")
    return errors


def _validate_role(name: str, role: Any) -> list:
    if not isinstance(role, dict):
        return [f"roles.{name}: must be an object"]
    errors = []
    tools = role.get("tools")
    tools_ok = isinstance(tools, list) and bool(tools) and all(isinstance(t, str) for t in tools)
    if not tools_ok:
        errors.append(f"roles.{name}.tools: must be a non-empty list of strings")
    disallowed = role.get("disallowed_tools")
    if not isinstance(disallowed, list):
        errors.append(f"roles.{name}.disallowed_tools: must be a list")
    else:
        for tool in NESTING_TOOLS:
            if tool not in disallowed:
                errors.append(f"roles.{name}.disallowed_tools: must contain {tool}")
    if tools_ok:
        errors.extend(
            _tool_list_errors(name, tools, disallowed if isinstance(disallowed, list) else [])
        )
    advisor = role.get("uses_advisor")
    if not isinstance(advisor, bool):
        errors.append(f"roles.{name}.uses_advisor: must be a bool")
    elif advisor != (name == "planner"):
        errors.append(f"roles.{name}.uses_advisor: only planner may use the advisor")
    if not isinstance(role.get("prefix"), str) or not role.get("prefix"):
        errors.append(f"roles.{name}.prefix: must be a non-empty string")
    return errors


def _validate_roles(roles: Any) -> list:
    if not isinstance(roles, dict):
        return ["roles: must be an object"]
    errors = []
    if set(roles) != set(ROLES):
        errors.append(f"roles: keys must be exactly {', '.join(ROLES)}")
    for name in ROLES:
        if name in roles:
            errors.extend(_validate_role(name, roles[name]))
    return errors


def _validate_effort_labels(labels: Any) -> list:
    if not isinstance(labels, dict):
        return ["effort_labels: must be an object"]
    errors = []
    if set(labels) != set(EFFORTS):
        errors.append(f"effort_labels: keys must be exactly {', '.join(EFFORTS)}")
    for effort, label in labels.items():
        if not isinstance(label, str) or not SLUG.match(label):
            errors.append(f"effort_labels.{effort}: must be a string matching ^[a-z0-9-]+$")
    values = [v for v in labels.values() if isinstance(v, str)]
    if len(set(values)) != len(values):
        errors.append("effort_labels: labels must be unique")
    return errors


def _valid_labels(labels: Any) -> Optional[dict]:
    return labels if not _validate_effort_labels(labels) else None


def _validate_model(label: str, model: Any) -> tuple:
    if model in TIER_FAMILIES:
        return model, []
    if isinstance(model, str) and model.startswith("claude-"):
        family = model_family(model)
        if family in TIER_FAMILIES:
            return family, []
    return None, [f"{label}: model {model!r} is not a haiku/sonnet/opus alias or id"]


def _validate_tier(tier: Any, index: int, roles: Any, labels: Optional[dict], seen: set) -> list:
    if not isinstance(tier, dict):
        return [f"tiers[{index}]: must be an object"]
    name = tier.get("name")
    label = f"tier {name}" if isinstance(name, str) else f"tiers[{index}]"
    errors = []
    if name in seen:
        errors.append(f"{label}: duplicate tier name")
    seen.add(name)
    role = tier.get("role")
    if role not in ROLES:
        errors.append(f"{label}: unknown role {role!r}")
    family, model_errors = _validate_model(label, tier.get("model"))
    errors.extend(model_errors)
    effort = tier.get("effort")
    if effort not in EFFORTS:
        errors.append(f"{label}: effort {effort!r} is not one of {', '.join(EFFORTS)}")
    errors.extend(_validate_tier_rules(label, tier, roles, labels, family))
    description = tier.get("description")
    if not isinstance(description, str) or not description or "\n" in description:
        errors.append(f"{label}: description must be a non-empty single line")
    return errors


def _validate_tier_rules(
    label: str, tier: dict, roles: Any, labels: Optional[dict], family: Optional[str]
) -> list:
    errors = []
    role, effort = tier.get("role"), tier.get("effort")
    role_def = roles.get(role) if isinstance(roles, dict) else None
    if family and effort in EFFORTS and labels and isinstance(role_def, dict):
        expected = f"{role_def.get('prefix')}-{family}-{labels[effort]}"
        if tier.get("name") != expected:
            errors.append(f"{label}: name must be {expected}")
    if family == "haiku" and effort == "xhigh":
        errors.append(f"{label}: haiku must not use effort xhigh")
    if role == "executor" and family == "opus":
        errors.append(f"{label}: an executor must not run on opus")
    return errors


def _validate_extras_and_audit(raw: Mapping, tier_names: set) -> list:
    errors = []
    extras = raw.get("extra_rules_by_model")
    if not isinstance(extras, dict):
        errors.append("extra_rules_by_model: must be an object")
    else:
        for key, rules in extras.items():
            ok = isinstance(rules, list) and all(isinstance(r, str) and r for r in rules)
            if key not in MODEL_FAMILIES or not ok:
                errors.append(f"extra_rules_by_model.{key}: invalid family or rule list")
    audit = raw.get("audit")
    if not isinstance(audit, dict):
        return errors + ["audit: must be an object"]
    for name in audit.get("flag_every_use") or []:
        if name not in tier_names:
            errors.append(f"audit.flag_every_use: {name} is not a tier")
    try:
        re.compile(audit.get("plan_path_pattern"))
    except (re.error, TypeError):
        errors.append("audit.plan_path_pattern: must be a valid regular expression")
    return errors


FRONTMATTER_FIELDS = {
    "omitClaudeMd": (lambda v: isinstance(v, bool), "must be a bool"),
    "autoCompactWindow": (
        lambda v: _is_int(v) and 100000 <= v <= 1000000,
        "must be an integer from 100000 to 1000000",
    ),
}


def _validate_frontmatter_fields(path: str, fields: Any) -> list:
    if not isinstance(fields, dict):
        return [f"agent_frontmatter.{path}: must be an object"]
    errors = []
    for key, value in fields.items():
        if key not in FRONTMATTER_FIELDS:
            errors.append(f"agent_frontmatter.{path}.{key}: unknown field")
        elif not FRONTMATTER_FIELDS[key][0](value):
            errors.append(f"agent_frontmatter.{path}.{key}: {FRONTMATTER_FIELDS[key][1]}")
    return errors


def _validate_agent_frontmatter(raw: Any) -> list:
    if not (isinstance(raw, dict) and set(raw) == {"all", "by_model"}
            and isinstance(raw["all"], dict) and isinstance(raw["by_model"], dict)):
        return ["agent_frontmatter: must be an object with keys all and by_model"]
    errors = _validate_frontmatter_fields("all", raw["all"])
    for family, fields in raw["by_model"].items():
        path = f"by_model.{family}"
        if family not in MODEL_FAMILIES:
            errors.append(f"agent_frontmatter.{path}: unknown model family")
            continue
        errors.extend(_validate_frontmatter_fields(path, fields))
        if isinstance(fields, dict):
            errors.extend(
                f"agent_frontmatter.{path}.{key}: already set in all"
                for key in fields if key in raw["all"]
            )
    return errors


def _validate_dispatch(raw: Any, tier_names: set) -> list:
    allow = raw.get("allow_agents") if isinstance(raw, dict) else None
    if not isinstance(raw, dict):
        return ["dispatch: must be an object with allow_agents"]
    valid = (isinstance(allow, list) and len(set(map(str, allow))) == len(allow)
             and all(isinstance(a, str) and a and not re.search(r"\s", a) for a in allow))
    if not valid:
        return ["dispatch.allow_agents: must be a list of unique agent type names"]
    errors = [f"dispatch.allow_agents: {a} is a tier" for a in allow if a in tier_names]
    try:
        re.compile(raw.get("blocked_output_names"))
    except (re.error, TypeError):
        errors.append("dispatch.blocked_output_names: must be a valid regular expression")
    return errors


def _is_str_list(value: Any, allow_empty: bool = False) -> bool:
    return (isinstance(value, list) and (allow_empty or bool(value))
            and all(isinstance(v, str) and v for v in value)
            and len(set(value)) == len(value))


def _stall_watch_has_list(section: Mapping, key: str) -> bool:
    return key in section and _is_str_list(section[key], allow_empty=key == "ignored_tools")


def _stall_watch_has_int(section: Mapping, key: str) -> bool:
    return key in section and _is_int(section[key]) and section[key] >= STALL_WATCH_INTS[key]


def _stall_watch_shape(section: Mapping) -> list:
    errors = [f"stall_watch.{key}: unknown key" for key in sorted(section) if key not in STALL_WATCH_KEYS]
    errors.extend(f"stall_watch.{key}: missing" for key in STALL_WATCH_KEYS if key not in section)
    return errors


def _stall_watch_scalars(section: Mapping) -> list:
    errors = []
    if "enabled" in section and not isinstance(section["enabled"], bool):
        errors.append("stall_watch.enabled: must be true or false")
    for key, minimum in STALL_WATCH_INTS.items():
        if key in section and not _stall_watch_has_int(section, key):
            errors.append(f"stall_watch.{key}: must be an integer >= {minimum}")
    if (_stall_watch_has_int(section, "repeat_limit")
            and _stall_watch_has_int(section, "repeat_window")
            and section["repeat_limit"] > section["repeat_window"]):
        errors.append("stall_watch.repeat_limit: must not exceed repeat_window")
    return errors


def _stall_watch_roles(section: Mapping) -> list:
    if "roles" not in section:
        return []
    if not _is_str_list(section["roles"]):
        return ["stall_watch.roles: must be a non-empty list of unique non-empty strings"]
    return [f"stall_watch.roles: unknown role {r}" for r in section["roles"] if r not in ROLES]


def _stall_watch_lists(section: Mapping) -> list:
    errors = [
        f"stall_watch.{key}: must be a non-empty list of unique non-empty strings"
        for key in STALL_WATCH_LISTS if key in section and not _is_str_list(section[key])
    ]
    if "ignored_tools" in section and not _is_str_list(section["ignored_tools"], allow_empty=True):
        errors.append("stall_watch.ignored_tools: must be a list of unique non-empty strings")
    return errors


def _watched_tools(config: Mapping, roles: list) -> set:
    tools: set = set()
    config_roles = config.get("roles")
    for name in roles:
        entry = config_roles.get(name) if isinstance(config_roles, dict) else None
        if isinstance(entry, dict) and isinstance(entry.get("tools"), list):
            tools.update(t for t in entry["tools"] if isinstance(t, str))
    return tools


def _stall_watch_tools(config: Mapping, section: Mapping) -> list:
    if "roles" not in section or not _is_str_list(section["roles"]):
        return []
    watched = _watched_tools(config, section["roles"])
    if not watched:
        return []
    errors = []
    for key in ("ignored_tools", "change_tools", "handback_tools", "read_only_tools"):
        if _stall_watch_has_list(section, key):
            errors.extend(
                f"stall_watch.{key}: {tool} is not a tool of any watched role"
                for tool in section[key] if tool not in watched
            )
    return errors


def _stall_watch_overlaps(section: Mapping) -> list:
    errors = []
    ignored = section.get("ignored_tools") if _stall_watch_has_list(section, "ignored_tools") else []
    for tool in ignored:
        for key in ("change_tools", "handback_tools", "read_only_tools"):
            if _stall_watch_has_list(section, key) and tool in section[key]:
                errors.append(f"stall_watch.ignored_tools: {tool} is also in {key}")
                break
    if _stall_watch_has_list(section, "change_tools") and _stall_watch_has_list(section, "read_only_tools"):
        errors.extend(
            f"stall_watch.change_tools: {tool} is also in read_only_tools"
            for tool in section["change_tools"] if tool in section["read_only_tools"]
        )
    return errors


def _validate_stall_watch(config: Mapping) -> list:
    if "stall_watch" not in config:
        return ["stall_watch: missing"]
    section = config["stall_watch"]
    if not isinstance(section, dict):
        return ["stall_watch: must be an object"]
    errors = _stall_watch_shape(section)
    errors.extend(_stall_watch_scalars(section))
    errors.extend(_stall_watch_roles(section))
    errors.extend(_stall_watch_lists(section))
    errors.extend(_stall_watch_tools(config, section))
    errors.extend(_stall_watch_overlaps(section))
    return errors


def _validate_policy(policy: Any) -> list:
    if not isinstance(policy, dict):
        return ["policy: must be an object"]
    sections = policy.get("sections")
    if not (isinstance(sections, list) and len(set(sections)) == len(sections)
            and all(isinstance(s, str) and SLUG.match(s) for s in sections)):
        return ["policy.sections: must be a unique list of ids matching ^[a-z0-9-]+$"]
    parts = policy.get("dispatcher_parts")
    if not isinstance(parts, list) or not parts:
        return ["policy.dispatcher_parts: must be a non-empty list"]
    errors = []
    for i, part in enumerate(parts):
        title = part.get("title") if isinstance(part, dict) else None
        listed = part.get("sections") if isinstance(part, dict) else None
        if not isinstance(title, str) or not title:
            errors.append(f"policy.dispatcher_parts[{i}].title: must be non-empty")
        if not isinstance(listed, list) or not listed:
            errors.append(f"policy.dispatcher_parts[{i}].sections: must be non-empty")
            continue
        for section in listed:
            if section not in sections:
                errors.append(f"policy.dispatcher_parts[{i}]: unknown section {section}")
    return errors


def _validate_header(raw: Mapping) -> list:
    errors = []
    if raw.get("schema_version") != 1:
        errors.append("schema_version: must be 1")
    name = raw.get("plugin_name")
    if not isinstance(name, str) or not SLUG.match(name):
        errors.append("plugin_name: must match ^[a-z0-9-]+$")
    if isinstance(name, str) and name.startswith(RESERVED_PLUGIN_PREFIXES):
        errors.append(
            f"plugin_name '{name}' uses a reserved prefix "
            "(claude-, anthropic-, anthropics-, cc-plugin-)"
        )
    dispatcher = raw.get("dispatcher")
    if not isinstance(dispatcher, dict):
        return errors + ["dispatcher: must be an object"]
    if dispatcher.get("model_family") not in MODEL_FAMILIES:
        errors.append("dispatcher.model_family: unknown model family")
    if dispatcher.get("effort") not in EFFORTS:
        errors.append("dispatcher.effort: unknown effort")
    return errors


def validate(raw: Mapping) -> list:
    """Return every validation message for a raw config; empty means valid."""
    if not isinstance(raw, dict):
        return ["config: must be a JSON object"]
    errors = _validate_header(raw)
    errors.extend(_validate_tunables(raw.get("tunables")))
    roles = raw.get("roles")
    errors.extend(_validate_roles(roles))
    labels = raw.get("effort_labels")
    errors.extend(_validate_effort_labels(labels))
    labels = _valid_labels(labels)
    tiers = raw.get("tiers")
    if not isinstance(tiers, list) or not tiers:
        errors.append("tiers: must be a non-empty list")
        tiers = []
    seen: set = set()
    for index, tier in enumerate(tiers):
        errors.extend(_validate_tier(tier, index, roles, labels, seen))
    errors.extend(_validate_extras_and_audit(raw, seen))
    errors.extend(_validate_agent_frontmatter(raw.get("agent_frontmatter")))
    errors.extend(_validate_dispatch(raw.get("dispatch"), seen))
    errors.extend(_validate_policy(raw.get("policy")))
    errors.extend(_validate_stall_watch(raw))
    return errors


def _build(raw: Mapping) -> RoutingConfig:
    roles = {
        name: Role(
            name=name,
            prefix=r["prefix"],
            tools=tuple(r["tools"]),
            disallowed_tools=tuple(r["disallowed_tools"]),
            uses_advisor=r["uses_advisor"],
        )
        for name, r in raw["roles"].items()
    }
    tiers = tuple(
        Tier(t["name"], t["role"], t["model"], t["effort"], t["description"],
             model_family(t["model"]))
        for t in raw["tiers"]
    )
    parts = tuple(
        DispatcherPart(p["title"], tuple(p["sections"]))
        for p in raw["policy"]["dispatcher_parts"]
    )
    return RoutingConfig(
        plugin_name=raw["plugin_name"],
        dispatcher_model_family=raw["dispatcher"]["model_family"],
        dispatcher_effort=raw["dispatcher"]["effort"],
        tunables=MappingProxyType(dict(raw["tunables"])),
        roles=MappingProxyType(roles),
        tiers=tiers,
        extra_rules_by_model=MappingProxyType(
            {k: tuple(v) for k, v in raw["extra_rules_by_model"].items()}
        ),
        audit_flag_every_use=tuple(raw["audit"]["flag_every_use"]),
        plan_path_pattern=raw["audit"]["plan_path_pattern"],
        policy_sections=tuple(raw["policy"]["sections"]),
        dispatcher_parts=parts,
        agent_frontmatter=tuple(raw["agent_frontmatter"]["all"].items()),
        agent_frontmatter_by_model=MappingProxyType({
            k: tuple(v.items()) for k, v in raw["agent_frontmatter"]["by_model"].items()
        }),
        dispatch_allow_agents=tuple(raw["dispatch"]["allow_agents"]),
        dispatch_blocked_output_names=raw["dispatch"]["blocked_output_names"],
        stall_watch=_build_stall_watch(raw["stall_watch"]),
    )


def _build_stall_watch(section: Mapping) -> StallWatch:
    return StallWatch(
        enabled=section["enabled"],
        roles=tuple(section["roles"]),
        ignored_tools=tuple(section["ignored_tools"]),
        change_tools=tuple(section["change_tools"]),
        handback_tools=tuple(section["handback_tools"]),
        read_only_tools=tuple(section["read_only_tools"]),
        read_only_bash_prefixes=tuple(section["read_only_bash_prefixes"]),
        repeat_window=section["repeat_window"],
        repeat_limit=section["repeat_limit"],
        read_only_streak_limit=section["read_only_streak_limit"],
        max_nudges=section["max_nudges"],
        state_max_age_hours=section["state_max_age_hours"],
    )


def load_config(path: Optional[Path] = None) -> RoutingConfig:
    """Load and validate the routing config; raise ConfigError on any problem."""
    target = Path(path) if path is not None else CONFIG_PATH
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"cannot read {target}: {exc}") from exc
    errors = validate(raw)
    if errors:
        raise ConfigError("\n".join(errors))
    return _build(raw)


def _scoped_remainder(agent_type: str, config: RoutingConfig) -> Optional[str]:
    prefix, sep, rest = agent_type.partition(":")
    if sep and prefix.split("@")[0] == config.plugin_name:
        return rest
    return None


def bare_name(agent_type: str, config: RoutingConfig) -> str:
    """Strip this plugin's scope prefix from an agent type, else return it unchanged."""
    rest = _scoped_remainder(agent_type, config)
    return agent_type if rest is None else rest


def resolve_tier(agent_type: Any, config: RoutingConfig) -> Optional[Tier]:
    """Return the tier an agent type names (bare or plugin-scoped), else None."""
    if not isinstance(agent_type, str) or not agent_type:
        return None
    if ":" in agent_type:
        name = _scoped_remainder(agent_type, config)
    else:
        name = agent_type
    return next((t for t in config.tiers if t.name == name), None)


def tier_names(config: RoutingConfig) -> tuple:
    return tuple(t.name for t in config.tiers)


def role_of(tier: Tier, config: RoutingConfig) -> Role:
    return config.roles[tier.role]
