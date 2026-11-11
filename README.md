# FDM VLM Operator Dashboard

A guardrailed dashboard where a vision-language model (GPT-4.1, GPT-5.4, or a local Ollama model) looks at a 3D-print image, names the FDM defect, and suggests corrective actions from a fixed 13-action library for an operator to approve.

**Full step-by-step guide: open [README.html](README.html) in your browser.**

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sh get_sample_frames.sh          # optional example images
cp .env.example .env             # then paste your OpenAI API key into .env
.venv/bin/python app_nicegui.py  # opens http://localhost:8600
```

Never commit `.env`; it holds your API key and is ignored by git.

Recommendations are advisory only: the dashboard never controls the printer.
