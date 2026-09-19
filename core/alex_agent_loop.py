"""ALEX user-facing agent loop built on the existing NEXO Manager/Router/Security/Planner stack."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable
import re
import uuid
from agents.manager.manager import NexoManager
from services.security.guardrails import inspect as inspect_security
from services.security.permissions import inspect_request

class Decision(str, Enum):
    ANSWER="ANSWER"; INSPECT="INSPECT"; EXECUTE="EXECUTE"; MULTI_STEP_TASK="MULTI_STEP_TASK"; CLARIFICATION="CLARIFICATION"; CONFIRMATION="CONFIRMATION"
class Risk(str, Enum):
    LOW="LOW"; MEDIUM="MEDIUM"; HIGH="HIGH"; CRITICAL="CRITICAL"

@dataclass
class Understanding:
    request:str; intent:str; target:str=""; desired_outcome:str=""; constraints:list[str]=field(default_factory=list)
    context:dict[str,Any]=field(default_factory=dict); risk:Risk=Risk.LOW; required_capabilities:list[str]=field(default_factory=list); autonomy:str="unspecified"

@dataclass
class Analysis:
    understanding:Understanding; problem:str; available_information:list[str]; missing_information:list[str]
    required_tools:list[str]; safe:bool; confirmation_required:bool; verification_method:str; security:dict[str,Any]

@dataclass
class DecisionResult:
    decision:Decision; reason:str; analysis:Analysis

def understand(request:str, manager:NexoManager|None=None)->Understanding:
    value=(request or "").strip(); mgr=manager or NexoManager(); task=mgr.create_task(value); lower=value.lower()
    target=""
    app=re.search(r"\b(youtube|telegram|whatsapp|chrome|instagram|settings|calculator)\b",lower)
    if app: target=app.group(1)
    elif "omnix" in lower: target="OMNIX"
    desired=value
    if any(x in lower for x in ("open ","launch ","khol","kholo")): desired=f"open {target}" if target else value
    elif any(x in lower for x in ("fix","repair","solve","debug")): desired=f"working {target}" if target else value
    risk=Risk.LOW
    if any(x in lower for x in ("send","delete","payment","install","uninstall","account","password","credential")): risk=Risk.HIGH
    if any(x in lower for x in ("factory reset","wipe","format","destroy","permanently delete")): risk=Risk.CRITICAL
    capabilities=[]
    if target in {"youtube","telegram","whatsapp","chrome","instagram","settings","calculator"}: capabilities.append("android_app_control")
    if any(x in lower for x in ("screen","what do you see","look at","button","dialog")): capabilities.append("screen_context")
    if any(x in lower for x in ("fix","repair","debug","deploy")): capabilities.extend(["repository_inspection","testing","verification"])
    return Understanding(value,task.intent,target,desired,[],{"manager_agent":task.agent,"complexity":mgr.complexity_signals(value)},risk,capabilities,"explicit" if any(x in lower for x in ("do ","open ","fix ","send ","restart ","run ")) else "unspecified")

def analyse(u:Understanding,*,user_id:int|str|None=None,owner_id:int|None=None)->Analysis:
    security=inspect_security(u.request); permission=inspect_request(u.request,user_id,owner_id); tools=[]
    if "android_app_control" in u.required_capabilities: tools.append("app_open")
    if "screen_context" in u.required_capabilities: tools.append("screen_analyze")
    missing=["explicit_confirmation"] if u.risk in {Risk.HIGH,Risk.CRITICAL} else []
    verification="foreground_application_observation" if "android_app_control" in u.required_capabilities else "registered_tool_verified_result"
    if "screen_context" in u.required_capabilities: verification="screen_capture_and_observation"
    return Analysis(u,u.request,["user_request","nexo_manager_classification"],missing,tools,bool(security.get("safe")) and bool(permission.get("safe")),u.risk in {Risk.HIGH,Risk.CRITICAL},verification,{"guardrails":security,"permissions":permission})

def decide(a:Analysis)->DecisionResult:
    text=a.understanding.request.lower()
    if not a.safe: return DecisionResult(Decision.CLARIFICATION,"Security or permission gate rejected the request.",a)
    if not text: return DecisionResult(Decision.CLARIFICATION,"No actionable request was supplied.",a)
    if a.confirmation_required: return DecisionResult(Decision.CONFIRMATION,"The requested action has elevated impact.",a)
    if any(x in text for x in ("fix ","repair ","deploy","build","migrate","do all")) or a.understanding.context["complexity"].get("reasoning_heavy"): return DecisionResult(Decision.MULTI_STEP_TASK,"The request needs planning and verification.",a)
    if any(x in text for x in ("check","inspect","why ","status","diagnose")): return DecisionResult(Decision.INSPECT,"The request is primarily read-only investigation.",a)
    if a.understanding.intent=="conversation": return DecisionResult(Decision.ANSWER,"No execution capability is required.",a)
    if a.understanding.required_capabilities: return DecisionResult(Decision.EXECUTE,"A registered capability can perform the requested action.",a)
    return DecisionResult(Decision.ANSWER,"No registered execution capability was identified.",a)

class AlexAgentLoop:
    """Thin ALEX layer. NEXO remains the only manager/router/security/planner authority."""
    def __init__(self,manager:NexoManager|None=None): self.manager=manager or NexoManager()
    def inspect(self,request:str,*,user_id:int|str|None=None,owner_id:int|None=None)->DecisionResult:
        u=understand(request,self.manager); return decide(analyse(u,user_id=user_id,owner_id=owner_id))
