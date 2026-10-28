"""Bounded v2 CP-SAT scheduling over confirmed facts and released conditions."""
from itertools import combinations
from ortools.sat.python import cp_model
from shared.living import absolute_minute, travel_minutes, validate_goal, validate_release

SETTINGS = {"random_seed": 7, "num_search_workers": 1, "max_seconds_per_objective": 5, "objectives": ["preserve_existing_commitments", "maximize_optional_coverage", "balance_owner_minutes", "confirmed_travel_and_waiting", "model_suggestions"]}


def solve(goal, offers, previous=None, suggestions=None, max_seconds=5):
    goal = validate_goal(goal)
    offers = [validate_release(o) for o in offers]
    model = cp_model.CpModel()
    tasks = {t["task_id"]: t for t in goal["tasks"]}
    owners = sorted(goal["participants"])
    start, end, used, choices = {}, {}, {}, {}
    intervals = {o: [] for o in owners}
    previous = {c["task_id"]: c for c in previous or []}
    suggestions = {s["task_id"]: s.get("owner_id") for s in suggestions or []}
    def fail(status, reason, uncovered=None):
        return {"status": status, "assignments": [], "reason": reason, "uncovered_task_ids": uncovered or [], "settings": SETTINGS, "scope": "Current released offers and confirmed facts only"}
    for tid, task in tasks.items():
        earliest = absolute_minute(task["date"], task["earliest"])
        latest = absolute_minute(task["date"], task["latest"])
        start[tid] = model.new_int_var(earliest, latest-task["duration"], "start_"+tid)
        end[tid] = model.new_int_var(earliest+task["duration"], latest, "end_"+tid)
        model.add(end[tid] == start[tid]+task["duration"])
        used[tid] = model.new_bool_var("used_"+tid)
        if task["required"]:
            model.add(used[tid] == 1)
        available = []
        for n, offer in enumerate(offers):
            if tid not in offer["task_ids"] or offer["owner_id"] not in owners:
                continue
            windows = [w for w in offer["windows"] if w["date"] == task["date"] and max(w["start"],task["earliest"])+task["duration"] <= min(w["end"],task["latest"])]
            for windex, window in enumerate(windows):
                selected = model.new_bool_var(f"choose_{tid}_{n}_{windex}")
                key = (tid, n, windex)
                choices[key] = selected
                available.append(selected)
                model.add(start[tid] >= absolute_minute(task["date"],window["start"])).only_enforce_if(selected)
                model.add(end[tid] <= absolute_minute(task["date"],window["end"])).only_enforce_if(selected)
                intervals[offer["owner_id"]].append(model.new_optional_interval_var(start[tid],task["duration"],end[tid],selected,f"interval_{tid}_{n}_{windex}"))
                if tid in suggestions:
                    model.add_hint(selected,int(offer["owner_id"]==suggestions[tid]))
        if not available and task["required"]:
            return fail("INFEASIBLE",f"{task['label']} needs an offer. Ask for human help; no private limit will be relaxed.",[tid])
        model.add(sum(available) == used[tid])
    for tid, task in tasks.items():
        for predecessor in task["predecessors"]:
            model.add(used[tid] <= used[predecessor])
            model.add(end[predecessor] <= start[tid]).only_enforce_if(used[tid])
    for values in intervals.values():
        model.add_no_overlap(values)
    own_task = {}
    for tid in tasks:
        for owner in owners:
            selected = model.new_bool_var(f"owner_{tid}_{owner}")
            model.add(selected == sum(v for (task_id,n,w),v in choices.items() if task_id==tid and offers[n]["owner_id"]==owner))
            own_task[tid,owner] = selected
    for (tid,n,w),selected in choices.items():
        offer = offers[n]
        for condition in offer["conditions"]:
            if condition["task_id"] != tid:
                continue
            receiver = condition["receiver_task_id"]
            if receiver not in tasks or condition["receiver_id"] not in owners or tasks[receiver]["date"] != tasks[tid]["date"]:
                model.add(selected == 0)
                continue
            model.add(own_task[receiver,condition["receiver_id"]] == 1).only_enforce_if(selected)
            model.add(end[receiver] <= absolute_minute(tasks[tid]["date"],condition["by"])).only_enforce_if(selected)
            model.add(start[receiver] >= end[tid]).only_enforce_if(selected)
    # Actual adjacent commitments determine travel, not every pair or earliest
    # task-window order. Unknown directional routes have no successor arc.
    transfer_terms=[]
    task_list=list(tasks.values())
    for owner in owners:
        active=model.new_bool_var("path_active_"+owner)
        count=sum(own_task[t["task_id"],owner] for t in task_list)
        model.add(count>=active); model.add(count<=len(task_list)*active)
        arcs=[(0,0,active.Not())]
        for node,t in enumerate(task_list,1):
            chosen=own_task[t["task_id"],owner]
            arcs.append((node,node,chosen.Not()))
            first=model.new_bool_var(f"first_{owner}_{node}"); last=model.new_bool_var(f"last_{owner}_{node}")
            model.add_implication(first,chosen); model.add_implication(last,chosen)
            arcs.extend([(0,node,first),(node,0,last)])
        for ln,left in enumerate(task_list,1):
            for rn,right in enumerate(task_list,1):
                if ln==rn:
                    continue
                travel=travel_minutes(goal,left["end_location"],right["start_location"])
                if travel is None:
                    continue
                successor=model.new_bool_var(f"next_{owner}_{ln}_{rn}")
                model.add_implication(successor,own_task[left["task_id"],owner]); model.add_implication(successor,own_task[right["task_id"],owner])
                model.add(end[left["task_id"]]+travel<=start[right["task_id"]]).only_enforce_if(successor)
                arcs.append((ln,rn,successor)); transfer_terms.append(successor*travel)
        model.add_circuit(arcs)
    changed = []
    for tid,prior in previous.items():
        if tid not in tasks or prior["owner_id"] not in owners:
            continue
        kept = model.new_bool_var("kept_"+tid)
        model.add_implication(kept,own_task[tid,prior["owner_id"]])
        model.add(start[tid] == absolute_minute(prior["date"],prior["start"])).only_enforce_if(kept)
        changed.append(1-kept)
    optional_omitted = sum(1-used[t["task_id"]] for t in tasks.values() if not t["required"])
    max_load = model.new_int_var(0,sum(t["duration"] for t in tasks.values()),"max_owner_minutes")
    for owner in owners:
        model.add(max_load >= sum(own_task[t["task_id"],owner]*t["duration"] for t in tasks.values()))
    waiting = sum(start[t["task_id"]]-absolute_minute(t["date"],t["earliest"]) for t in tasks.values())
    model_deviations = sum(v for (tid,n,w),v in choices.items() if suggestions.get(tid) is not None and offers[n]["owner_id"] != suggestions[tid])
    solver = cp_model.CpSolver()
    solver.parameters.random_seed = 7
    solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = max_seconds
    values=[]
    for objective in (sum(changed),optional_omitted,max_load,waiting+sum(transfer_terms),model_deviations):
        model.minimize(objective)
        status = solver.solve(model)
        if status not in (cp_model.OPTIMAL,cp_model.FEASIBLE):
            return fail(solver.status_name(status),"No complete arrangement was established under current offers and confirmed travel. Ask for human help." if status != cp_model.UNKNOWN else "The bounded solver did not finish. Feasibility remains unknown.")
        value=int(solver.value(objective)); values.append(value)
        if status == cp_model.FEASIBLE:
            break
        model.add(objective == value)
    assignments=[]
    for (tid,n,w),chosen in choices.items():
        if solver.boolean_value(chosen):
            task,offer=tasks[tid],offers[n]
            midnight=absolute_minute(task["date"],0)
            assignments.append({"task_id":tid,"owner_id":offer["owner_id"],"date":task["date"],"start":solver.value(start[tid])-midnight,"end":solver.value(end[tid])-midnight,"offer_id":offer["offer_id"],"offer_revision":offer["offer_revision"]})
    return {"status":solver.status_name(status),"assignments":sorted(assignments,key=lambda a:(a["date"],a["start"],a["task_id"])),"objectives":values,"settings":{**SETTINGS,"max_seconds_per_objective":max_seconds},"scope":"Current released offers and confirmed facts only"}
