import time
import unittest
from smart_home.core import DeviceRegistry, SmartHomeAssistant

class AssistantTests(unittest.TestCase):
    def setUp(self): self.assistant=SmartHomeAssistant()
    def test_cooler_request_executes_and_verifies(self):
        result=self.assistant.request("make it cooler in here")
        self.assertEqual(result["status"],"executed")
        self.assertEqual(self.assistant.registry.devices["ac-living"]["state"]["temperature_c"],22)
        self.assertTrue(all(x["verified"] for x in result["outcomes"]))
        first,second=result["outcomes"]
        self.assertEqual((first["verified_parameter"],first["verified_value"]),("temperature_c",22))
        self.assertFalse(first["state_after_action"]["power"])
        self.assertEqual((second["verified_parameter"],second["verified_value"]),("power",True))
        self.assertTrue(second["state_after_action"]["power"])
        self.assertEqual(result["final_states"]["ac-living"],self.assistant.registry.devices["ac-living"]["state"])
    def test_ambiguous_request_does_not_execute(self): self.assertEqual(self.assistant.request("turn on the heater")["status"],"ambiguous")
    def test_away_requires_confirmation(self):
        result=self.assistant.request("I'm away for a week")
        self.assertEqual(result["status"],"confirmation_required")
        self.assertTrue(self.assistant.registry.devices["light-living"]["state"]["power"])
    def test_confirmation_approval_and_rejection(self):
        pending=self.assistant.request("I'm away for a week")
        self.assertEqual(self.assistant.confirm(pending["confirmation_id"],True,"owner",pending["actions"])["status"],"executed")
        pending=self.assistant.request("I'm away for a week")
        self.assertEqual(self.assistant.confirm(pending["confirmation_id"],False,"owner",pending["actions"])["status"],"rejected")
    def test_missing_stale_and_invalid_water_evidence_block_heater(self):
        registry=DeviceRegistry(); registry.sensors.pop("water_level_bath")
        self.assertEqual(SmartHomeAssistant(registry).request("turn on water heater")["status"],"blocked")
        registry=DeviceRegistry(); registry.sensors["water_level_bath"]["observed_at"]=time.time()-500
        self.assertEqual(SmartHomeAssistant(registry).request("turn on water heater")["status"],"blocked")
        registry=DeviceRegistry(); registry.sensors["water_level_bath"]["value"]=140
        self.assertEqual(SmartHomeAssistant(registry).request("turn on water heater")["status"],"blocked")
    def test_unauthorized_user_cannot_unlock(self):
        result=self.assistant.request("unlock the front door","guest")
        self.assertEqual(result["status"],"blocked")
        self.assertTrue(self.assistant.registry.devices["lock-front"]["state"]["locked"])
    def test_authorized_unlock_requires_confirmation(self):
        pending=self.assistant.request("unlock the front door","owner")
        self.assertEqual(pending["status"],"confirmation_required")
        result=self.assistant.confirm(pending["confirmation_id"],True,"owner",pending["actions"])
        self.assertEqual(result["status"],"executed")
        self.assertFalse(self.assistant.registry.devices["lock-front"]["state"]["locked"])
    def test_confirmation_binds_actions_state_and_user(self):
        pending=self.assistant.request("I'm away for a week"); actions=[dict(a) for a in pending["actions"]]; actions[0]["value"]=True
        self.assertEqual(self.assistant.confirm(pending["confirmation_id"],True,"owner",actions)["status"],"blocked")
        pending=self.assistant.request("I'm away for a week"); self.assistant.registry.devices["light-living"]["state"]["power"]=False
        self.assertEqual(self.assistant.confirm(pending["confirmation_id"],True,"owner",pending["actions"])["status"],"blocked")
        pending=self.assistant.request("I'm away for a week")
        self.assertEqual(self.assistant.confirm(pending["confirmation_id"],True,"guest",pending["actions"])["status"],"blocked")
    def test_confirmation_cannot_bypass_heater_safety(self):
        registry=DeviceRegistry(); registry.sensors["water_level_bath"]["valid"]=False
        assistant=SmartHomeAssistant(registry)
        result=assistant.evaluate([{"device_id":"heater-bath","parameter":"power","value":True}],"owner")
        self.assertEqual(result["status"],"blocked")
        self.assertFalse(registry.devices["heater-bath"]["state"]["power"])
    def test_heater_activation_requires_confirmation_and_sensor_is_bound(self):
        pending=self.assistant.request("turn on water heater")
        self.assertEqual(pending["status"],"confirmation_required")
        result=self.assistant.confirm(pending["confirmation_id"],True,"owner",pending["actions"])
        self.assertEqual(result["status"],"executed")
        other=SmartHomeAssistant(); pending=other.request("turn on water heater")
        other.registry.sensors["water_level_bath"]["value"]=50
        result=other.confirm(pending["confirmation_id"],True,"owner",pending["actions"])
        self.assertEqual(result["status"],"blocked")
        self.assertFalse(other.registry.devices["heater-bath"]["state"]["power"])
    def test_invalid_parameters_are_blocked(self):
        result=self.assistant.evaluate([{"device_id":"ac-living","parameter":"temperature_c","value":5}],"owner")
        self.assertEqual(result["status"],"blocked")

if __name__=="__main__": unittest.main()
