# Spikes

## `serum_host_spike.py`

**Goal:** Prove Serum 2 can be hosted outside Ableton and driven with MIDI.

### Result (this machine)

| Backend | Python | Load Serum 2 | MIDI → sound |
|---------|--------|--------------|--------------|
| **DawDreamer** | **3.12** | Yes | **Yes** (`spikes/out/serum_spike.wav`) |
| Pedalboard | 3.14 | Yes (need `plugin_name="Serum 2"`) | No simple path in spike |

Use **DawDreamer on Python 3.12** as the host sidecar runtime. Keep the FastAPI app on 3.14.

### Run

```powershell
py -3.12 -m pip install dawdreamer numpy scipy
py -3.12 spikes/serum_host_spike.py
```

### Next

- Sidecar process API for the main app  
- Load `.fxp` into hosted Serum  
- Two instances (bass + lead)  
