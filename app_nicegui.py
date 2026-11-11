"""
In-Situ FDM Process Monitor — NiceGUI interface.

Run:   .venv/bin/python app_nicegui.py        (opens http://localhost:8600)
Logic (action library, prompt, Ollama call, safety layer) lives in core.py.
"""
import asyncio
import html
import io
import json
import os
import sys
import time
from datetime import datetime

# --- launch guard -----------------------------------------------------------
# This is a NiceGUI app (not Streamlit) and its packages live in app/.venv.
_HERE = os.path.dirname(os.path.abspath(__file__))
_VENV_PY = os.path.join(_HERE, ".venv", "bin", "python")
_RUN_HINT = f"cd {_HERE}\n.venv/bin/python app_nicegui.py"
if "streamlit" in sys.modules:
    import streamlit as _st
    _st.error("This dashboard is a NiceGUI app and cannot be started with `streamlit run`.\n\n"
              "Stop this server (Control + C in Terminal) and start it with:\n\n"
              f"```\n{_RUN_HINT}\n```")
    _st.stop()
try:
    import nicegui  # noqa: F401
except ModuleNotFoundError:
    if os.path.exists(_VENV_PY) and os.path.abspath(sys.prefix) != os.path.join(_HERE, ".venv"):
        os.execv(_VENV_PY, [_VENV_PY, os.path.abspath(__file__), *sys.argv[1:]])  # restart with app/.venv
    sys.exit("NiceGUI is not installed for this Python. Start the dashboard with:\n\n" + _RUN_HINT +
             "\n\n(If app/.venv is missing, see 'First-time setup' in README.md.)")

from nicegui import events, run, ui
from PIL import Image

import core

PORT = int(os.environ.get("MONITOR_PORT", "8600"))

CHANNELS = [  # key, chip label, field label, default, min, max, step, decimals
    ("hotend_c", "T_melt", "T_melt (°C)", 210, 170, 300, 5, 0),
    ("bed_c", "T_bed", "T_bed (°C)", 60, 20, 120, 5, 0),
    ("speed_mm_s", "v_feed", "v_feed (mm/s)", 60, 10, 200, 5, 0),
    ("flow_pct", "η_flow", "η_flow (%)", 100, 80, 120, 5, 0),
    ("z_offset_mm", "Δz", "Δz (mm)", 0.00, -0.50, 0.50, 0.02, 2),
]

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600;700&display=swap');
:root { --z:1; --ink:#101828; --ink2:#344054; --muted:#667085; --line:#e4e7ec; --bg:#eceff4; --card:#ffffff;
        --accent:#2563eb; --ok:#067647; --okbg:#ecfdf3; --bad:#b42318; --badbg:#fef3f2; --warn:#b54708;
        --shadow:0 1px 2px rgba(16,24,40,.05), 0 2px 6px rgba(16,24,40,.06); }
html { font-size:16px; }
html, body { height:100%; overflow:hidden; background:var(--bg); font-family:Inter, system-ui, sans-serif; color:var(--ink); }
.nicegui-content { padding:0 !important; gap:0 !important; height:100vh; width:100%; max-width:none !important; }

/* ---------- shell: everything floats on the grey background ---------- */
.shell { zoom:var(--z); height:calc(100vh / var(--z)); box-sizing:border-box; width:100%;
         display:grid; grid-template-columns:330px minmax(0,1fr); gap:16px; padding:16px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:16px; box-shadow:var(--shadow); }

/* ---------- sidebar card ---------- */
.side { display:flex; flex-direction:column; min-height:0; overflow:hidden; }
.side .scroll { flex:1 1 auto; min-height:0; overflow-y:auto; padding:16px 18px 8px 18px; display:flex; flex-direction:column; gap:8px; }
.brand { display:flex; align-items:center; gap:11px; }
.brand .logo { width:40px; height:40px; border-radius:11px; background:linear-gradient(135deg,#2563eb,#7c3aed);
               color:#fff; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:15px; letter-spacing:.02em; }
.brand .t { font-size:17px; font-weight:700; line-height:1.2; }
.brand .s { font-size:13px; color:var(--muted); }
.mstat { display:flex; align-items:center; gap:8px; font-size:13.5px; font-weight:600; color:var(--ink2);
         background:#f8fafc; border:1px solid var(--line); border-radius:10px; padding:7px 10px; }
.mstat .dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
.mstat .m { margin-left:auto; color:var(--muted); font-weight:500; }
.sec { font-size:12px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); margin-top:5px; }
.fname { font-size:14px; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; flex:1; min-width:0; }
.q-field--dense .q-field__control, .q-field--dense .q-field__marginal { height:42px !important; min-height:42px !important; }
.q-field--outlined .q-field__control { border-radius:10px !important; }
.q-field__label { font-size:14px !important; }
.q-field__native, .q-field__input { font-size:15px !important; }
.q-item__label { font-size:15px; }
.chips { display:grid !important; grid-template-columns:repeat(5, minmax(0,1fr)); gap:5px; width:100%; }
.chips .q-chip { margin:0; height:30px; padding:0; width:100%; justify-content:center; font-size:13.5px; border:1px solid #bfdbfe; border-radius:8px; }
.chips .q-chip .q-chip__content { justify-content:center; padding:0 2px; }
.chips .q-chip .q-chip__icon--left { display:none; }
.chips .q-chip.off { border-color:#e4e7ec; }
.tgrid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
.side .foot { padding:12px 18px 16px 18px; border-top:1px solid var(--line); }

/* ---------- main: 2 x 2 result boxes ---------- */
.grid4 { min-height:0; display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); grid-template-rows:repeat(2, minmax(0,1fr)); gap:16px; }
.panel { min-height:0; overflow-y:auto; padding:16px 20px 18px 20px; display:flex; flex-direction:column; gap:13px; }
.ph { display:flex; align-items:center; gap:10px; font-size:18px; font-weight:700; line-height:1.25; flex:0 0 auto;
      padding-bottom:12px; border-bottom:1px solid var(--line); min-height:44px; }
.ph .pt { white-space:nowrap; }
.ph .n { width:30px; height:30px; flex-shrink:0; border-radius:9px; background:#eef4ff; color:var(--accent); font-size:15px;
         display:inline-flex; align-items:center; justify-content:center; font-weight:800; }
.ph .r { margin-left:auto; font-size:13.5px; font-weight:600; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:50%; }
.ph .q-btn { margin-left:auto; font-size:14px; }
.lbl { font-size:12px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); margin-bottom:7px; }
.lblr { display:flex; justify-content:space-between; align-items:baseline; }
.empty { flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:10px; text-align:center;
         color:var(--muted); font-size:15px; line-height:1.45; border:1.5px dashed #d0d5dd; border-radius:14px; padding:20px; background:#fcfcfd; }
.empty .i { width:52px; height:52px; border-radius:14px; background:#eef4ff; color:var(--accent); display:flex; align-items:center;
            justify-content:center; font-size:24px; }

/* box 1: optical acquisition (frame | machine + telemetry list) */
.acq { flex:1 1 auto; min-height:0; display:grid; grid-template-columns:minmax(0,1.65fr) minmax(0,1fr); gap:16px; }
.framebox { width:100%; aspect-ratio:3 / 2; max-height:100%; align-self:center; min-height:0; border-radius:12px; overflow:hidden; background:#f2f4f7; border:1px solid var(--line); }
.framebox .q-img { width:100%; height:100%; }
.framebox .q-img__image { background-size:contain !important; }
.kv { display:flex; flex-direction:column; min-height:0; overflow-y:auto; }
.kv .g { font-size:11.5px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); margin:0 0 2px 0; }
.kv .g + .row { border-top:none; }
.kv .row + .g { margin-top:12px; }
.kv .row { display:flex; justify-content:space-between; align-items:baseline; gap:8px; padding:5px 2px; border-top:1px solid #f0f2f5; font-size:14.5px; }
.kv .row .k { color:var(--muted); font-weight:600; white-space:nowrap; }
.kv .row .v { font-weight:700; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.kv .row.off .v { color:#98a2b3; font-weight:500; }

/* box 2: failure mode assessment */
.hero { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:12px; align-items:stretch; }
.dtile { border-radius:14px; padding:10px 18px; display:flex; flex-direction:column; justify-content:center; gap:6px; }
.dtile .k { font-size:12px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; opacity:.85; }
.dtile .v { font-size:28px; font-weight:800; line-height:1.1; text-transform:capitalize; letter-spacing:-.01em; }
.dtile .s { font-size:13.5px; font-weight:600; opacity:.85; }
.gauge { border:1px solid var(--line); border-radius:14px; padding:4px 14px; display:flex; flex-direction:column; align-items:center; justify-content:center; }
.gauge svg { width:82px; height:82px; display:block; }
.gauge .cap { font-size:12px; color:var(--muted); font-weight:600; }
.cls { display:grid; grid-template-columns:repeat(5, minmax(0,1fr)); gap:6px; }
.cls span { font-size:13px; font-weight:600; text-align:center; padding:6px 4px; border-radius:8px; border:1px solid var(--line);
            color:var(--muted); text-transform:capitalize; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.cls span.on { color:#fff; font-weight:700; }
.meta { display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:8px; }
.meta .m { border:1px solid var(--line); border-radius:10px; padding:5px 11px; min-width:0; }
.meta .k { white-space:nowrap; font-size:12px; color:var(--muted); font-weight:600; }
.meta .v { font-size:14.5px; font-weight:700; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.rc { background:#f8fafc; border:1px solid var(--line); border-radius:12px; padding:9px 14px; font-size:15px; line-height:1.45; color:var(--ink2); }

/* box 3: deterministic safety layer */
.chk { display:grid; grid-template-columns:repeat(2, minmax(0,1fr)); gap:8px; }
.cr { display:flex; align-items:center; gap:11px; border-radius:11px; padding:8px 12px; min-width:0; }
.cr .ic { width:26px; height:26px; border-radius:50%; flex-shrink:0; display:flex; align-items:center; justify-content:center;
          color:#fff; font-weight:800; font-size:14px; }
.cr .tx { display:flex; flex-direction:column; min-width:0; }
.cr .t { font-size:14px; font-weight:700; color:var(--ink); line-height:1.25; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.cr .d { font-size:12.5px; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.cr.pass { background:var(--okbg); } .cr.pass .ic { background:#12b76a; }
.cr.warn { background:#fffaeb; } .cr.warn .ic { background:#f79009; }
.cr.fail { background:var(--badbg); } .cr.fail .ic { background:#f04438; }
.stats { display:grid; grid-template-columns:repeat(3, minmax(0,1fr)); gap:8px; margin-bottom:9px; }
.st { border:1px solid var(--line); border-radius:12px; padding:7px 12px; }
.st .k { font-size:12.5px; color:var(--muted); font-weight:600; }
.st .v { font-size:22px; font-weight:800; line-height:1.2; }
.st .v small { font-size:13px; color:var(--muted); font-weight:500; }
.st.good .v { color:var(--ok); } .st.bad .v { color:var(--bad); }
.track { position:relative; height:10px; background:#e4e7ec; border-radius:6px; overflow:hidden; }
.track .used { position:absolute; inset:0 auto 0 0; background:var(--accent); border-radius:6px; }
.tcap { font-size:12.5px; color:var(--muted); margin-top:6px; }

/* box 4: guardrailed corrective actions */
.status { border-radius:12px; padding:10px 14px; font-size:15.5px; font-weight:700; display:flex; align-items:center; gap:9px; }
.status.ok { background:var(--okbg); border:1px solid #abefc6; color:var(--ok); }
.status.gate { background:var(--badbg); border:1px solid #fecdca; color:var(--bad); }
.flow { display:grid; grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); gap:8px; align-items:stretch; }
.fbox { border:1px solid var(--line); border-radius:12px; padding:8px 12px; display:flex; align-items:center; gap:10px; }
.fbox .lbl { margin:0; }
.ids { display:flex; flex-wrap:wrap; gap:5px; }
.idc { font-family:'JetBrains Mono', ui-monospace, monospace; font-size:14px; font-weight:700; color:#fff; padding:3px 9px; border-radius:7px; }
.idc.x { background:#e4e7ec; color:#98a2b3; text-decoration:line-through; }
.flow .arr { align-self:center; font-size:22px; color:#98a2b3; }
.acts { display:flex; flex-direction:column; gap:8px; }
.at { border-radius:12px; padding:9px 13px; border-left:5px solid; display:grid; grid-template-columns:auto minmax(0,1fr); gap:1px 12px; align-items:center; }
.at .aid { grid-row:span 2; font-family:'JetBrains Mono', ui-monospace, monospace; font-size:22px; font-weight:800; }
.at .atl { font-size:15.5px; font-weight:700; color:var(--ink); line-height:1.25; display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.at .adt { font-size:13.5px; color:var(--muted); }
.okb { font-size:11.5px; font-weight:700; color:var(--ok); background:var(--okbg); border:1px solid #abefc6; border-radius:999px; padding:1px 8px; letter-spacing:.02em; }
.q-btn { font-size:15px; }
.q-btn.rounded-btn { border-radius:12px !important; }

/* ---------- proportional scale-down on smaller screens ---------- */
@media (max-height: 900px), (max-width: 1500px) { :root { --z:.92; } }
@media (max-height: 790px), (max-width: 1360px) { :root { --z:.84; } }
@media (max-height: 700px) { :root { --z:.77; } }
"""

CAT_ROWS = [("Thermal Control", ["A1", "A2", "A3", "A4"], "Thermal"),
            ("Flow Dynamics", ["B1", "B2"], "Flow"),
            ("Kinematic Feed", ["B3", "B4"], "Kinematic"),
            ("Toolpath / Offset", ["C1", "C2", "C3"], "Toolpath"),
            ("Supervisory Gate", ["D1", "D2"], "Gate")]


def esc(x) -> str:
    return html.escape(str(x))


def safety_checks(raw_obj: dict, r: dict, notes: list) -> list:
    """Re-state the deterministic interlock as six checks: (label, status, detail)."""
    proposed = r["proposed_actions"]
    rejected = [a for a in proposed if a not in core.ACTION_LIBRARY]
    conflicts = [f"{a}/{b}" for a, b in core.CONFLICTING_PAIRS if a in proposed and b in proposed]
    mapped = any(n.startswith("Defect label") for n in notes)
    rescaled = any(n.startswith("Confidence reported") for n in notes)
    conf = r["confidence_score"]
    raw_flag = bool(raw_obj.get("escalation_flag", False)) if isinstance(raw_obj, dict) else False
    return [
        ("Valid JSON response", "pass", "schema parsed"),
        ("Canonical defect class",
         "fail" if r["detected_defect"] is None else ("warn" if mapped else "pass"),
         "unrecognized → hold" if r["detected_defect"] is None else
         (f"mapped to {r['detected_defect']}" if mapped else r["detected_defect"])),
        (f"Confidence ≥ {core.CONF_THRESHOLD:.2f}", "pass" if conf >= core.CONF_THRESHOLD else "fail",
         (f"{conf:.2f}" + (" (rescaled)" if rescaled else "")) + ("" if conf >= core.CONF_THRESHOLD else " → D1 hold")),
        ("Actions within library", "fail" if rejected else "pass",
         f"discarded {', '.join(rejected)}" if rejected else f"{len(proposed)} of 13 IDs"),
        ("No contradictory adjustments", "fail" if conflicts else "pass",
         f"removed {', '.join(conflicts)}" if conflicts else "none"),
        ("Escalation flag consistent", "warn" if raw_flag != r["escalation_flag"] else "pass",
         "recomputed" if raw_flag != r["escalation_flag"] else ("raised" if r["escalation_flag"] else "not raised")),
    ]


def donut(v: float, col: str, thr: float) -> str:
    """Confidence ring with threshold tick."""
    import math
    r, c = 40, 2 * math.pi * 40
    a = thr * 2 * math.pi - math.pi / 2
    x1, y1 = 50 + 31 * math.cos(a), 50 + 31 * math.sin(a)
    x2, y2 = 50 + 49 * math.cos(a), 50 + 49 * math.sin(a)
    return (f'<svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="{r}" fill="none" stroke="#eef0f3" stroke-width="11"/>'
            f'<circle cx="50" cy="50" r="{r}" fill="none" stroke="{col}" stroke-width="11" stroke-linecap="round" '
            f'stroke-dasharray="{max(v, 0) * c:.1f} {c:.1f}" transform="rotate(-90 50 50)"/>'
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#111827" stroke-width="2.5"/>'
            f'<text x="50" y="57" text-anchor="middle" font-size="22" font-weight="700" fill="{col}" '
            f'font-family="Inter, sans-serif">{v:.2f}</text></svg>')


@ui.page("/")
def index():
    ui.add_css(CSS)
    ui.colors(primary="#2563eb")
    state = {"image": None, "source": "", "result": None, "raw_obj": {}, "notes": [], "raw": "", "model": "",
             "latency": 0.0, "time": "", "error": None, "busy": False, "tele": None}
    tele_inputs, tele_on, chips = {}, {}, {}

    # ------------------------------------------------------------ helpers
    def telemetry() -> dict:
        t = {"kinematics": platform.value, "material": polymer.value, "section": section.value,
             "layer_time_s": float(layer_time.value or 0)}
        for key, *_ in CHANNELS:
            v = tele_inputs[key].value
            t[key] = (float(v) if key == "z_offset_mm" else v) if tele_on[key] else None
        return t

    def model_tag() -> str:
        if model.value == "Custom...":
            return (custom_tag.value or "").strip() or core.DEFAULT_MODEL
        return model.value

    def set_image(img, name):
        state.update(image=img, source=name, result=None, error=None)
        fname.set_text(name or "No file selected")
        run_btn.set_enabled(img is not None)
        refresh_all()

    async def on_upload(e: events.UploadEventArguments):
        data = await e.file.read()
        img = Image.open(io.BytesIO(data))
        img.load()
        specimen.set_value(None)
        set_image(img.convert("RGB"), e.file.name)
        uploader.reset()

    def on_specimen(e):
        if e.value:
            set_image(core.load_specimen(e.value), e.value)

    def toggle_channel(key, selected):
        tele_on[key] = selected
        tele_inputs[key].set_enabled(selected)
        chips[key].props(f'color={"blue-1" if selected else "grey-1"} text-color={"blue-10" if selected else "grey-6"}')
        chips[key].classes(remove="off") if selected else chips[key].classes(add="off")
        panel1.refresh()

    async def run_diagnostics():
        if state["image"] is None or state["busy"]:
            return
        state.update(busy=True, error=None)
        run_btn.props("loading")
        t = telemetry()
        t0 = time.perf_counter()
        try:
            if demo.value:
                await asyncio.sleep(0.6)
                if profile.value == "Guardrail stress test":
                    raw_obj, label = core.STRESS_TEST_RESPONSE, "stress test"
                else:
                    src = (state["source"] or "").lower()
                    target = src if src in core.MOCK_RESPONSES else next(
                        (c for c in core.DEFECT_CLASSES if c.replace(" ", "_") in src), "warping")
                    raw_obj, label = core.MOCK_RESPONSES[target], target
                raw_text, used = json.dumps(raw_obj, indent=2), f"Demo ({label})"
                state["backend"] = "demo"
            else:
                tag = model_tag()
                if tag in core.OPENAI_MODELS:
                    raw_text, backend = await run.io_bound(core.call_openai, tag, t, state["image"])
                    used = tag
                else:
                    raw_text, backend = await run.io_bound(core.call_ollama, endpoint.value,
                                                           core.MODEL_ALIASES.get(tag, tag), t, state["image"])
                    used = tag if tag in core.MODEL_ALIASES else backend
                state["backend"] = backend
                raw_obj = core.clean_json_text(raw_text)
            result, notes = core.sanitize_result(raw_obj)
            state.update(result=result, raw_obj=raw_obj, notes=notes, raw=raw_text, model=used, tele=t,
                         latency=time.perf_counter() - t0, time=datetime.now().strftime("%H:%M:%S"))
        except Exception as ex:  # surfaced in the panels
            state.update(result=None, error=str(ex))
        finally:
            state["busy"] = False
            run_btn.props(remove="loading")
            refresh_all()

    def export_audit():
        r = state["result"]
        if not r:
            return
        margin = state["tele"]["layer_time_s"] - state["latency"]
        record = {"timestamp": state["time"], "model_engine": state["model"], "backend_model": state.get("backend", ""),
                  "source": state["source"], "latency_sec": round(state["latency"], 2),
                  "layer_time_sec": state["tele"]["layer_time_s"], "process_window_margin_sec": round(margin, 2),
                  "telemetry_state": state["tele"], "supervisory_decision": r, "deterministic_overrides": state["notes"],
                  "raw_model_payload": state["raw"]}
        ui.download.content(json.dumps(record, indent=2).encode(), f"audit_log_{state['time'].replace(':', '')}.json")

    # ------------------------------------------------------------ settings dialog
    with ui.dialog() as settings, ui.card().classes("w-96"):
        ui.label("Endpoint & demo mode").classes("text-lg font-semibold")
        endpoint = ui.input("Ollama endpoint", value="http://localhost:11434").props("dense outlined").classes("w-full")
        custom_tag = ui.input("Custom model tag").props("dense outlined").classes("w-full")
        demo = ui.switch("Demo / mock mode (offline)", value=False, on_change=lambda: header.refresh())
        profile = ui.select(core.DEMO_PROFILES, value=core.DEMO_PROFILES[0], label="Demo response profile") \
            .props("dense outlined").classes("w-full")
        ui.button("Close", on_click=settings.close).props("flat").classes("self-end")

    uploader = ui.upload(on_upload=on_upload, auto_upload=True, max_files=1) \
        .props('accept=".png,.jpg,.jpeg"').classes("hidden")

    with ui.element("div").classes("shell"):
        # -------------------------------------------------------- sidebar card
        with ui.element("div").classes("card side"):
            with ui.element("div").classes("scroll"):
                ui.html('<div class="brand"><div class="logo">IS</div><div><div class="t">In-Situ FDM Process Monitor</div>'
                        '<div class="s">Guardrailed operator decision support</div></div></div>', sanitize=False)

                @ui.refreshable
                def header():
                    dot = "#d97706" if demo.value else "#12b76a"
                    name = "Demo · scripted responses" if demo.value else esc(model_tag())
                    ui.html(f'<div class="mstat"><span class="dot" style="background:{dot}"></span>{name}'
                            f'<span class="m">interlock ≥ {core.CONF_THRESHOLD:.2f}</span></div>', sanitize=False)
                hdr_slot = ui.element("div").classes("w-full")

                ui.html('<div class="sec">Input frame</div>', sanitize=False)
                with ui.row(wrap=False).classes("items-center gap-2 w-full"):
                    ui.button("Browse", icon="upload_file", on_click=lambda: uploader.run_method("pickFiles")) \
                        .props("outline no-caps").classes("rounded-btn")
                    fname = ui.label("No file selected").classes("fname")
                specimen = ui.select({c: c.title() for c in core.DEFECT_CLASSES}, label="Benchmark specimen",
                                     on_change=on_specimen, clearable=True).props("dense outlined").classes("w-full")

                ui.html('<div class="sec">Model</div>', sanitize=False)
                with ui.row(wrap=False).classes("items-center gap-1 w-full"):
                    model = ui.select(core.MODEL_OPTIONS, value=core.DEFAULT_MODEL, label="Vision-language model",
                                      on_change=lambda: header.refresh()).props("dense outlined").classes("flex-1")
                    ui.button(icon="tune", on_click=settings.open).props("flat round").tooltip("Endpoint & demo mode")
                with hdr_slot:
                    header()

                ui.html('<div class="sec">Machine</div>', sanitize=False)
                platform = ui.select(core.KINEMATIC_SYSTEMS, value=core.KINEMATIC_SYSTEMS[0], label="Platform",
                                     on_change=lambda: panel1.refresh()).props("dense outlined").classes("w-full")
                polymer = ui.select(core.MATERIAL_PROFILES, value="PLA", label="Polymer",
                                    on_change=lambda: panel1.refresh()).props("dense outlined").classes("w-full")
                section = ui.select(core.PRINT_SECTIONS, value=core.PRINT_SECTIONS[1], label="Section",
                                    on_change=lambda: panel1.refresh()).props("dense outlined").classes("w-full")

                ui.html('<div class="sec">Telemetry</div>', sanitize=False)
                with ui.element("div").classes("chips"):
                    for key, chip, *_ in CHANNELS:
                        tele_on[key] = True
                        chips[key] = ui.chip(chip, selectable=True, selected=True, color="blue-1", text_color="blue-10",
                                             on_selection_change=lambda e, k=key: toggle_channel(k, e.value)).props("dense")
                with ui.element("div").classes("tgrid"):
                    for key, chip, label, dflt, lo, hi, step, dec in CHANNELS:
                        tele_inputs[key] = ui.number(label, value=dflt, min=lo, max=hi, step=step,
                                                     format=f"%.{dec}f", on_change=lambda: panel1.refresh()) \
                            .props("dense outlined")
                    layer_time = ui.number("t_layer (s)", value=45, min=1, max=600, step=5, format="%.0f",
                                           on_change=lambda: panel1.refresh()).props("dense outlined")
            with ui.element("div").classes("foot"):
                run_btn = ui.button("Run diagnostics", icon="play_arrow", on_click=run_diagnostics) \
                    .props("unelevated no-caps color=primary").classes("w-full rounded-btn") \
                    .style("height:50px; font-size:16px; font-weight:600")
                run_btn.set_enabled(False)

        # -------------------------------------------------------- 2 x 2 result boxes
        with ui.element("div").classes("grid4"):
            def head(n, title, right=""):
                ui.html(f'<div class="ph"><span class="n">{n}</span><span class="pt">{title}</span>'
                        f'<span class="r">{right}</span></div>', sanitize=False)

            def empty(icon, text):
                ui.html(f'<div class="empty"><span class="i">{icon}</span>{text}</div>', sanitize=False) \
                    .classes("flex flex-1 flex-col")

            # ---------------- box 1: optical acquisition
            @ui.refreshable
            def panel1():
                with ui.element("div").classes("card panel"):
                    head(1, "Optical acquisition", esc(state["source"]) if state["image"] is not None else "")
                    if state["image"] is None:
                        empty("◫", "Upload an in-situ frame or choose a benchmark specimen.")
                        return
                    t = telemetry()

                    def row(k, v, unit=""):
                        if v is None:
                            return f'<div class="row off"><span class="k">{k}</span><span class="v">off</span></div>'
                        return f'<div class="row"><span class="k">{k}</span><span class="v">{esc(v)}{unit}</span></div>'

                    z = f"{t['z_offset_mm']:+.2f}" if t["z_offset_mm"] is not None else None
                    plat = "Gantry" if t["kinematics"].startswith("Gantry") else "6-DoF arm"
                    with ui.element("div").classes("acq"):
                        with ui.element("div").classes("framebox"):
                            ui.image(state["image"]).props("fit=contain").classes("w-full h-full")
                        ui.html('<div class="g">Machine</div>'
                                + row("Platform", plat) + row("Polymer", t["material"]) + row("Section", t["section"])
                                + '<div class="g">Process telemetry</div>'
                                + row("T<sub>melt</sub>", t["hotend_c"], " °C") + row("T<sub>bed</sub>", t["bed_c"], " °C")
                                + row("v<sub>feed</sub>", t["speed_mm_s"], " mm/s") + row("η<sub>flow</sub>", t["flow_pct"], " %")
                                + row("Δz", z, " mm") + row("t<sub>layer</sub>", f"{t['layer_time_s']:.0f}", " s"),
                                sanitize=False).classes("kv")

            # ---------------- box 2: failure mode assessment
            @ui.refreshable
            def panel2():
                with ui.element("div").classes("card panel"):
                    r = state["result"]
                    head(2, "Failure mode assessment", f'run at {state["time"]}' if r else "")
                    if state["error"]:
                        ui.html(f'<div class="status gate">{esc(state["error"])}</div>', sanitize=False)
                        return
                    if not r:
                        empty("◎", "Detected defect class, model confidence and the physical root cause appear here.")
                        return
                    det = r["detected_defect"]
                    dcol = core.DEFECT_COLORS.get(det or "unrecognized", "#495057")
                    conf = r["confidence_score"]
                    col = "#067647" if conf >= core.CONF_THRESHOLD else "#b42318"
                    above = "above" if conf >= core.CONF_THRESHOLD else "below"
                    classes = "".join(
                        f'<span class="on" style="background:{core.DEFECT_COLORS[c]};border-color:{core.DEFECT_COLORS[c]}">{esc(c)}</span>'
                        if c == det else f'<span>{esc(c)}</span>' for c in core.DEFECT_CLASSES)
                    ui.html(
                        f'<div class="hero"><div class="dtile" style="background:{dcol}12;color:{dcol}">'
                        f'<span class="k">Detected defect</span><span class="v">{esc(det or "unrecognized")}</span>'
                        f'<span class="s">Confidence {conf:.2f} · {above} the {core.CONF_THRESHOLD:.2f} interlock</span></div>'
                        f'<div class="gauge">{donut(conf, col, core.CONF_THRESHOLD)}'
                        f'<span class="cap">confidence</span></div></div>'
                        f'<div><div class="lbl">Defect taxonomy (5 classes)</div><div class="cls">{classes}</div></div>'
                        f'<div><div class="lbl">Physical root cause</div><div class="rc">{esc(r["physical_root_cause"])}</div></div>'
                        f'<div><div class="lbl">Run details</div><div class="meta">'
                        f'<div class="m"><div class="k">Model</div><div class="v">{esc(state["model"])}</div></div>'
                        f'<div class="m"><div class="k">Backend</div><div class="v">{esc(state.get("backend", ""))}</div></div>'
                        f'<div class="m"><div class="k">Response time</div><div class="v">{state["latency"]:.1f} s</div></div>'
                        f'<div class="m"><div class="k">Overrides</div><div class="v">{len(state["notes"]) or "none"}</div></div>'
                        f'</div></div>',
                        sanitize=False).classes("flex flex-col gap-3")

            # ---------------- box 3: deterministic safety layer
            @ui.refreshable
            def panel3():
                with ui.element("div").classes("card panel"):
                    r = state["result"]
                    if state["error"] or not r:
                        head(3, "Deterministic safety layer")
                        empty("⛨", "Supervisory pipeline suspended." if state["error"] else
                              "The six deterministic safety checks and the process-window margin appear here.")
                        return
                    chk = safety_checks(state["raw_obj"], r, state["notes"])
                    npass = sum(st == "pass" for _, st, _ in chk)
                    head(3, "Deterministic safety layer",
                         f'<span style="color:{"#067647" if npass == 6 else "#b54708"}">{npass}/6 checks passed</span>')
                    rows = "".join(
                        f'<div class="cr {st}" title="{esc(lbl)}: {esc(d)}"><span class="ic">'
                        f'{"✓" if st == "pass" else ("!" if st == "warn" else "✕")}</span>'
                        f'<span class="tx"><span class="t">{esc(lbl)}</span><span class="d">{esc(d)}</span></span></div>'
                        for lbl, st, d in chk)
                    lat, tl = state["latency"], state["tele"]["layer_time_s"]
                    margin = tl - lat
                    used = min(100.0, 100.0 * lat / tl) if tl > 0 else 100.0
                    ui.html(
                        f'<div><div class="lbl">Safety checks</div><div class="chk">{rows}</div></div>'
                        f'<div><div class="lbl">Process window</div>'
                        f'<div class="stats"><div class="st"><div class="k">Inference</div><div class="v">{lat:.1f}<small> s</small></div></div>'
                        f'<div class="st"><div class="k">Layer time</div><div class="v">{tl:.0f}<small> s</small></div></div>'
                        f'<div class="st {"bad" if margin <= 0 else "good"}"><div class="k">Margin</div><div class="v">{margin:+.1f}<small> s</small></div></div></div>'
                        f'<div class="track"><div class="used" style="width:{used:.1f}%"></div></div>'
                        f'<div class="tcap">Inference uses {used:.0f}% of the layer time'
                        f'{"; the decision arrives before the next layer." if margin > 0 else "; the decision arrives too late for the next layer."}</div></div>',
                        sanitize=False).classes("flex flex-col gap-4")

            # ---------------- box 4: guardrailed corrective actions
            @ui.refreshable
            def panel4():
                with ui.element("div").classes("card panel"):
                    r = state["result"]
                    if state["error"] or not r:
                        head(4, "Guardrailed corrective actions")
                        empty("▦", "Supervisory pipeline suspended." if state["error"] else
                              "Bounded interventions from the 13-action library appear here.")
                        return
                    with ui.element("div").classes("ph"):
                        ui.html('<span class="n">4</span><span class="pt">Guardrailed corrective actions</span>',
                                sanitize=False).classes("flex items-center gap-[10px]")
                        ui.button("Export audit (.json)", icon="download", on_click=export_audit) \
                            .props("flat dense no-caps color=primary")
                    status = ('<div class="status gate">⛔ Interlock active · operator verification required</div>'
                              if r["escalation_flag"] else
                              '<div class="status ok">✓ Released for operator approval</div>')
                    released = r["recommended_actions"]
                    ok_set = set(core.ACCEPTABLE_ACTIONS.get(r["detected_defect"] or "", []))

                    def idchip(k):
                        if k not in core.ACTION_LIBRARY:
                            return f'<span class="idc x" title="not in library">{esc(k)}</span>'
                        c = core.CATEGORY_COLORS[core.ACTION_LIBRARY[k]["category"]]
                        style = f"background:{c}" if k in released else f"background:{c};opacity:.35"
                        return f'<span class="idc" style="{style}" title="{esc(core.ACTION_LIBRARY[k]["title"])}">{k}</span>'
                    prop_html = "".join(idchip(k) for k in r["proposed_actions"]) or '<span class="adt">none</span>'
                    rel_html = "".join(idchip(k) for k in released) or '<span class="adt">none</span>'
                    cards = ""
                    for k in released:
                        a = core.ACTION_LIBRARY[k]
                        c = core.CATEGORY_COLORS[a["category"]]
                        badge = '<span class="okb">Table 2 ✓</span>' if k in ok_set else ""
                        cards += (f'<div class="at" style="border-left-color:{c};background:{c}0f">'
                                  f'<span class="aid" style="color:{c}">{k}</span>'
                                  f'<span class="atl">{esc(a["title"])}{badge}</span>'
                                  f'<span class="adt">{esc(a["category"])} · {esc(a["detail"])}</span></div>')
                    ui.html(
                        status
                        + f'<div class="flow"><div class="fbox"><span class="lbl">Proposed</span><div class="ids">{prop_html}</div></div>'
                          f'<span class="arr">→</span><div class="fbox"><span class="lbl">Released</span><div class="ids">{rel_html}</div></div></div>'
                        + f'<div class="acts">{cards}</div>',
                        sanitize=False).classes("flex flex-col gap-[13px]")

            panel1()
            panel2()
            panel3()
            panel4()

    def refresh_all():
        header.refresh()
        panel1.refresh()
        panel2.refresh()
        panel3.refresh()
        panel4.refresh()


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="In-Situ FDM Process Monitor", port=PORT, reload=False,
           show=not os.environ.get("MONITOR_NO_BROWSER"), favicon="🛠️")
