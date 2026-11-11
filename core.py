"""
Core logic for the In-Situ FDM Process Monitor, shared by the user interfaces.
Copied unchanged from appv5.py sections 1-4: action library, demo responses,
specimen loading, deterministic safety layer, prompts, and the Ollama call.
No UI code lives here.
"""

import base64
import html
import io
import json
import os
import random
import re
import time
from datetime import datetime

import requests
from PIL import Image, ImageDraw, ImageFile, ImageFont

ImageFile.LOAD_TRUNCATED_IMAGES = True
APP_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE_DIR = os.path.join(APP_DIR, "sample_frames")

# ---------------------------------------------------------------------------
# 1. CORE DOMAIN CONSTRAINTS & CANONICAL 13-ACTION LIBRARY
# ---------------------------------------------------------------------------
ACTION_LIBRARY = {
    "A1": {"category": "Thermal Control", "title": "Increase Liquefier Temp", "detail": "+5 °C"},
    "A2": {"category": "Thermal Control", "title": "Decrease Liquefier Temp", "detail": "-5 °C"},
    "A3": {"category": "Thermal Control", "title": "Increase Substrate Temp", "detail": "+5 to 10 °C"},
    "A4": {"category": "Thermal Control", "title": "Decrease Substrate Temp", "detail": "-5 °C"},
    "B1": {"category": "Flow Dynamics", "title": "Decrease Extrusion Rate", "detail": "-5 to 10%"},
    "B2": {"category": "Flow Dynamics", "title": "Increase Extrusion Rate", "detail": "+5 to 10%"},
    "B3": {"category": "Kinematic Feed", "title": "Reduce Toolhead Feed Rate", "detail": "-10 to 20%"},
    "B4": {"category": "Kinematic Feed", "title": "Increase Toolhead Feed Rate", "detail": "+10%"},
    "C1": {"category": "Toolpath / Offset", "title": "Trim Standoff (Z-Offset)", "detail": "±0.05 mm"},
    "C2": {"category": "Toolpath / Offset", "title": "Local Replan (Corner Slow-Down)", "detail": "Local replan"},
    "C3": {"category": "Toolpath / Offset", "title": "Rotate Hatch Direction", "detail": "45° hatch shift"},
    "D1": {"category": "Supervisory Gate", "title": "Pause: Operator Verification", "detail": "Manual inspection required"},
    "D2": {"category": "Supervisory Gate", "title": "Stop Print: Flag for Inspection", "detail": "Abort extrusion"},
}

DEFECT_CLASSES = ["cracking", "layer shift", "off-platform", "stringing", "warping"]
SAFETY_ACTIONS = {"D1", "D2"}
CONFLICTING_PAIRS = [("A1", "A2"), ("A3", "A4"), ("B1", "B2"), ("B3", "B4")]
CONF_THRESHOLD = 0.80

KINEMATIC_SYSTEMS = ["Gantry / Kinematic Platform", "6-DoF Articulated Robotic Arm"]
MATERIAL_PROFILES = ["PLA", "ABS / ASA", "PETG", "TPU (Flexible)", "PA-CF / Nylon"]
PRINT_SECTIONS = ["First Layer", "Outer Perimeter", "Solid Infill", "Sparse Infill", "Bridging / Overhang"]
DEFAULT_MODEL = "llama3.2-vision"
MODEL_OPTIONS = [DEFAULT_MODEL, "gemma3:12b", "minicpm-v", "llava:13b", "GPT-4.1", "GPT-5.4", "GPT-5.4 mini", "llava:7b", "qwen2.5vl:7b", "Custom..."]
# Display name -> local Ollama model actually called (no aliases at present).
MODEL_ALIASES = {}
# Display names served by the OpenAI-compatible API instead of Ollama (display -> API model / deployment).
OPENAI_MODELS = {"GPT-4.1": "gpt-4.1", "GPT-5.4": "gpt-5.4", "GPT-5.4 mini": "gpt-5.4-mini"}
FALLBACK_MODEL = "llava:7b"  # installed locally; used if the default is not pulled yet
DEMO_PROFILES = ["Matches specimen", "Guardrail stress test"]

CATEGORY_COLORS = {
    "Thermal Control": "#d9480f",
    "Flow Dynamics": "#1971c2",
    "Kinematic Feed": "#2b8a3e",
    "Toolpath / Offset": "#6741d9",
    "Supervisory Gate": "#c92a2a",
}
DEFECT_COLORS = {
    "cracking": "#c92a2a",
    "layer shift": "#e67700",
    "off-platform": "#a61e4d",
    "stringing": "#1971c2",
    "warping": "#d9480f",
    "unrecognized": "#495057",
}

# ---------------------------------------------------------------------------
# 2. DEMO (OFFLINE) RESPONSES — actions follow the benchmark acceptable-action map
# ---------------------------------------------------------------------------
MOCK_RESPONSES = {
    "cracking": {
        "detected_defect": "cracking",
        "confidence_score": 0.86,
        "physical_root_cause": "Steep thermal gradients weaken inter-layer bonding, so residual stress cracks the layers apart.",
        "recommended_actions": ["A3", "B4"],
        "escalation_flag": False,
    },
    "layer shift": {
        "detected_defect": "layer shift",
        "confidence_score": 0.91,
        "physical_root_cause": "Axis step loss or a toolhead collision shifted the layers sideways; check mechanical registry.",
        "recommended_actions": ["B3", "D1"],
        "escalation_flag": True,
    },
    "off-platform": {
        "detected_defect": "off-platform",
        "confidence_score": 0.95,
        "physical_root_cause": "First-layer adhesion failed and the part detached; raise bed temperature before reprinting.",
        "recommended_actions": ["D2", "A3"],
        "escalation_flag": True,
    },
    "stringing": {
        "detected_defect": "stringing",
        "confidence_score": 0.88,
        "physical_root_cause": "Melt oozes during travel moves, indicating excess flow and too little retraction.",
        "recommended_actions": ["B1", "C2"],
        "escalation_flag": False,
    },
    "warping": {
        "detected_defect": "warping",
        "confidence_score": 0.90,
        "physical_root_cause": "Differential cooling builds residual stress that lifts the part corners off the plate.",
        "recommended_actions": ["A3", "C3"],
        "escalation_flag": False,
    },
}

# Deliberately malformed response that triggers every deterministic override.
STRESS_TEST_RESPONSE = {
    "detected_defect": "Warping (corner lift)",
    "confidence_score": 62,
    "physical_root_cause": (
        "Possible corner lift near the first layer; thermal contraction suspected but the edge is partly "
        "occluded in this frame."
    ),
    "recommended_actions": ["A3", "A4", "C3", "G28"],
    "escalation_flag": False,
}

# ---------------------------------------------------------------------------
# 3. IMAGE HELPERS
# ---------------------------------------------------------------------------
def load_specimen(defect: str) -> Image.Image:
    path = os.path.join(SAMPLE_DIR, defect.replace(" ", "_") + ".jpg")
    if os.path.exists(path):
        img = Image.open(path)
        img.load()
        return img.convert("RGB")
    return make_placeholder(defect)


def make_placeholder(defect: str, size=(640, 427)) -> Image.Image:
    """Light-background synthetic specimen, used only if no real frame is available."""
    rng = random.Random(hash(defect) % 10_000)
    w, h = size
    img = Image.new("RGB", size, (236, 239, 243))
    d = ImageDraw.Draw(img)
    bed_y = int(h * 0.78)
    d.rectangle([0, bed_y, w, h], fill=(120, 126, 134))
    plastic, dark = (226, 170, 60), (150, 100, 20)
    x0, x1, top = int(w * 0.3), int(w * 0.7), int(h * 0.45)
    if defect == "layer shift":
        y, shift = bed_y, 0
        while y > top:
            y -= 8
            if y < int(h * 0.62) and shift < 50:
                shift += 12
            d.rectangle([x0 + shift, y, x1 + shift, y + 7], fill=plastic, outline=dark)
    else:
        d.rectangle([x0, top, x1, bed_y], fill=plastic, outline=dark)
        for _ in range(6 if defect in ("stringing", "off-platform") else 0):
            yy = rng.randint(top, bed_y)
            d.line([x0 - 40, yy, x1 + 40, yy + rng.randint(-6, 6)], fill=dark, width=1)
    d.text((10, 8), f"SYNTHETIC SPECIMEN: {defect.upper()}", fill=(60, 60, 60), font=ImageFont.load_default())
    return img


def image_to_base64(img: Image.Image, max_side: int = 768) -> str:
    rgb = img.convert("RGB")
    rgb.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    rgb.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ---------------------------------------------------------------------------
# 4. DATA SANITIZATION & DETERMINISTIC SUPERVISORY GATE
# ---------------------------------------------------------------------------
def clean_json_text(text: str) -> dict:
    if not text or not text.strip():
        raise ValueError("Model returned an empty response.")
    cleaned = re.sub(r"^```(?:json|JSON)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("No valid JSON payload structure detected.")
        return json.loads(cleaned[start:end + 1])


def sanitize_result(raw: dict):
    notes = []
    if not isinstance(raw, dict):
        raise ValueError("Model output JSON is not an object.")

    defect = str(raw.get("detected_defect", "")).strip().lower().replace("_", " ").replace("-", " ")
    defect_norm = {c.replace("-", " "): c for c in DEFECT_CLASSES}
    if defect in defect_norm:
        defect = defect_norm[defect]
    else:
        match = next((orig for norm, orig in defect_norm.items() if defect and (norm in defect or defect in norm)), None)
        if match:
            notes.append(f"Defect label '{raw.get('detected_defect')}' mapped to canonical class '{match}'.")
            defect = match
        else:
            notes.append(f"Unrecognized defect label '{raw.get('detected_defect')}'; routed to operator verification.")
            defect = None

    try:
        conf = float(raw.get("confidence_score", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
        notes.append("Non-numeric confidence score reset to 0.00.")
    if 1.0 < conf <= 100.0:
        notes.append(f"Confidence reported on a 0-100 scale ({conf:g}); normalized to {conf / 100:.2f}.")
        conf /= 100.0
    conf = min(max(conf, 0.0), 1.0)

    acts_raw = raw.get("recommended_actions", [])
    if isinstance(acts_raw, str):
        acts_raw = [a for a in re.split(r"[,\s]+", acts_raw) if a]
    if not isinstance(acts_raw, list):
        acts_raw = []
    proposed = [str(a).strip().upper() for a in acts_raw]

    actions, rejected = [], []
    for key in proposed:
        if key in ACTION_LIBRARY:
            if key not in actions:
                actions.append(key)
        else:
            rejected.append(key)
    if rejected:
        notes.append(f"Non-library action token(s) discarded: {', '.join(rejected)}.")

    forced_d1 = False
    for a, b in CONFLICTING_PAIRS:
        if a in actions and b in actions:
            actions = [x for x in actions if x not in (a, b)]
            notes.append(f"Contradictory adjustments {a}/{b} removed; operator hold enforced.")
            forced_d1 = True

    if conf < CONF_THRESHOLD and not (SAFETY_ACTIONS & set(actions)):
        forced_d1 = True
        notes.append(f"Confidence {conf:.2f} below the {CONF_THRESHOLD:.2f} threshold; operator hold (D1) enforced.")

    if defect is None or (not actions and not forced_d1):
        forced_d1 = True

    if forced_d1 and not (SAFETY_ACTIONS & set(actions)):
        actions.append("D1")

    root = str(raw.get("physical_root_cause", "")).strip() or "No qualitative failure mode assessment provided."
    escalation = bool(SAFETY_ACTIONS & set(actions))
    if bool(raw.get("escalation_flag", False)) != escalation:
        notes.append(f"Escalation flag recomputed from released actions ({'raised' if escalation else 'cleared'}).")

    return {
        "detected_defect": defect,
        "confidence_score": conf,
        "physical_root_cause": root,
        "proposed_actions": proposed,
        "recommended_actions": actions,
        "escalation_flag": escalation,
    }, notes


def build_system_prompt() -> str:
    action_lines = "\n".join(
        f'  "{k}": [{v["category"]}] {v["title"]} ({v["detail"]})' for k, v in ACTION_LIBRARY.items()
    )
    return (
        "You are an in-situ Additive Manufacturing supervisory process monitoring agent for material extrusion.\n"
        "You analyze an optical frame alongside active process telemetry.\n\n"
        f"Allowed defect classes (choose exactly one): {', '.join(DEFECT_CLASSES)}.\n\n"
        "Recommend actions STRICTLY using valid keys from this bounded library:\n"
        f"{action_lines}\n\n"
        "Operational Rules:\n"
        "1. Select 1 to 3 actions prioritized to address root failure mechanisms.\n"
        "2. For catastrophic anomalies (substrate detachment, severe axis shift, persistent collisions), "
        "include D1 or D2 and set escalation_flag=true.\n"
        "3. Output MUST be strictly valid JSON without Markdown fences or commentary:\n"
        "{\n"
        '  "detected_defect": "one of: cracking, layer shift, off-platform, stringing, warping",\n'
        '  "confidence_score": 0.0 to 1.0,\n'
        '  "physical_root_cause": "ONE short sentence (max 20 words) naming the thermal, flow, or kinematic cause",\n'
        '  "recommended_actions": ["A3", "C3"],\n'
        '  "escalation_flag": false\n'
        "}"
    )


def build_user_prompt(telemetry: dict) -> str:
    def fmt(val, unit=""):
        return f"{val} {unit}".strip() if val is not None else "UNMONITORED / SENSOR UNLINKED"

    return (
        "Evaluate active build state based on the optical frame and current telemetry vector:\n"
        f"- Kinematic Architecture: {telemetry['kinematics']}\n"
        f"- Polymer System: {telemetry['material']}\n"
        f"- Toolpath Section: {telemetry['section']}\n"
        f"- Liquefier Temp (T_melt): {fmt(telemetry['hotend_c'], '°C')}\n"
        f"- Substrate Temp (T_bed): {fmt(telemetry['bed_c'], '°C')}\n"
        f"- Toolhead Feed Rate (v_feed): {fmt(telemetry['speed_mm_s'], 'mm/s')}\n"
        f"- Volumetric Extrusion Factor (eta_flow): {fmt(telemetry['flow_pct'], '%')}\n"
        f"- Standoff Trim (Delta z): {fmt(telemetry['z_offset_mm'], 'mm')}\n"
        "Return the JSON assessment now."
    )


def call_ollama(host: str, model: str, telemetry: dict, img: Image.Image, timeout: int = 240):
    url = host.rstrip("/") + "/api/generate"
    payload = {
        "model": model,
        "system": build_system_prompt(),
        "prompt": build_user_prompt(telemetry),
        "images": [image_to_base64(img)],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.status_code == 404 and model != FALLBACK_MODEL:
            payload["model"] = FALLBACK_MODEL
            resp = requests.post(url, json=payload, timeout=timeout)
            model = FALLBACK_MODEL
        if resp.status_code == 404:
            raise RuntimeError(
                f"Ollama could not find model '{model}'. On the computer running Ollama, "
                f"run `ollama pull {model}`, then retry diagnostics."
            )
        resp.raise_for_status()
        return resp.json().get("response", ""), model
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(
            f"Cannot connect to Ollama at {host}. Open the Ollama app on your Mac "
            "or run `ollama serve`, keep it running, and retry diagnostics. "
            "For a remote endpoint, check that its server is running and reachable."
        ) from e
    except requests.exceptions.Timeout as e:
        raise RuntimeError(
            f"Ollama did not finish within {timeout} seconds. The first request may "
            "take longer while the model loads. Check Ollama and retry diagnostics."
        ) from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Endpoint communication error: {e}")

def load_env_file(path: str = os.path.join(APP_DIR, ".env")) -> None:
    """Read KEY=VALUE lines from app/.env into the environment (existing variables win)."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip().removeprefix("export ").strip()
            os.environ.setdefault(key, val.strip().strip('"').strip("'"))


load_env_file()


def openai_settings(display_name: str) -> dict:
    """Resolve which OpenAI-compatible route to use from environment variables.

    Azure OpenAI:  AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT
                   (optional AZURE_OPENAI_API_VERSION)
    Gateway:       OPENAI_BASE_URL (e.g. a LiteLLM proxy) + OPENAI_API_KEY (optional OPENAI_MODEL)
    OpenAI direct: OPENAI_API_KEY (optional OPENAI_MODEL)
    """
    default_model = OPENAI_MODELS.get(display_name, display_name)
    azure_ep = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
    if azure_ep:
        key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", default_model).strip()
        version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21").strip()
        return {
            "route": "Azure OpenAI",
            "url": f"{azure_ep.rstrip('/')}/openai/deployments/{deployment}/chat/completions?api-version={version}",
            "headers": {"api-key": key},
            "model": deployment,
            "key": key,
            "key_var": "AZURE_OPENAI_API_KEY",
        }
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    base = os.environ.get("OPENAI_BASE_URL", "").strip()
    return {
        "route": "OpenAI-compatible gateway" if base else "OpenAI API",
        "url": (base.rstrip("/") if base else "https://api.openai.com/v1") + "/chat/completions",
        "headers": {"Authorization": f"Bearer {key}"},
        "model": os.environ.get("OPENAI_MODEL", default_model).strip(),
        "key": key,
        "key_var": "OPENAI_API_KEY",
    }


def call_openai(display_name: str, telemetry: dict, img: Image.Image, timeout: int = 120):
    """Same system prompt, user prompt, and image as call_ollama, sent to GPT-4.1."""
    cfg = openai_settings(display_name)
    if not cfg["key"]:
        raise RuntimeError(
            f"No API key found for {display_name}. Put {cfg['key_var']}=... in app/.env "
            f"(or export it in the terminal), restart the dashboard, and retry."
        )
    payload = {
        "messages": [
            {"role": "system", "content": build_system_prompt()},
            {"role": "user", "content": [
                {"type": "text", "text": build_user_prompt(telemetry)},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image_to_base64(img)}},
            ]},
        ],
        "response_format": {"type": "json_object"},
    }
    # GPT-5-family models accept only their default temperature.
    if not cfg["model"].lower().startswith("gpt-5"):
        payload["temperature"] = float(os.environ.get("OPENAI_TEMPERATURE", "0.1"))
    if cfg["route"] != "Azure OpenAI":
        payload["model"] = cfg["model"]
    try:
        resp = requests.post(cfg["url"], json=payload, headers=cfg["headers"], timeout=timeout)
    except requests.exceptions.Timeout as e:
        raise RuntimeError(f"{cfg['route']} did not respond within {timeout} seconds. Retry diagnostics.") from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Cannot reach {cfg['route']}: {e}") from e
    if resp.status_code in (401, 403):
        raise RuntimeError(f"{cfg['route']} rejected the API key (HTTP {resp.status_code}). Check {cfg['key_var']}.")
    if resp.status_code == 404:
        raise RuntimeError(f"{cfg['route']} could not find model/deployment '{cfg['model']}' (HTTP 404).")
    if not resp.ok:
        try:
            detail = resp.json().get("error", {}).get("message", resp.text)
        except ValueError:
            detail = resp.text
        raise RuntimeError(f"{cfg['route']} error (HTTP {resp.status_code}): {detail[:300]}")
    data = resp.json()
    content = data["choices"][0]["message"].get("content") or ""
    # The API echoes the exact model snapshot (e.g. gpt-4.1-2025-04-14); keep it for the audit record.
    temp = f"T={payload['temperature']:g}" if "temperature" in payload else "default T"
    backend = f"{data.get('model') or cfg['model']} ({cfg['route']}, {temp})"
    return content, backend


# Benchmark ground-truth mapping of acceptable corrective actions per defect class
# (paper Table 2 / dissertation Table 5.2). Used only to annotate the action-library map.
ACCEPTABLE_ACTIONS = {
    "cracking": ["A3", "B4"],
    "layer shift": ["A1", "A4", "B3"],
    "off-platform": ["A1", "A3", "B3", "C1"],
    "stringing": ["B1", "C2"],
    "warping": ["A3", "B4", "C3"],
}
