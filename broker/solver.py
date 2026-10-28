"""Single-worker, deterministic, lexicographic CP-SAT scheduling over released data."""
from __future__ import annotations
from itertools import combinations
from ortools.sat.python import cp_model

SETTINGS = {"random_seed": 7, "num_search_workers": 1, "max_time_in_seconds_per_objective": 5.0, "objective_order": ["changed_existing_assignments", "weighted_minutes_plus_max_owner_load", "transfer_minutes_plus_start_delay", "model_suggestion_deviations"]}


def solve(tasks: list[dict], offers: list[dict], previous: list[dict] | None = None, max_seconds: float = 5.0, suggestions: list[dict] | None = None) -> dict:
    model = cp_model.CpModel()
    starts, ends, choice = {}, {}, {}
    intervals: dict[str, list] = {}
    previous_owner = {a["task_id"]: a["owner_id"] for a in previous or []}
    suggested_owner = {a["task_id"]: a["owner_id"] for a in suggestions or []}
    owners = sorted({o["owner_id"] for o in offers})
    tasks_sorted = sorted(tasks, key=lambda t: (t["earliest"], t["task_id"]))
    for task in tasks:
        tid = task["task_id"]
        if task["earliest"] + task["duration"] > task["latest"]:
            return {"status": "INFEASIBLE", "assignments": [], "objectives": [], "settings": SETTINGS, "reason": "A confirmed task has no legal interval."}
        starts[tid] = model.new_int_var(task["earliest"], task["latest"] - task["duration"], f"start_{tid}")
        ends[tid] = model.new_int_var(task["earliest"] + task["duration"], task["latest"], f"end_{tid}")
        model.add(ends[tid] == starts[tid] + task["duration"])
        eligible = []
        for index, offer in enumerate(offers):
            if tid not in offer["task_ids"] or task["capability"] not in offer["capabilities"]:
                continue
            if offer["capacity"] != 1:
                return {"status": "MODEL_INVALID", "assignments": [], "objectives": [], "settings": SETTINGS, "reason": "Only explicit owner capacity one is supported."}
            selected = model.new_bool_var(f"use_{tid}_{index}")
            choice[tid, index] = selected
            if tid in suggested_owner:
                model.add_hint(selected, int(offer["owner_id"] == suggested_owner[tid]))
            eligible.append(selected)
            model.add(starts[tid] >= offer["start"]).only_enforce_if(selected)
            model.add(ends[tid] <= offer["end"]).only_enforce_if(selected)
            interval = model.new_optional_interval_var(starts[tid], task["duration"], ends[tid], selected, f"interval_{tid}_{index}")
            intervals.setdefault(offer["owner_id"], []).append(interval)
        if not eligible:
            responsibility = {"prepare": "getting ready at home", "outbound": "the trip to the clinic", "accompany": "staying with Dev during the appointment", "return": "the trip home", "handoff": "welcoming Dev home"}.get(tid, "a required responsibility")
            return {"status": "INFEASIBLE", "assignments": [], "objectives": [], "settings": SETTINGS, "reason": f"The current offers don’t cover {responsibility}. Someone can review and release an offer for that responsibility.", "scope": "Current released offers only; not a claim of global infeasibility.", "uncovered_task_id": tid}
        model.add_exactly_one(eligible)
    for task in tasks:
        for prior in task["predecessors"]:
            if prior not in ends:
                return {"status": "MODEL_INVALID", "assignments": [], "objectives": [], "settings": SETTINGS, "reason": "Unknown predecessor."}
            model.add(ends[prior] <= starts[task["task_id"]])
    for owner_intervals in intervals.values():
        model.add_no_overlap(owner_intervals)
    # Pairwise direction variables enforce actual transfer feasibility even for non-chain inputs.
    for left, right in combinations(tasks, 2):
        l, r = left["task_id"], right["task_id"]
        for li, lo in enumerate(offers):
            for ri, ro in enumerate(offers):
                if lo["owner_id"] != ro["owner_id"] or (l, li) not in choice or (r, ri) not in choice:
                    continue
                before = model.new_bool_var(f"before_{l}_{r}_{li}_{ri}")
                transfer_lr = 0 if left["location"].split("→")[-1] == right["location"].split("→")[0] else 40
                transfer_rl = 0 if right["location"].split("→")[-1] == left["location"].split("→")[0] else 40
                model.add(ends[l] + transfer_lr <= starts[r]).only_enforce_if([choice[l, li], choice[r, ri], before])
                model.add(ends[r] + transfer_rl <= starts[l]).only_enforce_if([choice[l, li], choice[r, ri], before.Not()])
    changes = sum(v for (tid, i), v in choice.items() if tid in previous_owner and offers[i]["owner_id"] != previous_owner[tid])
    weighted_minutes = sum(v * next(t["duration"] for t in tasks if t["task_id"] == tid) * (1 + offers[i]["preference_cost"]) for (tid, i), v in choice.items())
    max_load = model.new_int_var(0, sum(t["duration"] for t in tasks), "max_owner_minutes")
    for owner in owners:
        load = sum(v * next(t["duration"] for t in tasks if t["task_id"] == tid) for (tid, i), v in choice.items() if offers[i]["owner_id"] == owner)
        model.add(max_load >= load)
    # Each owner's selected tasks form one temporal path through a dummy
    # node. Unlike sorting task windows, actual successor arcs remain correct
    # when a flexible task runs after a task whose earliest start is later.
    transfer_terms = []
    for owner in owners:
        owner_choices = {}
        for task in tasks:
            tid = task["task_id"]
            own = [v for (t, i), v in choice.items() if t == tid and offers[i]["owner_id"] == owner]
            flag = model.new_bool_var(f"assigned_{owner}_{tid}")
            model.add(flag == sum(own))
            owner_choices[tid] = flag
        active = model.new_bool_var(f"active_path_{owner}")
        selected_count = sum(owner_choices.values())
        model.add(selected_count >= active)
        model.add(selected_count <= len(tasks) * active)
        # Inactive tasks use self-loops. The dummy self-loop is selected only
        # for an unused owner; otherwise it breaks the temporal path's cycle.
        arcs = [(0, 0, active.Not())]
        for node, task in enumerate(tasks, start=1):
            flag = owner_choices[task["task_id"]]
            arcs.append((node, node, flag.Not()))
            first = model.new_bool_var(f"path_first_{owner}_{node}")
            last = model.new_bool_var(f"path_last_{owner}_{node}")
            model.add_implication(first, flag)
            model.add_implication(last, flag)
            arcs.extend([(0, node, first), (node, 0, last)])
        for left_node, left in enumerate(tasks, start=1):
            for right_node, right in enumerate(tasks, start=1):
                if left_node == right_node:
                    continue
                successor = model.new_bool_var(f"path_next_{owner}_{left_node}_{right_node}")
                model.add_implication(successor, owner_choices[left["task_id"]])
                model.add_implication(successor, owner_choices[right["task_id"]])
                transfer = 0 if left["location"].split("→")[-1] == right["location"].split("→")[0] else 40
                model.add(ends[left["task_id"]] + transfer <= starts[right["task_id"]]).only_enforce_if(successor)
                arcs.append((left_node, right_node, successor))
                if transfer:
                    transfer_terms.append(successor * transfer)
        model.add_circuit(arcs)
    waiting = sum(starts[t["task_id"]] - t["earliest"] for t in tasks)
    model_deviations = sum(v for (tid, i), v in choice.items() if tid in suggested_owner and offers[i]["owner_id"] != suggested_owner[tid])
    objectives = [changes, weighted_minutes + max_load, sum(transfer_terms) + waiting, model_deviations]
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = 7
    solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = max_seconds
    values: list[int] = []
    status = cp_model.UNKNOWN
    for objective in objectives:
        model.minimize(objective)
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return {"status": solver.status_name(status), "assignments": [], "objectives": values, "settings": {**SETTINGS, "max_time_in_seconds_per_objective": max_seconds}, "reason": "Search did not establish a feasible plan." if status == cp_model.UNKNOWN else "No plan satisfies the current released offers."}
        value = int(solver.value(objective))
        values.append(value)
        if status == cp_model.FEASIBLE:
            break
        model.add(objective == value)
    assignments = []
    for task in tasks_sorted:
        tid = task["task_id"]
        for i, offer in enumerate(offers):
            if (tid, i) in choice and solver.boolean_value(choice[tid, i]):
                assignments.append({"task_id": tid, "owner_id": offer["owner_id"], "start": solver.value(starts[tid]), "end": solver.value(ends[tid]), "offer_id": offer["offer_id"], "offer_revision": offer["revision"]})
    return {"status": solver.status_name(status), "assignments": assignments, "objectives": values, "settings": {**SETTINGS, "max_time_in_seconds_per_objective": max_seconds}, "lexicographic_optimal": status == cp_model.OPTIMAL and len(values) == 4}
