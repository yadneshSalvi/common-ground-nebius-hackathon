"""Independent ordinary-Python v2 checker. It does not import CP-SAT/solver."""
from collections import defaultdict
from shared.living import absolute_minute, travel_minutes, validate_goal, validate_release


def check(goal, offers, assignments):
    errors=[]
    try:
        goal=validate_goal(goal)
        offers=[validate_release(o) for o in offers]
    except (ValueError,TypeError) as exc:
        return {"valid":False,"errors":["Invalid reviewed goal or public release contract."],"checks":[]}
    tasks={t["task_id"]:t for t in goal["tasks"]}
    assigned={a.get("task_id"):a for a in assignments}
    released={o["offer_id"]:o for o in offers}
    if len(assigned)!=len(assignments) or set(assigned)-set(tasks) or any(t["required"] and tid not in assigned for tid,t in tasks.items()):
        errors.append("Required coverage or unique task assignment failed.")
    own=defaultdict(list)
    for assignment in assignments:
        try:
            tid=assignment["task_id"]; task=tasks[tid]; offer=released[assignment["offer_id"]]
            if assignment["owner_id"] != offer["owner_id"] or assignment["owner_id"] not in goal["participants"] or assignment["offer_revision"] != offer["offer_revision"] or tid not in offer["task_ids"]:
                errors.append("Assignment exceeds its registered signed release.")
            start,end=assignment["start"],assignment["end"]
            if type(start) is not int or type(end) is not int or assignment["date"] != task["date"] or end-start != task["duration"] or start<task["earliest"] or end>task["latest"]:
                errors.append("Assignment changes a confirmed date, duration or window.")
                continue
            if not any(w["date"]==task["date"] and w["start"]<=start and end<=w["end"] for w in offer["windows"]):
                errors.append("Assignment is outside released availability.")
            for predecessor in task["predecessors"]:
                prior=assigned.get(predecessor)
                if prior is None or absolute_minute(prior["date"],prior["end"])>absolute_minute(task["date"],start):
                    errors.append("A required dependency is missing or late.")
            for condition in offer["conditions"]:
                if condition["task_id"]!=tid:
                    continue
                receiver=assigned.get(condition["receiver_task_id"])
                if not receiver or receiver["owner_id"]!=condition["receiver_id"] or receiver["date"]!=task["date"] or receiver["end"]>condition["by"] or receiver["start"]<end:
                    errors.append("An owner-reviewed conditional handoff is not satisfied.")
            own[assignment["owner_id"]].append(assignment)
        except (KeyError,TypeError,ValueError):
            errors.append("Malformed assignment or unknown reference.")
    for values in own.values():
        ordered=sorted(values,key=lambda a:(a["date"],a["start"],a["end"]))
        for previous,current in zip(ordered,ordered[1:]):
            travel=travel_minutes(goal,tasks[previous["task_id"]]["end_location"],tasks[current["task_id"]]["start_location"])
            if travel is None:
                errors.append("Travel duration is unknown; it cannot be invented.")
            elif absolute_minute(previous["date"],previous["end"])+travel>absolute_minute(current["date"],current["start"]):
                errors.append("Owner capacity or confirmed transfer duration is violated.")
    subjects=defaultdict(list)
    for assignment in assignments:
        if assignment.get("task_id") in tasks and all(k in assignment for k in ("date","start","end")):
            subjects[(tasks[assignment["task_id"]]["subject"],assignment["date"])].append(assignment)
    for values in subjects.values():
        ordered=sorted(values,key=lambda a:(a["start"],a["end"]))
        for previous,current in zip(ordered,ordered[1:]):
            if previous["end"]>current["start"] or tasks[previous["task_id"]]["end_location"]!=tasks[current["task_id"]]["start_location"]:
                errors.append("The care recipient overlaps activities or lacks an explicit journey.")
    return {"valid":not errors,"errors":list(dict.fromkeys(errors)),"checks":["registered owners","reviewed source-linked facts","complete required coverage","released task scope and windows","exact dates/durations","recipient continuity","dependency ordering","confirmed owner travel","conditional handoff","capacity one"],"scope":"Current released offers; owners independently recheck private state"}
