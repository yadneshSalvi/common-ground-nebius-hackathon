"""Explicit fictional authored source; dates and durations are never inferred."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import uuid
from shared.protocol import utc_now
from shared.living import validate_goal


def sample_goal(sequence=0):
    day=(datetime.now(ZoneInfo("Asia/Kolkata")).date()+timedelta(days=5+sequence)).isoformat()
    source=(f"Fictional reviewed request for {day}, Asia/Kolkata. Asha, Ravi and Leena are the participating owners. Dev is the care recipient. "
            "Prepare Dev at home from 12:20 to 12:40 (20 minutes). Ravi can drive pickup and return. "
            "Drive Dev from home to clinic from 13:10 to 13:50 (40 minutes). Stay with Dev at the clinic from 13:50 to 15:20 (90 minutes). "
            "Drive Dev from clinic to home from 15:20 to 16:00 (40 minutes). Receive Dev at home from 16:00 to 16:15 (15 minutes). "
            "These five responsibilities form that required sequence. The explicitly confirmed travel time is 40 minutes in each direction between home and clinic. "
            "Asha prepares and receives Dev, Ravi initially drives both ways, and Leena accompanies him. All people, dates and decisions in this rehearsal are fictional.")
    facts=[("prepare","Get ready at home","preparation",740,760,"home","home",[]),
           ("outbound","Take Dev to the appointment","driving",790,830,"home","clinic",["prepare"]),
           ("accompany","Stay with Dev at the appointment","accompaniment",830,920,"clinic","clinic",["outbound"]),
           ("return","Bring Dev home","driving",920,960,"clinic","home",["accompany"]),
           ("handoff","Receive Dev at home","handoff",960,975,"home","home",["return"])]
    return validate_goal({"schema_version":2,"goal_id":"care-"+uuid.uuid4().hex[:20],"revision":1,"title":"Dev’s afternoon appointment","description":"A fictional care arrangement that can be repaired without asking Asha to drive.","timezone":"Asia/Kolkata","participants":["asha","ravi","leena"],"subject":"Dev","source_text":source,"tasks":[{"task_id":tid,"label":label,"capability":cap,"date":day,"duration":end-start,"earliest":start,"latest":end,"start_location":origin,"end_location":destination,"predecessors":prior,"required":True,"subject":"Dev","source_quote":source} for tid,label,cap,start,end,origin,destination,prior in facts],"routes":[{"from_location":"home","to_location":"clinic","duration":40,"source_quote":"The explicitly confirmed travel time is 40 minutes in each direction between home and clinic."},{"from_location":"clinic","to_location":"home","duration":40,"source_quote":"The explicitly confirmed travel time is 40 minutes in each direction between home and clinic."}],"confirmed_at":utc_now(),"confirmed_by":"authored-fictional-sample"})
