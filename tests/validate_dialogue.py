#!/usr/bin/env python3
"""Validate all data/dialogue/*.json; no arguments or Godot required.

Exit 0 = valid, 1 = errors. Conditions use strict booleans, absent = false.
Explores persistent flag states across completed/repeated conversations.
Entry availability is conservative: every known entry may be started after
any completed conversation. Scene/puzzle ordering is not modeled.
"""
from __future__ import annotations

from collections import defaultdict, deque
from itertools import product
import json
from pathlib import Path

KNOWN_ENTRIES = {"logbook", "radio", "door", "start"}
JOURNAL_ENTRY_PREFIX = "entry_"
# Declare flags produced by gameplay outside dialogue here, with the values
# reachable before a conversation. Keep empty until real gameplay producers
# exist. Example: {"lamp_relit": (False, True)}. No CLI configuration needed.
EXTERNAL_FLAG_VALUES: dict[str, tuple[bool, ...]] = {}
MAX_STATES = 100_000
ROOT = Path(__file__).resolve().parent.parent
DIALOGUE_DIR = ROOT / "data" / "dialogue"


def is_journal_graph(graph: dict) -> bool:
    return any(k.startswith(JOURNAL_ENTRY_PREFIX) for k in graph)


def entries_for(graph: dict) -> set[str]:
    return (KNOWN_ENTRIES & graph.keys()) | {
        k for k in graph if k.startswith(JOURNAL_ENTRY_PREFIX)
    }


def reachable(graph: dict, entries: set[str]) -> set[str]:
    """Structural reachability; call only after schema validation."""
    seen = set()
    stack = list(entries)
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        node = graph[nid]
        edges = node["choices"] if "choices" in node else [node]
        stack.extend(c["next"] for c in edges if c["next"] is not None)
    return seen


def check_schema(path: Path, graph: object) -> list[str]:
    errors = []
    def error(where, message):
        errors.append(f"{path.name}:{where}: {message}")
    if not isinstance(graph, dict) or not graph:
        return [f"{path.name}: top level must be a nonempty object of node_id -> node"]
    def flags(value, where, requirements=False):
        if not isinstance(value, dict):
            error(where, "flags must be an object")
            return
        for key, val in value.items():
            if not isinstance(key, str) or not key:
                error(where, "flag names must be nonempty strings")
            if requirements and type(val) is not bool:
                error(where, "requires_flags values must be booleans")
    def target(item, where):
        if "next" not in item:
            error(where, "missing explicit 'next' (use null to end)")
        elif item["next"] is not None and (
            not isinstance(item["next"], str) or item["next"] not in graph
        ):
            error(where, f"'next' points to missing/invalid node {item['next']!r}")
    for nid, node in graph.items():
        if not nid or not isinstance(node, dict):
            error(str(nid), "node must have a nonempty ID and an object value")
            continue
        if "requires_flags" in node:
            error(nid, "requires_flags is supported on choices only")
        if "set_flag" in node:
            flags(node["set_flag"], nid)
        if ("choices" in node) == ("next" in node):
            error(nid, "node must have exactly one of 'next' or 'choices'")
        if "next" in node:
            target(node, nid)
        if "choices" not in node:
            continue
        choices = node["choices"]
        if not isinstance(choices, list) or not choices:
            error(nid, "choices must be a nonempty array")
            continue
        for i, choice in enumerate(choices):
            where = f"{nid}:choice #{i}"
            if not isinstance(choice, dict):
                error(where, "choice must be an object")
                continue
            if not isinstance(choice.get("text"), str):
                error(where, "choice needs a string 'text'")
            target(choice, where)
            if "set_flag" in choice:
                flags(choice["set_flag"], where)
            if "requires_flags" in choice:
                flags(choice["requires_flags"], where, True)
    return errors


def analyze(graphs: dict[Path, dict], external=None, max_states=MAX_STATES):
    """Exact boolean-condition abstraction; unrelated flag values are ignored.

    Each relevant flag is false (also absent), true, or non-boolean. The third
    category never matches a boolean requirement, matching GameState exactly.
    Paths remain separate; flag sets are never unioned at branch merges.
    """
    external = EXTERNAL_FLAG_VALUES if external is None else external
    errors, warnings = [], []
    producers, required = set(external), set()
    for graph in graphs.values():
        for node in graph.values():
            producers.update(node.get("set_flag", {}))
            for choice in node.get("choices", []):
                producers.update(choice.get("set_flag", {}))
                required.update(choice.get("requires_flags", {}))
    for path, graph in graphs.items():
        for nid, node in graph.items():
            for i, choice in enumerate(node.get("choices", [])):
                for key in choice.get("requires_flags", {}):
                    if key not in producers:
                        errors.append(f"{path.name}:{nid}:choice #{i}: missing prerequisite flag '{key}' (no dialogue producer or external declaration)")
    for key, values in external.items():
        if not isinstance(key, str) or not key or not values or any(type(v) is not bool for v in values):
            errors.append(f"invalid external flag declaration: {key!r}")
    if errors:
        return errors, warnings
    keys = sorted(required)
    slots = {key: i for i, key in enumerate(keys)}
    def apply(state, effects):
        result = list(state)
        for key, val in effects.items():
            if key in slots:
                result[slots[key]] = int(val) if type(val) is bool else 2
        return tuple(result)
    def allows(state, requirements):
        return all(state[slots[k]] == int(v) for k, v in requirements.items())
    entries = []
    structural = {}
    for path, graph in graphs.items():
        starts = entries_for(graph)
        if not starts:
            errors.append(f"{path.name}: no known entry point; add its real entry to KNOWN_ENTRIES")
        structural[path] = reachable(graph, starts)
        entries.extend((path, nid) for nid in sorted(starts))
        for nid in sorted(graph.keys() - structural[path]):
            warnings.append(f"{path.name}:{nid}: structurally unreachable from known entries")
    queue, discovered = deque(), set()
    reverse = defaultdict(set)
    terminals, seen_nodes, chosen, blocked = set(), set(), set(), set()
    completed_states = set()
    def enqueue(path, nid, flags):
        # State identity is AFTER entry effects, as in DialogueManager._goto.
        state = (path, nid, apply(flags, graphs[path][nid].get("set_flag", {})))
        if state not in discovered:
            if len(discovered) >= max_states:
                raise OverflowError
            discovered.add(state)
            queue.append(state)
        return state
    external_keys = sorted(set(external) & required)
    def restart(flags):
        # External values are assumptions, not invented dialogue producers.
        for values in product(*(external[k] for k in external_keys)):
            seed = apply(flags, dict(zip(external_keys, values)))
            if seed in completed_states:
                continue
            completed_states.add(seed)
            for path, nid in entries:
                enqueue(path, nid, seed)
    try:
        restart((0,) * len(keys))
        while queue:
            state = queue.popleft()
            path, nid, flags = state
            seen_nodes.add((path, nid))
            node = graphs[path][nid]
            options = node.get("choices")
            edges = [(None, node)] if options is None else [
                (i, c) for i, c in enumerate(options)
                if allows(flags, c.get("requires_flags", {}))
            ]
            if not edges:
                blocked.add((path, nid))
            for index, edge in edges:
                if index is not None:
                    chosen.add((path, nid, index))
                after = apply(flags, edge.get("set_flag", {})) if index is not None else flags
                if edge["next"] is None:
                    terminals.add(state)
                    restart(after)
                else:
                    dest = enqueue(path, edge["next"], after)
                    reverse[dest].add(state)
    except OverflowError:
        errors.append(f"state exploration exceeded {max_states} states; analysis incomplete (not a pass)")
        return errors, warnings
    can_end = set(terminals)
    queue = deque(terminals)
    while queue:
        for previous in reverse[queue.popleft()]:
            if previous not in can_end:
                can_end.add(previous)
                queue.append(previous)
    for path, nid in sorted(blocked):
        errors.append(f"{path.name}:{nid}: reachable flag state has no eligible choices")
    for path, nid in sorted({(p, n) for p, n, _ in discovered - can_end} - blocked):
        errors.append(f"{path.name}:{nid}: reachable flag state has no path to an ending")
    for path, graph in graphs.items():
        for nid in sorted(structural[path]):
            if (path, nid) not in seen_nodes:
                errors.append(f"{path.name}:{nid}: unreachable once flag prerequisites are applied")
            else:
                for i in range(len(graph[nid].get("choices", []))):
                    if (path, nid, i) not in chosen:
                        errors.append(f"{path.name}:{nid}:choice #{i}: prerequisites can never be satisfied on a reachable visit")
    return errors, warnings


def validate_paths(paths, external=None, max_states=MAX_STATES):
    graphs, errors = {}, []
    for path in paths:
        try:
            graph = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{path.name}: cannot read dialogue JSON: {exc}")
            continue
        found = check_schema(path, graph)
        errors.extend(found)
        if not found:
            graphs[path] = graph
    if errors:
        return errors, []  # Do not traverse malformed graphs or infer missing producers.
    return analyze(graphs, external, max_states)


def validate_file(path: Path):
    """Single-file compatibility helper; main analyzes the complete folder."""
    return validate_paths([path])


def main() -> int:
    files = sorted(DIALOGUE_DIR.glob("*.json"))
    if not files:
        print(f"No dialogue files found in {DIALOGUE_DIR}")
        return 1
    errors, warnings = validate_paths(files)
    for path in files:
        print(f"[CHECKED] {path.relative_to(ROOT)}")
    for message in warnings:
        print(f"  warning: {message}")
    for message in errors:
        print(f"  ERROR: {message}")
    print(f"{'FAIL' if errors else 'OK'}: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
