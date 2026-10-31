# JARVIS Backend

FastAPI server that connects the JARVIS frontend to Google's Gemini AI.

## Quick Start

### 1. Install Python dependencies

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `backend/.env` and set your Gemini API key:

```
GEMINI_API_KEY=your-actual-api-key
```

Get a key at https://aistudio.google.com/apikey

### 3. Start the backend

```bash
# From the backend/ directory, with the venv activated:
uvicorn main:app --reload
```

The server runs at `http://localhost:8000`.

### 4. Start the frontend (separate terminal)

```bash
# From the project root:
npm run dev
```

The Vite dev server proxies `/api/*` requests to the backend automatically.

## API Endpoints

| Method | Path          | Description                              |
| ------ | ------------- | ---------------------------------------- |
| GET    | `/api/health` | Health check — reports Gemini readiness   |
| POST   | `/api/chat`   | Send message, receive JARVIS AI response |

### POST /api/chat

**Request body:**
```json
{
  "message": "Hello JARVIS",
  "previous_interaction_id": null
}
```

**Response:**
```json
{
  "reply": "Good evening, Sir. How may I assist you?",
  "interaction_id": "interaction-abc123",
  "model": "gemini-3.8-flash"
}
```

## Configuration

All settings live in `backend/.env` (never committed to git):

| Variable                    | Required | Default               | Description                         |
| --------------------------- | -------- | --------------------- | ----------------------------------- |
| `GEMINI_API_KEY`            | Yes      | —                     | Google AI API key                   |
| `GEMINI_MODEL`              | No       | `gemini-3.8-flash`    | Gemini model ID                     |
| `JARVIS_SYSTEM_INSTRUCTION` | No       | *(JARVIS persona)*    | System prompt for the AI            |
| `HOST`                      | No       | `0.0.0.0`             | Server bind address                 |
| `PORT`                      | No       | `8000`                | Server port                         |

## Multi-turn Conversation

The frontend tracks `interaction_id` from each response and sends it back as
`previous_interaction_id` on the next request. This gives Gemini server-side
conversation context without storing chat history on the client.

## Architecture Notes

- **No API keys in the browser.** The Gemini key stays server-side only.
- **Voice recognition / TTS:** Not yet implemented. The current interface
  provides typed text input. Real-time voice streaming is planned for Phase 5.
- **SDK:** Uses `google-genai` (the current recommended SDK), not the
  deprecated `google-generativeai` package.
