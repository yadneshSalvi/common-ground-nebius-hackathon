from copy import deepcopy
from datetime import date,timedelta
import pytest
from broker.living_sample import sample_goal
from broker.living_solver import solve
from broker.living_checker import check
from shared.living import validate_goal,goal_digest
from shared.protocol import expires_in


def offer(goal,owner,tasks):
    return {"goal_id":goal["goal_id"],"goal_revision":goal["revision"],"goal_digest":goal_digest(goal),"offer_id":"offer-"+owner,"offer_revision":1,"owner_id":owner,"constraint_revision":1,"task_ids":tasks,"windows":[{"date":d,"start":0,"end":1440} for d in sorted({t["date"] for t in goal["tasks"]})],"conditions":[],"recipients":{"humans":goal["participants"],"broker":"common-ground-broker","inference":[]},"request_categories":[],"expires_at":expires_in(14400)}


def test_recipient_cannot_be_in_two_places_with_different_owners():
    goal=sample_goal(); goal["tasks"]=goal["tasks"][:2]
    goal["tasks"][1].update(predecessors=[],capability="visit",start_location="clinic",end_location="clinic",duration=20,earliest=740,latest=760)
    with pytest.raises(ValueError,match="continuity"):
        validate_goal(goal)
    offers=[offer(goal,"asha",["prepare"]),offer(goal,"ravi",["outbound"])]
    checked=check(goal,offers,[{"task_id":"prepare","owner_id":"asha","date":goal["tasks"][0]["date"],"start":740,"end":760,"offer_id":"offer-asha","offer_revision":1},{"task_id":"outbound","owner_id":"ravi","date":goal["tasks"][1]["date"],"start":740,"end":760,"offer_id":"offer-ravi","offer_revision":1}])
    assert not checked["valid"]


def test_new_two_day_accompaniment_and_meal_structure_without_driving():
    goal=sample_goal(); day=goal["tasks"][0]["date"]; next_day=(date.fromisoformat(day)+timedelta(days=1)).isoformat()
    source=f"Fictional reviewed source: {day} accompany Dev at home from10:00 to10:30 for30 minutes; {next_day} prepare a meal at home from11:00 to11:20 for20 minutes then hand the meal over at home from11:20 to11:30 for10 minutes. Asha and Leena participate."
    goal.update(participants=["asha","leena"],source_text=source,routes=[])
    def task(tid,cap,d,start,end,prior,subject):
        return {"task_id":tid,"label":tid,"capability":cap,"date":d,"duration":end-start,"earliest":start,"latest":end,"start_location":"home","end_location":"home","predecessors":prior,"required":True,"subject":subject,"source_quote":source}
    goal["tasks"]=[task("company","accompaniment",day,600,630,[],"Dev"),task("meal-prep","meal",next_day,660,680,[],"Meal"),task("meal-handoff","handoff",next_day,680,690,["meal-prep"],"Meal")]
    goal=validate_goal(goal)
    offers=[offer(goal,"asha",["meal-prep","meal-handoff"]),offer(goal,"leena",["company","meal-handoff"])]
    result=solve(goal,offers)
    assert result["status"]=="OPTIMAL" and len(result["assignments"])==3
    assert check(goal,offers,result["assignments"])["valid"]


def test_unconfirmed_route_and_cyclic_graph_fail_before_negotiation():
    goal=sample_goal(); goal["routes"]=[]
    with pytest.raises(ValueError,match="confirmed route"):
        validate_goal(goal)
    goal=sample_goal(); goal["tasks"][0]["predecessors"]=["handoff"]
    with pytest.raises(ValueError,match="Cyclic"):
        validate_goal(goal)


def test_solver_timeout_is_unknown_and_conditional_deadline_is_hard():
    goal=sample_goal()
    offers=[offer(goal,"asha",["prepare","handoff"]),offer(goal,"ravi",["outbound"]),offer(goal,"leena",["accompany","return"])]
    offers[-1]["conditions"]=[{"task_id":"return","receiver_id":"asha","receiver_task_id":"handoff","by":974}]
    result=solve(goal,offers)
    assert result["status"]=="INFEASIBLE"
    offers[-1]["conditions"][0]["by"]=975
    result=solve(goal,offers,max_seconds=0)
    assert result["status"]=="UNKNOWN"


def test_six_owners_twelve_confirmed_responsibilities():
    goal=sample_goal(); goal["participants"]=[f"owner{i}" for i in range(6)]
    source="Twelve fictional reviewed visits at home, each10 minutes starting at08:00, in the stated sequence; same confirmed date and home location."
    goal.update(source_text=source,routes=[])
    template=goal["tasks"][0]
    goal["tasks"]=[{**template,"task_id":f"visit{i}","label":f"Visit {i+1}","capability":"visit","duration":10,"earliest":480+10*i,"latest":490+10*i,"predecessors":[f"visit{i-1}"] if i else [],"source_quote":source} for i in range(12)]
    goal=validate_goal(goal)
    offers=[offer(goal,o,[t["task_id"] for t in goal["tasks"]]) for o in goal["participants"]]
    result=solve(goal,offers,max_seconds=2)
    assert result["status"] in ("OPTIMAL","FEASIBLE") and len(result["assignments"])==12
    assert check(goal,offers,result["assignments"])["valid"]


@pytest.mark.parametrize("day,start,end",[("2026-03-08",150,170),("2026-11-01",90,110),("2026-03-08",110,190)])
def test_clock_change_windows_require_explicit_unambiguous_review(day,start,end):
    goal=sample_goal(); goal["timezone"]="America/New_York"
    for task in goal["tasks"]:
        task["date"]=day
    goal["tasks"][0].update(earliest=start,latest=end)
    with pytest.raises(ValueError,match="ambiguous|offset"):
        validate_goal(goal)
