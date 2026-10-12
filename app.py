"""Local HTTP interface for the simulated smart-home assistant."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from smart_home.core import SmartHomeAssistant

ASSISTANT=SmartHomeAssistant()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route=urlparse(self.path).path
        if route=="/":
            data=(Path(__file__).parent/"web"/"index.html").read_bytes(); self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
        elif route=="/api/devices": self._json(200,ASSISTANT.registry.snapshot())
        elif route=="/api/log": self._json(200,{"events":ASSISTANT.audit_log[-100:]})
        else: self._json(404,{"error":"Not found"})
    def do_POST(self):
        try:
            length=int(self.headers.get("Content-Length","0"))
            if length>32000: return self._json(413,{"error":"Request too large"})
            data=json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data,dict): return self._json(400,{"error":"Expected a JSON object"})
            route=urlparse(self.path).path
            if route=="/api/request": result=ASSISTANT.request(str(data.get("text","")),str(data.get("user_id","owner")))
            elif route=="/api/confirm": result=ASSISTANT.confirm(data.get("confirmation_id",""),data.get("approved"),str(data.get("user_id","owner")),data.get("actions"))
            else: return self._json(404,{"error":"Not found"})
            self._json(200,result)
        except (ValueError,TypeError,KeyError) as exc: self._json(400,{"error":str(exc)})
    def _json(self,status,body):
        data=json.dumps(body).encode(); self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
    def log_message(self,fmt,*args): print("[%s] %s"%(self.log_date_time_string(),fmt%args))

if __name__=="__main__":
    server=ThreadingHTTPServer(("127.0.0.1",8000),Handler); print("Havells demo: http://127.0.0.1:8000")
    try: server.serve_forever()
    except KeyboardInterrupt: server.server_close()
