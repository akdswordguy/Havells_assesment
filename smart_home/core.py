"""Request interpreter, deterministic policy, and simulated device registry."""
from __future__ import annotations
import copy, hashlib, json, re, secrets, time
from typing import Any


class DeviceRegistry:
    def __init__(self):
        self.devices = {
            "ac-living": {"id":"ac-living","type":"ac","room":"living room","capabilities":["set_temperature","set_mode","set_power"],"state":{"power":False,"temperature_c":24,"mode":"cool"},"constraints":{"temperature_c":[18,30],"modes":["cool","heat","auto","off"]}},
            "fan-living": {"id":"fan-living","type":"fan","room":"living room","capabilities":["set_power","set_speed"],"state":{"power":False,"speed":1},"constraints":{"speed":[1,5]}},
            "light-living": {"id":"light-living","type":"light","room":"living room","capabilities":["set_power"],"state":{"power":True},"constraints":{}},
            "heater-bath": {"id":"heater-bath","type":"water_heater","room":"bathroom","capabilities":["set_power"],"state":{"power":False},"constraints":{"requires_fresh_water_level":True}},
            "lock-front": {"id":"lock-front","type":"door_lock","room":"entry","capabilities":["lock","unlock"],"state":{"locked":True},"constraints":{"unlock_roles":["owner"]}},
        }
        self.sensors = {"water_level_bath":{"value":82,"unit":"percent","observed_at":time.time(),"valid":True}}

    def snapshot(self): return copy.deepcopy({"devices":self.devices,"sensors":self.sensors})


class Interpreter:
    """Maps a small phrase vocabulary to proposals only; never executes commands."""
    def interpret(self, text: str):
        s=" ".join(text.lower().strip().split())
        def proposal(actions,intent): return {"status":"proposed","intent":intent,"actions":actions}
        if not s: return {"status":"ambiguous","reason":"Please describe what you want changed."}
        if any(x in s for x in ("unlock","open the door","open front")):
            return proposal([{"device_id":"lock-front","parameter":"locked","value":False}],"door unlock")
        if any(x in s for x in ("lock the door","lock front","secure the door")):
            return proposal([{"device_id":"lock-front","parameter":"locked","value":True}],"door lock")
        if "heater" in s and "water heater" not in s:
            return {"status":"ambiguous","reason":"Which heater do you mean? Please specify the water heater."}
        if "water heater" in s:
            if any(x in s for x in ("turn on","switch on","start","activate")):
                return proposal([{"device_id":"heater-bath","parameter":"power","value":True}],"water heater on")
            if any(x in s for x in ("turn off","switch off","stop","deactivate")):
                return proposal([{"device_id":"heater-bath","parameter":"power","value":False}],"water heater off")
            return {"status":"ambiguous","reason":"Specify whether to turn the water heater on or off."}
        if any(x in s for x in ("away for","vacation","leaving for","away a week")):
            actions=[{"device_id":"ac-living","parameter":"power","value":False},{"device_id":"fan-living","parameter":"power","value":False},{"device_id":"light-living","parameter":"power","value":False},{"device_id":"heater-bath","parameter":"power","value":False},{"device_id":"lock-front","parameter":"locked","value":True}]
            return proposal(actions,"away mode")
        if any(x in s for x in ("cooler","cool down","lower the temperature","less warm")):
            m=re.search(r"(?:to|at)\s+(\d{1,2})\s*(?:°\s*)?(?:c|degrees?)?",s)
            if m: target=int(m.group(1))
            elif any(x in s for x in ("make it cooler","cooler in here","cool down")): target=22
            else: return {"status":"ambiguous","reason":"Please specify a target temperature."}
            return proposal([{"device_id":"ac-living","parameter":"temperature_c","value":target},{"device_id":"ac-living","parameter":"power","value":True}],"cool room")
        if "light" in s and any(x in s for x in ("turn off","switch off","turn on","switch on")):
            on=not any(x in s for x in ("turn off","switch off"))
            return proposal([{"device_id":"light-living","parameter":"power","value":on}],"light toggle")
        return {"status":"ambiguous","reason":"I couldn't map that request to a supported device action."}


class SmartHomeAssistant:
    CONFIRM_TTL=300
    MAX_SENSOR_AGE=300
    ROLES={"owner":"owner","resident":"resident","guest":"guest"}
    def __init__(self,registry=None):
        self.registry=registry or DeviceRegistry(); self.interpreter=Interpreter(); self.confirmations={}; self.audit_log=[]
    def request(self,text,user_id="owner"):
        p=self.interpreter.interpret(text); self._log("interpreted",user_id,p)
        if p["status"]!="proposed": return {**p,"risk":"none"}
        return self.evaluate(p["actions"],user_id)
    def evaluate(self,actions,user_id):
        if not isinstance(actions,list) or not actions: return self._result("blocked","Proposal contains no actions.","high",user_id)
        if user_id not in self.ROLES: return self._result("blocked","Unknown or unauthorized user.","high",user_id)
        role=self.ROLES[user_id]; normalized=[]
        for a in actions:
            if not isinstance(a,dict) or set(a)!={"device_id","parameter","value"}: return self._result("blocked","Malformed action proposal.","high",user_id)
            d=self.registry.devices.get(a["device_id"])
            if d is None: return self._result("blocked","Unknown device.","high",user_id)
            p,v=a["parameter"],a["value"]
            capability={"power":"set_power" if d["type"]!="door_lock" else "unlock","locked":"lock","temperature_c":"set_temperature"}.get(p,p)
            if capability not in d["capabilities"]: return self._result("blocked","Unsupported device parameter.","high",user_id)
            if not self._valid(d,p,v): return self._result("blocked",f"Invalid value for {d['id']}.{p}.","high",user_id)
            if d["type"]=="door_lock" and p=="locked" and v is False and role not in d["constraints"]["unlock_roles"]:
                return self._result("blocked","Door unlocking is not authorized for this user.","high",user_id)
            if d["type"]=="water_heater" and p=="power" and v is True:
                sensor=self.registry.sensors.get("water_level_bath")
                if not sensor or not sensor.get("valid") or type(sensor.get("value")) not in (int,float) or not 0<=sensor["value"]<=100:
                    return self._result("blocked","Water-level evidence is missing or invalid; heater activation blocked.","high",user_id)
                if time.time()-sensor.get("observed_at",0)>self.MAX_SENSOR_AGE:
                    return self._result("blocked","Water-level evidence is stale; heater activation blocked.","high",user_id)
            normalized.append(copy.deepcopy(a))
        risk=self._risk(normalized)
        if risk=="high": return self._result("blocked","Hard policy blocks this high-impact action.",risk,user_id)
        if risk=="confirmation":
            cid=secrets.token_urlsafe(18); touched={a["device_id"] for a in normalized}
            self.confirmations[cid]={"actions":normalized,"user_id":user_id,"role":role,"state_hash":self._state_hash(touched),"created":time.time()}
            self._log("confirmation_required",user_id,{"actions":normalized,"confirmation_id":cid})
            return {"status":"confirmation_required","reason":"Confirm this exact proposed action.","risk":risk,"actions":normalized,"confirmation_id":cid}
        return self._execute(normalized,user_id,risk)
    def confirm(self,cid,approved,user_id,actions=None):
        pending=self.confirmations.pop(cid,None)
        if pending is None: return self._result("blocked","Confirmation unknown, expired, or already used.","high",user_id)
        if type(approved) is not bool: return self._result("blocked","Approval must be boolean.","high",user_id)
        if time.time()-pending["created"]>self.CONFIRM_TTL: return self._result("blocked","Confirmation expired.","high",user_id)
        if user_id!=pending["user_id"] or self.ROLES.get(user_id)!=pending["role"]: return self._result("blocked","Confirmation belongs to a different user.","high",user_id)
        if actions is not None and actions!=pending["actions"]: return self._result("blocked","Proposed action changed after confirmation.","high",user_id)
        touched={a["device_id"] for a in pending["actions"]}
        if self._state_hash(touched)!=pending["state_hash"]: return self._result("blocked","Relevant device state changed; request confirmation again.","high",user_id)
        if not approved:
            self._log("confirmation_rejected",user_id,{"actions":pending["actions"]})
            return {"status":"rejected","reason":"User rejected the proposed action.","risk":"confirmation"}
        # Revalidate each safety rule. Confirmation cannot bypass a hard block.
        for a in pending["actions"]:
            d=self.registry.devices[a["device_id"]]
            if d["type"]=="water_heater" and a["parameter"]=="power" and a["value"] is True:
                sensor=self.registry.sensors.get("water_level_bath")
                if not sensor or not sensor.get("valid") or type(sensor.get("value")) not in (int,float) or not 0<=sensor["value"]<=100 or time.time()-sensor.get("observed_at",0)>self.MAX_SENSOR_AGE:
                    return self._result("blocked","Water-level evidence is absent, invalid, or stale.","high",user_id)
        return self._execute(pending["actions"],user_id,"confirmation")
    def _execute(self,actions,user_id,risk):
        outcomes=[]
        for step,a in enumerate(actions,1):
            d=self.registry.devices[a["device_id"]]; d["state"][a["parameter"]]=a["value"]
            verified=d["state"].get(a["parameter"])==a["value"]
            state_after=copy.deepcopy(d["state"])
            outcomes.append({"step":step,"action":copy.deepcopy(a),"verified_parameter":a["parameter"],"verified_value":a["value"],"verified":verified,"state_after_action":state_after})
            self._log("executed" if verified else "verification_failed",user_id,{"step":step,"action":a,"verified":verified,"state_after_action":state_after})
            if not verified: return {"status":"execution_failed","reason":"Device state verification failed.","risk":risk,"outcomes":outcomes}
        device_ids={a["device_id"] for a in actions}
        final_states={device_id:copy.deepcopy(self.registry.devices[device_id]["state"]) for device_id in sorted(device_ids)}
        for outcome in outcomes:
            outcome["final_device_state"]=final_states[outcome["action"]["device_id"]]
        return {"status":"executed","reason":"Actions completed sequentially; each outcome shows state after that step, and final_states shows the verified result.","risk":risk,"actions":actions,"outcomes":outcomes,"final_states":final_states}
    @staticmethod
    def _valid(d,p,v):
        if p in ("power","locked"): return type(v) is bool
        if p=="temperature_c": return type(v) is int and d["constraints"][p][0]<=v<=d["constraints"][p][1]
        if p=="speed": return type(v) is int and d["constraints"][p][0]<=v<=d["constraints"][p][1]
        if p=="mode": return v in d["constraints"]["modes"]
        return False
    @staticmethod
    def _risk(actions):
        if any(a["device_id"]=="lock-front" and a["parameter"]=="locked" and a["value"] is False for a in actions): return "confirmation"
        if len({a["device_id"] for a in actions})>1 or any(a["device_id"]=="heater-bath" and a["value"] is True for a in actions): return "confirmation"
        return "low"
    def _state_hash(self,ids):
        state={i:self.registry.devices[i]["state"] for i in sorted(ids)}
        if "heater-bath" in ids: state["sensor:water_level_bath"]=self.registry.sensors.get("water_level_bath")
        return hashlib.sha256(json.dumps(state,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    def _result(self,status,reason,risk,user):
        result={"status":status,"reason":reason,"risk":risk}; self._log("policy_"+status,user,result); return result
    def _log(self,event,user,details): self.audit_log.append({"at":time.time(),"event":event,"user_id":user,"details":copy.deepcopy(details)})
