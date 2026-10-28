"""Finite authored solver audit, independently enumerated in ordinary Python.

These are synthetic five-task cases, not held-out human data or a population
benchmark. The oracle does not call the production checker or solver while
constructing its feasible set or objective values.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from itertools import combinations

import pytest

from broker.checker import verify_assignments
from broker.solver import solve
from shared.schema import TASKS

IDS = ("prepare", "outbound", "accompany", "return", "handoff")


def task(task_id, start, duration=5, slack=0, location="home", capability="preparation", predecessors=()):
    return {"task_id": task_id, "label": task_id, "duration": duration, "earliest": start, "latest": start + duration + slack, "location": location, "capability": capability, "predecessors": list(predecessors)}


def chain(slack=0, gap=6, locations=None):
    return [task(tid, index * gap, slack=slack, location=(locations or ["home"] * 5)[index], predecessors=IDS[index - 1:index] if index else ()) for index, tid in enumerate(IDS)]


def offer(owner, tasks=IDS, start=0, end=1000, cost=0, capabilities=("preparation", "driving", "accompaniment", "handoff"), suffix=""):
    return {"offer_id": f"oracle-{owner}-{suffix or 'one'}", "owner_id": owner, "revision": 1, "constraint_revision": 1, "task_ids": list(tasks), "capabilities": list(capabilities), "start": start, "end": end, "capacity": 1, "preference_cost": cost}


def edge_locations(location):
    parts = location.split("→")
    return parts[0], parts[-1]


def signature(assignments):
    return tuple(sorted((a["task_id"], a["owner_id"], a["start"], a["end"], a["offer_id"]) for a in assignments))


def independently_valid(tasks, offers, assignments):
    """Validate by direct set, pair and graph relations, without production code."""
    if len(assignments) != len(tasks) or len({a.get("task_id") for a in assignments}) != len(tasks):
        return False
    task_by_id = {t["task_id"]: t for t in tasks}
    offered = {o["offer_id"]: o for o in offers}
    assigned = {a["task_id"]: a for a in assignments}
    if set(task_by_id) != set(assigned) or len(offered) != len(offers):
        return False
    for a in assignments:
        t, o = task_by_id[a["task_id"]], offered.get(a.get("offer_id"))
        if o is None or o["capacity"] != 1 or a.get("owner_id") != o["owner_id"] or a.get("offer_revision") != o["revision"]:
            return False
        if t["task_id"] not in o["task_ids"] or t["capability"] not in o["capabilities"]:
            return False
        if type(a.get("start")) is not int or type(a.get("end")) is not int:
            return False
        if a["end"] - a["start"] != t["duration"]:
            return False
        if not (t["earliest"] <= a["start"] and a["end"] <= t["latest"] and o["start"] <= a["start"] and a["end"] <= o["end"]):
            return False
        for prerequisite in t["predecessors"]:
            if prerequisite not in assigned or assigned[prerequisite]["end"] > a["start"]:
                return False
    for one, two in combinations(assignments, 2):
        if one["owner_id"] == two["owner_id"]:
            before, after = sorted((one, two), key=lambda a: a["start"])
            _, destination = edge_locations(task_by_id[before["task_id"]]["location"])
            origin, _ = edge_locations(task_by_id[after["task_id"]]["location"])
            if before["end"] + (40 if destination != origin else 0) > after["start"]:
                return False
    return True


def independent_objective(tasks, offers, assignments, previous=(), suggestions=()):
    task_by_id = {t["task_id"]: t for t in tasks}
    offers_by_id = {o["offer_id"]: o for o in offers}
    former = {a["task_id"]: a["owner_id"] for a in previous or ()}
    suggested = {a["task_id"]: a["owner_id"] for a in suggestions or ()}
    grouped = defaultdict(list)
    weighted, changed, deviation, waiting = 0, 0, 0, 0
    for a in assignments:
        t = task_by_id[a["task_id"]]
        grouped[a["owner_id"]].append(a)
        weighted += t["duration"] * (1 + offers_by_id[a["offer_id"]]["preference_cost"])
        waiting += a["start"] - t["earliest"]
        changed += a["task_id"] in former and former[a["task_id"]] != a["owner_id"]
        deviation += a["task_id"] in suggested and suggested[a["task_id"]] != a["owner_id"]
    maximum_work = max((sum(task_by_id[a["task_id"]]["duration"] for a in group) for group in grouped.values()), default=0)
    transfers = 0
    for group in grouped.values():
        scheduled = sorted(group, key=lambda a: a["start"])
        for before, after in zip(scheduled, scheduled[1:]):
            _, destination = edge_locations(task_by_id[before["task_id"]]["location"])
            origin, _ = edge_locations(task_by_id[after["task_id"]]["location"])
            transfers += 40 if destination != origin else 0
    return int(changed), weighted + maximum_work, transfers + waiting, int(deviation)


@dataclass
class OracleResult:
    objective: tuple | None
    optima: set
    feasible_count: int


def enumerate_oracle(tasks, offers, previous=(), suggestions=()):
    """Exhaust every legal integer start and eligible offer, pruning partial facts.

    Small authored windows keep the complete search finite. Pruning checks only
    already assigned prerequisites and pairwise owner constraints, then the full
    validator independently checks complete schedules.
    """
    choices = {}
    by_id = {t["task_id"]: t for t in tasks}
    for t in tasks:
        domain = []
        for o in offers:
            if o["capacity"] != 1 or t["task_id"] not in o["task_ids"] or t["capability"] not in o["capabilities"]:
                continue
            first = max(t["earliest"], o["start"])
            last = min(t["latest"], o["end"]) - t["duration"]
            for start in range(first, last + 1):
                domain.append({"task_id": t["task_id"], "owner_id": o["owner_id"], "start": start, "end": start + t["duration"], "offer_id": o["offer_id"], "offer_revision": o["revision"]})
        choices[t["task_id"]] = domain
    order = sorted(tasks, key=lambda t: (len(choices[t["task_id"]]), t["task_id"]))
    best, optimal, count = None, set(), 0
    selected = {}

    def visit(index):
        nonlocal best, count, optimal
        if index == len(order):
            schedule = list(selected.values())
            if not independently_valid(tasks, offers, schedule):
                return
            count += 1
            score = independent_objective(tasks, offers, schedule, previous, suggestions)
            if best is None or score < best:
                best, optimal = score, {signature(schedule)}
            elif score == best:
                optimal.add(signature(schedule))
            return
        t = order[index]
        for a in choices[t["task_id"]]:
            valid = True
            for other_id, b in selected.items():
                other_task = by_id[other_id]
                if other_id in t["predecessors"] and b["end"] > a["start"]:
                    valid = False
                if t["task_id"] in other_task["predecessors"] and a["end"] > b["start"]:
                    valid = False
                if a["owner_id"] == b["owner_id"]:
                    before, after = (a, b) if a["start"] <= b["start"] else (b, a)
                    destination = edge_locations(by_id[before["task_id"]]["location"])[1]
                    origin = edge_locations(by_id[after["task_id"]]["location"])[0]
                    if before["end"] + (0 if destination == origin else 40) > after["start"]:
                        valid = False
                if not valid:
                    break
            if valid:
                selected[t["task_id"]] = a
                visit(index + 1)
                del selected[t["task_id"]]
    visit(0)
    return OracleResult(best, optimal, count)


def authored_cases():
    cases = []
    def add(name, tasks, offers, previous=(), suggestions=()):
        cases.append(pytest.param(tasks, offers, previous, suggestions, id=name))
    for slack in (0, 1, 2):
        add(f"balanced-two-owner-slack{slack}", chain(slack), [offer("asha"), offer("ravi")])
        add(f"costly-third-owner-slack{slack}", chain(slack), [offer("asha"), offer("ravi"), offer("leena", cost=2)])
    add("single-owner-chain", chain(2), [offer("asha")])
    add("restricted-task-alternatives", chain(1), [offer("asha", IDS[::2]), offer("ravi", IDS[1::2]), offer("leena", IDS[2:], cost=1)])
    add("offer-window-forces-alternate", chain(1), [offer("asha", end=23), offer("ravi", start=23)])
    add("missing-final-task-allowlist", chain(), [offer("asha", IDS[:-1]), offer("ravi", IDS[:-1])])
    add("missing-capability-despite-task-id", chain(), [offer("asha", capabilities=("driving",))])
    add("no-offers", chain(), [])
    add("offer-too-short-for-final-end", chain(), [offer("asha", end=28)])
    impossible = chain()
    impossible[2]["latest"] = impossible[2]["earliest"] + 4
    add("task-interval-shorter-than-duration", impossible, [offer("asha")])
    backwards = chain()
    backwards[0]["earliest"], backwards[0]["latest"] = 10, 15
    add("precedence-overlap", backwards, [offer("asha"), offer("ravi")])
    cyclic = chain()
    cyclic[0]["predecessors"] = [IDS[-1]]
    add("cyclic-precedence", cyclic, [offer("asha"), offer("ravi")])
    alternating = ["home", "clinic", "home", "clinic", "home"]
    add("different-owner-needed-for-travel", chain(1, locations=alternating), [offer("asha"), offer("ravi")])
    add("travel-infeasible-one-owner", chain(1, locations=alternating), [offer("asha")])
    add("travel-exact-forty-minute-gap", chain(gap=45, locations=alternating), [offer("asha")])
    add("travel-gap-thirty-nine-rejected", chain(gap=44, locations=alternating), [offer("asha")])
    directed = ["home→clinic", "clinic", "clinic→home", "home", "home"]
    add("directed-task-endpoints", chain(gap=5, locations=directed), [offer("asha")])
    parallel = [task(tid, 0, predecessors=()) for tid in IDS]
    add("parallel-capacity-overload", parallel, [offer("asha"), offer("ravi"), offer("leena")])
    add("parallel-one-owner-each", parallel, [offer(f"owner{index}", [tid]) for index, tid in enumerate(IDS)])
    duplicated_owner = chain()
    duplicated_owner[0] = task(IDS[0], 0)
    duplicated_owner[1] = task(IDS[1], 0)
    add("capacity-shared-across-two-offers", duplicated_owner, [offer("asha", IDS[:1], suffix="a"), offer("asha", IDS[1:2], suffix="b"), offer("ravi", IDS[2:])])
    previous = [{"task_id": tid, "owner_id": "asha"} for tid in IDS]
    add("prior-owner-first-even-when-costlier", chain(), [offer("asha", cost=3), offer("ravi")], previous)
    add("prior-owner-withdrawn-offer", chain(), [offer("ravi"), offer("leena")], previous)
    return cases


@pytest.mark.parametrize("tasks,offers,previous,suggestions", authored_cases())
def test_solver_matches_exhaustive_five_task_oracle(tasks, offers, previous, suggestions):
    oracle = enumerate_oracle(tasks, offers, previous, suggestions)
    solved = solve(tasks, offers, previous=list(previous), suggestions=list(suggestions))
    if oracle.objective is None:
        assert solved["status"] == "INFEASIBLE", (oracle, solved)
        assert solved["assignments"] == []
    else:
        assert solved["status"] == "OPTIMAL" and solved["lexicographic_optimal"] is True
        assert independently_valid(tasks, offers, solved["assignments"])
        assert tuple(solved["objectives"]) == oracle.objective
        assert signature(solved["assignments"]) in oracle.optima
        assert verify_assignments(tasks, offers, solved["assignments"])["valid"]


def test_zero_search_budget_is_unknown_and_not_false_infeasible():
    tasks, offers = chain(2), [offer("asha"), offer("ravi")]
    assert enumerate_oracle(tasks, offers).feasible_count > 0
    result = solve(tasks, offers, max_seconds=0)
    assert result["status"] == "UNKNOWN" and result["assignments"] == []
    assert "did not establish" in result["reason"]


def test_unknown_predecessor_and_unsupported_capacity_are_model_invalid():
    tasks = chain()
    tasks[0]["predecessors"] = ["unknown-task"]
    assert solve(tasks, [offer("asha")])["status"] == "MODEL_INVALID"
    invalid = offer("asha")
    invalid["capacity"] = 2
    assert solve(chain(), [invalid])["status"] == "MODEL_INVALID"


def test_model_suggestions_only_choose_among_equal_cost_balanced_optima():
    tasks, offers = chain(), [offer("asha"), offer("ravi")]
    first = [{"task_id": tid, "owner_id": "asha" if index < 3 else "ravi"} for index, tid in enumerate(IDS)]
    second = [{"task_id": tid, "owner_id": "ravi" if index < 3 else "asha"} for index, tid in enumerate(IDS)]
    plans = []
    for suggested in (first, second):
        expected = enumerate_oracle(tasks, offers, suggestions=suggested)
        result = solve(tasks, offers, suggestions=suggested)
        assert tuple(result["objectives"]) == expected.objective
        assert signature(result["assignments"]) in expected.optima
        assert result["objectives"][-1] == 0
        plans.append(result)
    assert plans[0]["objectives"][:3] == plans[1]["objectives"][:3]
    assert {a["task_id"]: a["owner_id"] for a in plans[0]["assignments"]} != {a["task_id"]: a["owner_id"] for a in plans[1]["assignments"]}
    # All-Asha model preference cannot override the earlier workload objective.
    unbalanced = [{"task_id": tid, "owner_id": "asha"} for tid in IDS]
    result = solve(tasks, offers, suggestions=unbalanced)
    assert len({a["owner_id"] for a in result["assignments"]}) == 2
    assert result["objectives"][:3] == plans[0]["objectives"][:3]


def test_model_suggestions_cannot_override_cost_or_missing_capability():
    tasks = chain()
    offers = [offer("asha"), offer("ravi"), offer("leena", cost=10), offer("incapable", capabilities=("driving",))]
    for suggested_owner in ("leena", "incapable"):
        hints = [{"task_id": tid, "owner_id": suggested_owner} for tid in IDS]
        oracle = enumerate_oracle(tasks, offers, suggestions=hints)
        result = solve(tasks, offers, suggestions=hints)
        assert tuple(result["objectives"]) == oracle.objective
        assert all(a["owner_id"] not in ("leena", "incapable") for a in result["assignments"])


def test_real_sample_preference_correction_genuinely_changes_handoff():
    tasks = deepcopy(TASKS)
    offers = [offer("asha", ["prepare", "handoff"], 720, 990), offer("ravi", ["outbound", "return"], 780, 975, cost=1), offer("leena", ["accompany", "return", "handoff"], 820, 1005)]
    first_oracle = enumerate_oracle(tasks, offers)
    first = solve(tasks, offers)
    assert tuple(first["objectives"]) == first_oracle.objective
    assert next(a for a in first["assignments"] if a["task_id"] == "handoff")["owner_id"] == "asha"
    corrected = deepcopy(offers)
    corrected[0].update(end=950, revision=2, constraint_revision=2)
    second_oracle = enumerate_oracle(tasks, corrected, previous=first["assignments"])
    second = solve(tasks, corrected, previous=first["assignments"])
    assert tuple(second["objectives"]) == second_oracle.objective
    assert independently_valid(tasks, corrected, second["assignments"])
    assert next(a for a in second["assignments"] if a["task_id"] == "handoff")["owner_id"] == "leena"
    assert second["objectives"][0] == 1
    assert not verify_assignments(tasks, corrected, first["assignments"])["valid"]


@pytest.mark.parametrize("tamper", ["duplicate", "missing", "owner", "offer_revision", "duration", "window", "scope", "capability", "overlap", "precedence", "travel"])
def test_checker_independently_rejects_forged_assignments(tamper):
    tasks, offers = chain(), [offer("asha"), offer("ravi")]
    assignments = solve(tasks, offers)["assignments"]
    if tamper == "duplicate":
        assignments.append(deepcopy(assignments[0]))
    elif tamper == "missing":
        assignments.pop()
    elif tamper == "owner":
        assignments[0]["owner_id"] = "unknown-owner"
    elif tamper == "offer_revision":
        assignments[0]["offer_revision"] += 1
    elif tamper == "duration":
        assignments[0]["end"] += 1
    elif tamper == "window":
        assignments[0]["start"] -= 1
        assignments[0]["end"] -= 1
    elif tamper == "scope":
        next(o for o in offers if o["offer_id"] == assignments[0]["offer_id"])["task_ids"].remove(assignments[0]["task_id"])
    elif tamper == "capability":
        next(o for o in offers if o["offer_id"] == assignments[0]["offer_id"])["capabilities"] = ["driving"]
    elif tamper == "overlap":
        assignments[1].update(owner_id=assignments[0]["owner_id"], offer_id=assignments[0]["offer_id"], start=0, end=5)
    elif tamper == "precedence":
        tasks[0]["predecessors"] = [tasks[-1]["task_id"]]
    elif tamper == "travel":
        tasks[0]["location"] = "clinic"
        # Ensure the first two responsibilities belong to the same owner, making
        # a physical transfer impossible despite a forged checker.valid claim.
        assignments[1].update(owner_id=assignments[0]["owner_id"], offer_id=assignments[0]["offer_id"])
    assert not independently_valid(tasks, offers, assignments)
    assert verify_assignments(tasks, offers, assignments)["valid"] is False


def test_reversed_nonchain_schedule_counts_actual_directed_transfer_effort():
    tasks = [task(IDS[0], 0, duration=10, slack=100, location="home→clinic"), task(IDS[1], 1, duration=10)]
    tasks.extend(task(tid, start, duration=10) for tid, start in zip(IDS[2:], (120, 140, 160)))
    offers = [offer("asha", IDS[:2]), offer("ravi", IDS[2:])]
    oracle = enumerate_oracle(tasks, offers)
    result = solve(tasks, offers)
    assert oracle.objective == (0, 80, 11, 0)
    assert independently_valid(tasks, offers, result["assignments"])
    assert tuple(result["objectives"]) == oracle.objective
