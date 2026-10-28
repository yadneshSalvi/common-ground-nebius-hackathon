"""V2 interactive and service routes reuse distinct existing capabilities."""
from pathlib import Path
from typing import Literal
from fastapi import BackgroundTasks,Request
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from pydantic import BaseModel,ConfigDict,Field,StrictBool,StrictInt
from broker.engine import BrokerError
from broker.living import LivingEngine


class Input(BaseModel):
    model_config=ConfigDict(extra="forbid")


class DraftInput(Input):
    source_text:str=Field(min_length=1,max_length=16000)
    provider:Literal["local","fireworks","nebius"]
    allow_inference:StrictBool


class ConfirmInput(Input):
    goal:dict
    expected_revision:StrictInt=Field(ge=1)


class PlanInput(Input):
    provider:Literal["local","fireworks","nebius"]
    expected_revision:StrictInt=Field(ge=1)


class RevisionInput(Input):
    expected_revision:StrictInt=Field(ge=1)


class ExecuteInput(Input):
    agreement_id:str=Field(min_length=1,max_length=128)
    revision:StrictInt=Field(ge=1)


class SampleInput(Input):
    provider:Literal["none","fireworks","nebius"]="none"
    enable_policy:StrictBool=False


class MessageInput(Input):
    message:dict


def mount_living_routes(app,engine):
    living=LivingEngine(engine); app.state.living=living
    @app.post("/sample/session")
    def sample_session(request:Request):
        if engine.config.get("fictional_sample") is not True:
            raise BrokerError("Fictional sessions are unavailable for this installation.",404)
        if request.headers.get("origin")!=engine.config.get("origin","http://127.0.0.1:4301"):
            raise BrokerError("An exact shared-room Origin is required for fictional entry.",403)
        result=engine.pair(engine.config["pair_code"])
        return {**result,"role":"fictional-coordinator","sample":True,"authority":"fictional-sample-only"}

    @app.get("/recorded")
    def recorded():
        import json
        path=Path(__file__).resolve().parents[1]/"evidence"/"sample-proof.json"
        return JSONResponse({"historical":True,"current_state_available":False,"description":"Recorded legacy authored agreement. Expired authority is not reactivated.","evidence":json.loads(path.read_text())})

    @app.get("/api/v2/state")
    def state():
        return living.public_state()

    @app.post("/api/v2/sample")
    def sample(payload:SampleInput):
        return living.sample(payload.provider,payload.enable_policy)

    @app.post("/api/v2/goal/draft",status_code=202)
    def draft(payload:DraftInput,background:BackgroundTasks):
        result=living.begin("goal",payload.provider,source_text=payload.source_text,allow_inference=payload.allow_inference)
        background.add_task(living.run)
        return result

    @app.post("/api/v2/goal/confirm")
    def confirm(payload:ConfirmInput):
        return living.confirm_goal(payload.goal,payload.expected_revision)

    @app.post("/api/v2/plan",status_code=202)
    def plan(payload:PlanInput,background:BackgroundTasks):
        result=living.begin("repair",payload.provider,payload.expected_revision)
        background.add_task(living.run)
        return result

    @app.post("/api/v2/cancel")
    def cancel(payload:RevisionInput):
        return living.cancel(payload.expected_revision)

    @app.post("/api/v2/execute")
    def execute(payload:ExecuteInput):
        return living.execute(payload.agreement_id,payload.revision)

    @app.post("/api/v2/reconcile")
    def reconcile(payload:ExecuteInput):
        return living.execute(payload.agreement_id,payload.revision,reconcile=True)

    @app.get("/api/v2/evidence")
    def evidence():
        return JSONResponse(living.evidence(),headers={"Content-Disposition":"attachment; filename=common-ground-living-proof.json"})

    @app.get("/api/v2/verifier")
    def verifier():
        path=Path(__file__).resolve().parents[1]/"scripts"/"verify_living_evidence.py"
        return Response(path.read_text(),media_type="text/x-python",headers={"Content-Disposition":"attachment; filename=verify_living_evidence.py"})

    @app.post("/v2/releases")
    def release(payload:MessageInput):
        return living.ingest(payload.message,"LivingRelease")

    @app.post("/v2/consents")
    def consent(payload:MessageInput):
        return living.ingest(payload.message,"LivingConsent")

    @app.post("/v2/withdrawals")
    def withdrawal(payload:MessageInput):
        return living.ingest(payload.message,"LivingWithdrawal")

    @app.post("/v2/refusals")
    def refusal(payload:MessageInput):
        return living.ingest(payload.message,"LivingRefusal")

    @app.get("/v2/current")
    def current():
        return living.current()

    @app.get("/v2/agreements/{agreement_id}/{revision}")
    def agreement(agreement_id:str,revision:int):
        return living.current(agreement_id,revision)
