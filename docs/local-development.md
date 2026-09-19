# Local Development Guide (Zero-AWS)

OpsMind is designed to run 100% locally on your machine without requiring any AWS account, cloud credentials, or internet access.

---

## 1. Prerequisites

- Python 3.11, 3.12, or 3.13
- Git
- (Optional) Docker & Docker Compose
- (Optional) Ollama for local offline LLM inference

---

## 2. Quick Start

### Step 1: Clone and Set Up Virtual Environment

```bash
git clone https://github.com/sasindu345/opsmind.git
cd opsmind

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Configure Environment

Copy the `.env.example` template:

```bash
cp .env.example .env
```

To use Google Gemini (free-tier):
```env
DEPLOYMENT_MODE=local
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key_here
```

To use 100% offline Ollama:
```env
DEPLOYMENT_MODE=local
LLM_PROVIDER=ollama
OLLAMA_MODEL=ollama/llama3:8b
OLLAMA_BASE_URL=http://localhost:11434
```

### Step 3: Start OpsMind Server

```bash
uvicorn src.main:app --reload --port 8000
```

Verify the health endpoint:
```bash
curl http://localhost:8000/healthz
# {"status":"ok","app":"OpsMind","mode":"local"}
```

---

## 3. Running with Docker Compose

To start both the API and the background worker locally:

```bash
docker compose up --build
```

To start with a local Ollama model in one command:
```bash
docker compose --profile local up --build
```

---

## 4. Running the OpsMind Terminal CLI

OpsMind includes an interactive CLI for testing and triage:

```bash
# Run interactive triage on sample errors
python -m src.cli.opsmind_cli triage --service checkout

# List historical incidents
python -m src.cli.opsmind_cli incidents

# Explain a specific incident root cause
python -m src.cli.opsmind_cli explain <incident-id>

# Run background incident worker
python -m src.cli.opsmind_cli worker
```

---

## 5. Running Tests

```bash
pytest -v
ruff check .
```
