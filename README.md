# Make it cooler in here

A local-only Havells smart-home assistant demo. It uses Python's standard library and simulates all appliances; it has no integrations or real device credentials.

## Run

Requires Python 3.10 or newer. From this folder:

```powershell
python app.py
```

Open <http://127.0.0.1:8000>. Run tests:

```powershell
python -m unittest discover -s tests -v
```

For Render, use `python app.py` as the start command. The server listens on `0.0.0.0` and reads Render's `PORT` environment variable (default `8000` for local use). Render terminates HTTPS at its proxy; the UI uses same-origin relative API paths, so browser requests remain on the deployed HTTPS origin.

## Architecture

- `smart_home/core.py`: device registry, phrase interpreter, separate deterministic policy, simulator, confirmation store, and audit log.
- `app.py`: local JSON API and static UI server.
- `web/index.html`: simple demo interface.
- `tests/test_assistant.py`: automated behavior and safety tests.

The local phrase interpreter produces structured proposals only. It cannot execute device commands. The deterministic policy checks each user, capability, parameter, value, sensor, risk, and confirmation before commands reach the simulator.

## Tool schemas

`POST /api/request` accepts `{"text":"make it cooler in here","user_id":"owner"}`. The result includes status, risk, reason, and proposed `actions` when applicable. Each action has `device_id`, `parameter`, and `value`, for example `{"device_id":"ac-living","parameter":"temperature_c","value":22}`.

`POST /api/confirm` accepts `{"confirmation_id":"…","approved":true,"user_id":"owner","actions":[…]}`. The server compares the supplied action with its stored proposal, checks identity, expiry and device-state fingerprint, then rechecks policy.

`GET /api/devices` returns registry and sensors. `GET /api/log` returns recent policy decisions and execution events.

## Risk tiers and guarantees

- **Low:** One in-range AC or light adjustment executes immediately.
- **Confirmation:** Multi-device changes, heater activation, and an authorized owner's door unlock wait for explicit approval.
- **Hard block:** Out-of-range parameters, missing/invalid/stale water-level evidence, unauthorized door unlocking, and malformed proposals are rejected. Approval cannot override hard rules.

The registry includes device IDs, types, rooms, capabilities, state, constraints, and a timestamped bath water-level sensor. Simulated commands are logged and verified against resulting device state. Confirmations are one-use, expire after five minutes, and are tied to the exact actions, user, and relevant device state.

## Limitations

This is a runnable assessment demo, not production home-automation software. The phrase interpreter supports a small vocabulary. Demo user IDs and roles are not authentication. State is in memory and resets at restart. The standard-library server binds to localhost. There is no external AI, hardware connection, or real device control.
