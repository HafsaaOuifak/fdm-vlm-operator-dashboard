# FDM VLM Operator Dashboard

A guardrailed dashboard where a vision-language model (GPT-4.1, GPT-5.4, GPT-5.4 mini, or a local Ollama model) looks at a 3D-print image, names the FDM defect, and suggests corrective actions from a fixed 13-action library for an operator to approve. It never controls the printer.

## 1. Get the project on your computer

You need [Git](https://git-scm.com/downloads) and [Python 3.10+](https://www.python.org/downloads/).

```bash
git clone https://github.com/HafsaaOuifak/fdm-vlm-operator-dashboard.git
cd fdm-vlm-operator-dashboard
```

No Git? On the repo page click **Code → Download ZIP**, unzip it, and open a terminal in that folder.

## 2. Install (first time only)

macOS / Linux:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## 3. Example images (optional)

```bash
sh get_sample_frames.sh
```

Downloads five example frames from the public FDM defect dataset of Hu et al. (2024). You can also upload your own PNG/JPG in the app.

## 4. Choose a model

- **GPT models**: copy the settings file and paste your own OpenAI API key into it:
  ```bash
  cp .env.example .env      # Windows: copy .env.example .env
  ```
  Then open `.env` and fill in `OPENAI_API_KEY=...`. Azure OpenAI and LiteLLM gateways are also supported (see `.env.example`).
- **Local models (free, offline)**: install [Ollama](https://ollama.com/download), keep it open, then run `ollama pull llama3.2-vision`.
- **Nothing installed?** Use **Demo / mock mode** (settings icon next to the model) to try the interface with scripted answers.

`.env` holds your secret key. It is ignored by git; never commit or share it.

## 5. Run

```bash
.venv/bin/python app_nicegui.py        # Windows: .venv\Scripts\python app_nicegui.py
```

The browser opens http://localhost:8600. Press `Ctrl + C` in the terminal to stop. Port busy? Use `MONITOR_PORT=8601` before the command.

## 6. Use it

1. **Browse** to upload an image, or pick a **Benchmark specimen**.
2. Pick a model and adjust the machine and process values.
3. Click **Run diagnostics** to see the defect, confidence, root cause, six safety checks, and the actions released for approval.
4. **Export audit (.json)** saves a record of the decision.

## Working on the code

| File | What it does |
|---|---|
| `app_nicegui.py` | The web interface (sidebar, four result boxes, audit export) |
| `core.py` | Action library, prompts, model calls (OpenAI / Ollama), deterministic safety checks |
| `get_sample_frames.sh` | Downloads the example images |
| `.env.example` | Template for API settings |

To get the latest changes later: `git pull`.
