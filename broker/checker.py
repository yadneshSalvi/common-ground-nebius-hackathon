"""Independent, ordinary-Python verifier; deliberately does not import the solver."""
from __future__ import annotations
from itertools import combinations


def verify_assignments(tasks: list[dict], offers: list[dict], assignments: list[dict]) -> dict:
    errors: list[str] = []
    checks: list[str] = []
    task_by_id = {t["task_id"]: t for t in tasks}
    offer_by_id = {o["offer_id"]: o for o in offers}
    assigned = {a["task_id"]: a for a in assignments}
    if len(task_by_id) != len(tasks) or len(assignments) != len(tasks) or set(assigned) != set(task_by_id):
        errors.append("Each confirmed responsibility must be assigned exactly once.")
    checks.append("complete task coverage")
    for item in assignments:
        task = task_by_id.get(item.get("task_id"))
        offer = offer_by_id.get(item.get("offer_id"))
        if not task or not offer:
            errors.append("Assignment references an unknown task or released offer.")
            continue
        if item.get("owner_id") != offer["owner_id"] or item.get("offer_revision") != offer["revision"]:
            errors.append("Assignment owner/offer revision does not match the signed release.")
        if task["task_id"] not in offer["task_ids"] or task["capability"] not in offer["capabilities"]:
            errors.append("An assignment exceeds the released task/capability scope.")
        start, end = item.get("start"), item.get("end")
        if type(start) is not int or type(end) is not int:
            errors.append("Assignment times must be integer minutes.")
            continue
        if end - start != task["duration"]:
            errors.append("A responsibility has the wrong duration.")
        if start < max(task["earliest"], offer["start"]) or end > min(task["latest"], offer["end"]):
            errors.append("A responsibility falls outside its task or released availability window.")
        for predecessor in task["predecessors"]:
            prior = assigned.get(predecessor)
            if not prior or prior["end"] > start:
                errors.append("A responsibility starts before its predecessor finishes.")
    checks.extend(["signed offer scope and revision", "task and availability windows", "exact durations", "precedence"])
    for left, right in combinations(assignments, 2):
        if left.get("owner_id") != right.get("owner_id"):
            continue
        first, second = sorted([left, right], key=lambda a: a["start"])
        if first["task_id"] not in task_by_id or second["task_id"] not in task_by_id:
            continue
        if first["end"] > second["start"]:
            errors.append("An owner has overlapping responsibilities beyond capacity one.")
        def endpoints(location: str) -> tuple[str, str]:
            parts = location.split("→")
            return parts[0], parts[-1]
        origin = endpoints(task_by_id[first["task_id"]]["location"])[1]
        destination = endpoints(task_by_id[second["task_id"]]["location"])[0]
        travel = 0 if origin == destination else 40
        if first["end"] + travel > second["start"]:
            errors.append("An owner has insufficient travel time between responsibilities.")
    checks.extend(["owner interval capacity", "between-task travel buffers"])
    return {"valid": not errors, "checks": checks, "errors": list(dict.fromkeys(errors)), "scope": "Released offers only; each owner must independently validate private current state."}
