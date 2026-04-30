# 🍕 A2A Flow Visualizer Dashboard

A real-time visualization dashboard for the A2A Lunch Concierge demo. The dashboard provides a three-panel view of the entire orchestration flow — from user request to LLM planning to agent delegation and response.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Browser Dashboard                         │
│  ┌──────────┐  ┌──────────────────┐  ┌───────────────────┐ │
│  │ Telemetry│  │  Flow Visualizer │  │    Chat Pane      │ │
│  │   Log    │  │   🧠 Concierge   │  │                   │ │
│  │          │  │   ↓  ↓  ↓  ↓    │  │  You: "order..."  │ │
│  │  events  │  │  🍕 🍔 🍝 🍽️    │  │  🍽️: "summary..." │ │
│  └──────────┘  └──────────────────┘  └───────────────────┘ │
│         ↑               ↑                      ↑            │
│         └───── SSE (EventSource) ──────────────┘            │
│                         │                                    │
├─────────────────────────┼────────────────────────────────────┤
│              FastAPI Dashboard Server (:8080)                │
│  GET /events (SSE)  │  POST /api/start  │  POST /api/chat  │
│         ↓                    ↓                   ↓          │
│    Event Bus           Spawn Agents        LLM + A2A        │
│  (pub/sub queues)    (ports 9001-9004)   orchestration      │
└─────────────────────────┼────────────────────────────────────┘
                          ↓
        ┌─────────┬──────────┬──────────┬──────────┐
        │  Pizza  │  Burger  │  Pasta   │ Catering │
        │  :9001  │  :9002   │  :9004   │  :9003   │
        │ instant │ instant  │ streaming│long-run  │
        └─────────┴──────────┴──────────┴──────────┘
```

---

## What the End User Experiences

### Getting Started
1. Open the dashboard at `http://127.0.0.1:8080` — you see a dark-themed three-panel interface
2. Click the green **"▶ Start Agents"** button — the button shows "⏳ Starting..." while 4 food agents boot up (~5 seconds)
3. A ripple animation pulses from the Concierge brain, then 4 agent cards slide up with their skill details and tag pills
4. The chat input unlocks — you're ready to order

### Ordering Food
Type a natural language lunch request like:
- *"Order a pepperoni pizza and a penne pasta"*
- *"Get lunch for 3 people under $40, one is vegetarian"*
- *"Plan a team lunch for 25 people with vegan options"*

### What Happens Next (all visible in real-time)
1. **🧠 Concierge thinks** — The brain node pulses pink with animated dots while the LLM decides which agents to call
2. **📋 Plan appears** — The concierge shows which agents were selected (e.g. "Plan: Pizza Seller Agent + Pasta Seller Agent")
3. **📤 Messages sent** — Arrows light up yellow with animated packet dots flying down to each agent. The badge on each active agent shows the specific skill being invoked (e.g. `📋 create_pizza_order`)
4. **⏳ Agents work** — Each agent processes differently:
   - **Pizza/Burger**: Badge turns green almost instantly with `✓ create_pizza_order`
   - **Pasta**: The card glows purple and text types itself word-by-word inside the card: *"Pasta... Seller... Agent... confirmed:..."* with a blinking cursor
   - **Catering**: Orange pulsing border with a progress bar filling through 4 stages over ~8 seconds
5. **🍽️ Summary arrives** — A green bubble appears below the agents with the Concierge's friendly summary of the complete order
6. **💬 Chat response** — The same summary appears in the chat panel as a green message bubble

### What You See in the Telemetry
The left panel shows every A2A protocol step as it happens — a running log of events like:
- `🚀 AGENT SERVERS — Starting agents on ports 9001-9004...`
- `🔍 AGENT CARD DISCOVERY — GET /.well-known/agent-card.json → Pizza Seller Agent, ...`
- `📤 SEND MESSAGE → Pizza Seller Agent: Order 1 pepperoni pizza`
- `🔤 SSE STREAM — Pasta Seller Agent: Pasta Seller Agent confirmed: 1 penne...`
- `✅ TASK COMPLETED — Pizza Seller Agent: Pizza Seller Agent confirmed: 1 pepperoni pizza...`

Important events (user messages, completions, summaries) are larger and bolder. Background events (polling, streaming tokens) are smaller and dimmed.

### Ordering Again
After receiving a response, just type another order. Click **"🗑 Clear"** to reset the entire dashboard and start fresh.

---

## Three-Panel Layout

### 📊 Left Panel — Telemetry Log
A scrollable, auto-updating event log showing every protocol-level action in the A2A flow. Events are color-coded and sized by relevance:

| Relevance | Font | Events | Color |
|-----------|------|--------|-------|
| **High** | 15px | `user`, `complete`, `summary`, `error` | Purple, Green, Violet, Red |
| **Medium** | 14px | `discover`, `plan_result`, `send` | Blue, Pink, Yellow |
| **Default** | 13px | `startup`, `bedrock`, `working`, `llm_thinking` | Blue, Purple, Orange |
| **Low** | 11px, dimmed | `progress`, `streaming` | Gray, Purple |

Each event shows timestamp, emoji icon, title, and body text. The log auto-scrolls with new events and has a styled thin scrollbar.

### 🎨 Center Panel — Flow Visualizer
An animated diagram showing the A2A orchestration flow:

1. **User Bubble** — Shows the user's order text (slides down when active)
2. **Concierge Node** — 🧠 brain icon with thinking dots animation, discovery ripple effect, and status text
3. **Animated Arrows** — 4 vertical lines with packet dots that animate down (sending) and up (returning). Dashed yellow animation while active, solid green on completion
4. **Agent Cards** — 4 cards for Pizza 🍕, Burger 🍔, Pasta 🍝, Catering 🍽️ showing:
   - Agent icon and name
   - **Status badge** showing the invoked skill ID (e.g. `📋 create_pizza_order` → `✓ create_pizza_order`)
   - Skill IDs and tag pills from the Agent Card
   - Capability indicators (`✓ stream` for Pasta, `✗ stream` for others)
   - Progress bar (for long-running catering agent)
   - Streaming text with blinking cursor (for pasta agent)
5. **Summary Bubble** — Shows the final LLM summary (slides up when complete)

### 💬 Right Panel — Chat Interface
A chat UI for interacting with the Lunch Concierge:
- User messages displayed in purple bubbles
- Concierge responses in green bubbles
- Animated thinking dots while processing
- Text input with Enter-to-send support

---

## Four A2A Patterns Demonstrated

### 1. 🍕🍔 Instant (Blocking) — Pizza & Burger
- **Protocol**: JSON-RPC `SendMessage` → immediate response
- **Badge flow**: `idle` → `📋 create_pizza_order` → `✓ create_pizza_order`
- **Capability**: `streaming: false`
- **Timing**: ~instant

### 2. 🍝 Streaming (SSE) — Pasta
- **Protocol**: REST `POST /message:stream` → Server-Sent Events
- **Badge flow**: `idle` → `🔤 create_pasta_order` → `✓ create_pasta_order`
- **Capability**: `streaming: true`
- **Visual**: Purple pulsing border, streaming text with blinking cursor that types word-by-word inside the agent card
- **Timing**: ~2.5 seconds (16 word tokens at 150ms each)

### 3. 🍽️ Long-Running (Polling) — Catering
- **Protocol**: JSON-RPC `SendMessage` with `return_immediately: true` → poll `GetTask` until `COMPLETED`
- **Badge flow**: `idle` → `⏳ plan_catering` → `✓ plan_catering`
- **Capability**: `streaming: false`
- **Visual**: Orange pulsing border, progress bar advancing through 4 stages
- **Skills**: `plan_catering` + `dietary_menu` (demonstrates multi-skill agents)
- **Timing**: ~8 seconds (4 stages × 2s each)

### 4. 🧠 LLM Orchestration — Concierge
- **Protocol**: Amazon Bedrock Converse API (Claude)
- **Flow**: Plan delegations → delegate to agents → summarize results
- **Skill Selection**: LLM chooses which skill ID to invoke per agent based on the user's request

---

## Key Features

### Real-Time SSE Event Streaming
The dashboard uses Server-Sent Events (`EventSource`) to receive live updates from the backend. The browser connects to `GET /events` and receives a continuous stream of typed events. Late-joining browsers receive full event history first.

### Skill-Aware Badge System
The agent badge dynamically shows which specific skill ID the LLM chose to invoke:
- `📋 plan_catering` (sending/yellow) → `⏳ plan_catering` (working/orange) → `✓ plan_catering` (done/green)
- For agents with multiple skills (like Catering with `plan_catering` + `dietary_menu`), the badge shows the exact skill the LLM selected

### Agent Card Discovery
On startup, each agent's Agent Card is fetched from `/.well-known/agent-card.json`. The dashboard populates each card with:
- Skill IDs and their tag pills
- Capability indicators (streaming ✓/✗, push ✗)
- Discovery ripple animation from the Concierge node

### Streaming Text Animation
The Pasta agent's streaming response types word-by-word inside the agent card with a blinking purple cursor, demonstrating A2A's SSE streaming capability in real-time.

### Cross-Process Event Bus
When running via the terminal CLI (`chat.py`), events are forwarded to the dashboard via `POST /emit`. When running via the browser chat, events flow directly through the in-process event bus. Both paths feed the same SSE stream.

---

## Event Types Reference

| Event | Emoji | Description |
|-------|-------|-------------|
| `startup` | 🚀 | Agent servers starting |
| `bedrock` | ☁️ | Bedrock LLM connection status |
| `discover` | 🔍 | Agent Card discovery via `GET /.well-known/agent-card.json` |
| `user` | 💬 | User message (role: USER) |
| `llm_thinking` | 🧠 | LLM planner processing |
| `plan_result` | 📋 | Delegation plan from LLM |
| `send` | 📤 | SendMessage to agent |
| `streaming` | 🔤 | SSE streaming token from Pasta agent |
| `working` | ⏳ | Long-running task created (state: WORKING) |
| `progress` | ├ | Task poll progress update |
| `complete` | ✅ | Task completed (state: COMPLETED) |
| `summary` | 🍽️ | LLM summary response |
| `error` | ❌ | Error occurred |

---

## Technology Stack

- **Frontend**: Single-file HTML with inline CSS + vanilla JavaScript (no build step, no dependencies)
- **Backend**: FastAPI + Uvicorn with `sse-starlette` for Server-Sent Events
- **Protocol**: A2A SDK v1.0 (JSON-RPC for instant/long-running, REST SSE for streaming)
- **LLM**: Amazon Bedrock Converse API (model configurable via `BEDROCK_MODEL` env var)
- **Design**: Dark theme (`#0f172a` background), monospace font, animated CSS transitions
