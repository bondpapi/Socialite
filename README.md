# 🎟️ Socialite – AI Event Discovery Agent

[![Created by](https://img.shields.io/badge/Created%20by-Michael%20Bond-blue?style=flat-square)](https://github.com/bondpapi)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

Socialite is an AI-powered event discovery assistant that helps you find concerts, shows, festivals, and other activities in your city.

It consists of:

- A **FastAPI backend** that aggregates events from multiple providers, exposes a simple REST API, and hosts an AI agent.
- A **Streamlit frontend** that provides a lightweight UI with:
  - **Discover** – personalized event feed
  - **Chat** – natural-language AI assistant
  - **Settings** – user profile & preferences

---

## ✨ Features

- **Multi-provider aggregation**
  - Fetches events from several providers (e.g. ticketing sites, local listings).
  - Normalizes data into a single event schema.
  - Deduplicates and sorts events by start time.

- **Upcoming events only**
  - Backend filters out past events.
  - Only events from **today onwards** are returned.

- **Smart AI agent**
  - Uses OpenAI's Chat Completions API to interpret user requests.
  - Calls tools for:
    - Event search (`tool_search_events`)
    - Saving preferences
    - Retrieving preferences
    - Subscribing to digests (stubbed)
  - Falls back gracefully to a direct search if the agent times out or fails.

- **User profile & personalization**
  - Per-user profile with:
    - Username & user ID
    - Home city & country (ISO-2, e.g. `LT`, `US`, `GB`)
    - Search window (`days_ahead`, `start_in_days`)
    - Keywords & passions/interests
  - Discover & Chat both use these settings for recommendations.

- **Streamlit diagnostics**
  - Sidebar shows:
    - API base URL
    - Connection status
    - Per-request latency
  - Debug expanders for:
    - Search parameters
    - Raw API responses
    - Agent responses (when enabled)

---

## Architecture

The system follows a layered architecture with the following components:

**Frontend (Streamlit UI)**
- User interface for discovering events and chatting with the AI agent
- Manages user profiles and preferences
- Displays personalized event recommendations

↓

**API Layer (FastAPI)**
- RESTful endpoints for events, profiles, and agent chat
- Request validation and error handling
- CORS and metrics middleware

↓

**Service Layer**
- **Aggregator**: Coordinates multiple event providers in parallel
- **Recommender**: Ranks events based on user preferences
- **Guardrails**: Content filtering and safety checks
- **Agent**: AI-powered conversational assistant

↓

**Provider Layer**
- **Ticketmaster**: Official event listings
- **Kakava**: Local event aggregator
- **ICS Feed**: Calendar-based events
- **Web Discovery**: Scrapes allowed domains
- **Mock Provider**: Testing and development

↓

**External Services**
- Event APIs (Ticketmaster, SeatGeek, etc.)
- AI/LLM providers (OpenAI, Anthropic)
- News and content APIs

↓

**Data Layer**
- SQLite database for user profiles and saved events
- In-memory caching for performance
- Session state management

### Key Flows

**Discover Tab**

Streamlit app.py → GET /profile/<user_id> → GET /events/search

Displays normalized events sorted by date, filtered to upcoming only.

**Chat Tab**
Streamlit app.py → POST /agent/chat

Backend `/agent/chat`:
1. Tries root AI agent (`agent.py`) using tools
2. If it fails or times out, falls back to:
   - Direct `search_events_sync(...)` via aggregator, or
   - A simple "generic help" reply

---

## ⚙️ Requirements

- Python 3.11+ (recommended)
- A virtual environment (venv, conda, etc.)
- OpenAI API key (for the agent)
- Optional: Docker and Docker Compose (for containerized deployment)

---

## 🚀 Getting Started (Local)

### 1. Clone the repository

```bash
git clone <your-repo-url> social_agent_ai
cd social_agent_ai
```

### 2. Create & activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate      # Windows (PowerShell or CMD)
```

### 3. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a .env file in the project root (or export these variables in your shell):

```ini
# FastAPI / agent
OPENAI_API_KEY=your_openai_api_key_here

# Base URL used by the Streamlit app to reach the backend
SOCIALITE_API=http://127.0.0.1:8000

# Provider-specific keys (if any)
# TICKETMASTER_API_KEY=...
# OTHER_PROVIDER_SECRET=...
```

### 5. Run the backend (FastAPI)

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Check it's up:

```bash
curl http://127.0.0.1:8000/
curl http://127.0.0.1:8000/events/providers
curl http://127.0.0.1:8000/agent/status
```

### 6. Run the frontend (Streamlit)

In another terminal (same virtual env):

```bash
streamlit run app.py
```

Open the URL that Streamlit prints (usually http://localhost:8501) and you should see the Socialite UI.

---

## Configuration & Environment

### Core Variables

**`SOCIALITE_API`**

Base URL of the FastAPI backend that the Streamlit app talks to.

Examples:
- Local: http://127.0.0.1:8000
- Render: https://socialite-7wkx.onrender.com

**`OPENAI_API_KEY`**

Required for the root AI agent (agent.py).

Without this, /agent/chat will fall back to the simple, non-LLM agent.

### Provider Configuration

Each provider under providers/ may have its own settings, for example:


```bash
BILIETAI_API_BASE=...
BILESU_SERVISS_API_BASE=...
# etc.
```

See individual provider modules for details (they usually read os.getenv(...) inside).

---

## 🧠 AI Agent Behaviour

The root agent (agent.py) uses OpenAI's function-calling API with the following tools:

- **`tool_search_events`**
  - Calls `services.aggregator.search_events_sync`
  - Parameters: `city`, `country`, `days_ahead`, `start_in_days`, `include_mock`, `query`

- **`tool_save_preferences`**
  - Persists `home_city`, `home_country`, `passions` via `services.storage`

- **`tool_get_preferences`**
  - Fetches stored preferences for the user

- **`tool_subscribe_digest`**
  - Stub for subscriptions; records intent but does not yet send real digests

### The agent loop:

1. Receives the user message and system prompt.
2. Optionally calls one or more tools using OpenAI tool calls.
3. Feeds tool results back into the model.
4. Returns a final natural-language reply + events (if any).

The agent has an internal timeout and low retry count to keep responses fast and avoid long-running calls on Render/Streamlit Cloud.

### Fallback behavior

If the agent fails or times out, `/agent/chat`:
- Logs the reason in debug
- Returns a simplified fallback response, which the UI shows with a yellow banner
- Optionally performs a direct event search as a backup

---

## 🧪 Diagnostics & Testing

### Backend health

```bash
# Backend status
curl -s http://127.0.0.1:8000/health | jq .

# Agent status
curl -s http://127.0.0.1:8000/agent/status | jq .

# Direct event search
curl -s "http://127.0.0.1:8000/events/search?city=Vilnius&country=LT&days_ahead=60" | jq .
```

### Agent tests from terminal

```bash
curl -s -X POST "http://127.0.0.1:8000/agent/chat" \
  -H "Content-Type: application/json" \
  -d '{
        "user_id": "demo-user",
        "username": "demo",
        "message": "Show me upcoming events in Vilnius",
        "city": "Vilnius",
        "country": "LT"
      }' | jq .
```

You should see:
- `ok: true`
- A natural-language answer
- A non-empty `items` list

---

## 🐛 Troubleshooting

### Streamlit shows "The AI agent had trouble replying (network or timeout issue)…"

This means the request to `/agent/chat` failed or timed out.

**Checklist:**
- Backend is reachable:
  - `/agent/status` returns JSON.
- `OPENAI_API_KEY` is set and valid.
- Providers are not timing out excessively.
- Render / hosting platform is not cold-starting or throttling.

The app will still fall back to a direct event search to avoid showing a blank screen.

### No events are returned

**Check your Settings tab:**
- Home City and Country (ISO-2) are set correctly.
- Days ahead isn't too small.

**Check raw search:**
- Use the sidebar diagnostics in Streamlit.
- Or call `/events/search` directly via curl.

Remember: the backend filters out past events, so you'll only see events whose `start_time` is ≥ current time.

---

## 📦 Deployment Notes

You can deploy:
- **Backend** to a service like Render, Fly.io, or Heroku.
- **Frontend** to Streamlit Cloud.

**Key things to align:**
- Set `SOCIALITE_API` in the Streamlit Cloud secrets to the public URL of your backend.
- Make sure both sides use HTTPS in production.
- Configure provider API keys as environment variables on your hosting platform.

---

## 🗺️ Roadmap

Potential future improvements:
- Real email or Telegram digests for subscriptions.
- Richer event ranking using:
  - User preferences
  - Implicit feedback (saves, clicks)
- More providers and better geo-coverage.
- Caching layer for popular searches.
- Authenticated user accounts.

---

## 📄 License

MIT License

**Built by Michael Bond** | [GitHub](https://github.com/bondpapi)