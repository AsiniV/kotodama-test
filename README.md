# Kotodama - Modular Multi-Agent Game Generation Service

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Godot 4.3+](https://img.shields.io/badge/Godot-4.3+-blue.svg?logo=godot-engine)](https://godotengine.org/)

## 🎮 Overview

**Kotodama (言霊)** is a modular multi-agent game generation service built on Godot 4.3+. It uses 11 specialized AI agents orchestrated via LangGraph to generate complete, playable games from natural language descriptions.

### Core Features

- **14-Step Wizard**: Intuitive game creation with cascading compatibility logic
- **Multi-Agent Pipeline**: 11 specialized agents (Designer, Architect, Quest Designer, Dialogue Writer, Art Director, Coder, QA, Playtester, etc.)
- **Three-Tier Uniqueness**: Core engine (stable), Content (generated per request), Lore RAG (user's knowledge base)
- **Incremental Updates**: Safe module updates with automatic rollback on failure
- **Procedural Generation**: BSP, Cellular Automata, Wave Function Collapse for levels
- **Quest & Dialogue Systems**: State machine graphs and branching dialogue trees
- **AI Playtester**: Automated testing with bot-player simulation
- **Localization Support**: Automatic text extraction and key management
- **Asset Pipeline**: Stable Diffusion integration with metadata tracking

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (Next.js)                     │
│   Wizard UI │ Live Preview │ Lore Manager │ Dashboard      │
└─────────────────────────────────────────────────────────────┘
                            │ WebSocket/REST
┌─────────────────────────────────────────────────────────────┐
│                    Backend (FastAPI + LangGraph)            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Agent Orchestration Pipeline             │  │
│  │                                                       │  │
│  │  Designer → Architect → QuestDesigner → DialogueWriter│  │
│  │      ↓                                              ↓  │  │
│  │  ArtDirector → LevelGenerator → Coder → QA → Playtest│  │
│  │                                                       │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  Database: PostgreSQL + PGVector │ Storage: MinIO          │
└─────────────────────────────────────────────────────────────┘
                            │ Headless CLI
┌─────────────────────────────────────────────────────────────┐
│                  Godot 4.3+ Core Engine                     │
│   Scene Manager │ Signal Bus │ State Machine │ Input System│
│   Modules: Player │ Inventory │ Quest │ Dialogue │ Save    │
└─────────────────────────────────────────────────────────────┘
```

## 📁 Project Structure

```
kotodama/
├── backend/                 # Python FastAPI backend
│   ├── agents/             # 11 specialized AI agents
│   ├── api/                # REST API endpoints
│   ├── core/               # Configuration, guards, utilities
│   ├── db/                 # Database session & models
│   ├── models/             # SQLAlchemy ORM models
│   ├── schemas/            # Pydantic validation schemas
│   ├── services/           # Business logic services
│   └── utils/              # Helper functions
├── frontend/               # Next.js 15 frontend
├── godot_core/             # Immutable Godot core engine
├── docker/                 # Docker configurations
├── configs/                # Configuration files
├── tests/                  # Test suites
└── scripts/                # Development & deployment scripts
```

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- Docker & Docker Compose
- Godot 4.3+ (for local testing)
- Ollama (for local LLM inference)
- Node.js 20+ (for frontend development)

### 1. Clone Repository

```bash
git clone https://github.com/your-org/kotodama.git
cd kotodama
```

### 2. Environment Setup

```bash
cp .env.example .env
# Edit .env with your configuration
```

### 3. Start Infrastructure (Docker)

```bash
docker-compose up -d postgres minio redis
```

### 4. Install Dependencies

```bash
pip install -e ".[dev]"
```

### 5. Initialize Database

```bash
python scripts/init_db.py
```

### 6. Start Development Server

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Visit `http://localhost:8000/docs` for API documentation.

## 🤖 Agent Pipeline

| # | Agent | Responsibility |
|---|-------|----------------|
| 1 | **Game Designer** | Converts wizard input + Lore into structured JSON GDD |
| 2 | **Architect** | Plans Godot scene structure and Signal contracts |
| 3 | **Quest Designer** | Generates quests as state machine graphs |
| 4 | **Dialogue Writer** | Creates branching dialogue trees |
| 5 | **Art Director** | Generates image prompts and manages asset slots |
| 6 | **Coder** | Writes clean GDScript for modules |
| 7 | **QA & Integrator** | Validates syntax, signals, and guard compliance |
| 8 | **AI Playtester** | Runs headless tests and stability scoring |
| 9 | **Prompt Refiner** | Improves prompts based on generation history |
| 10 | **Level Generator** | Procedural level generation (BSP, CA, WFC) |
| 11 | **Localization Manager** | Extracts text strings for i18n |

## 📊 Development Phases

| Phase | Focus | Weeks | Status |
|-------|-------|-------|--------|
| 0 | Foundation (Docker, DB, Core) | 1-2 | ✅ In Progress |
| 1 | Core Agents + Infrastructure | 3-4 | 📋 Planned |
| 2 | RAG + Incremental Updates | 5-6 | 📋 Planned |
| 3 | UI/UX (Wizard, Preview) | 7-8 | 📋 Planned |
| 4 | Art Pipeline | 9-10 | 📋 Planned |
| 5 | Quest & Dialogue Systems | 11-12 | 📋 Planned |
| 6 | Procedural Levels | 13-14 | 📋 Planned |
| 7 | Enhanced Playtester + Save/Load | 15-16 | 📋 Planned |
| 8 | Localization + Monetization | 17-18 | 📋 Planned |
| 9 | Export + Marketplace + Launch | 19-20 | 📋 Planned |

## 💰 Subscription Plans

| Plan | Price | Credits/Month | Features |
|------|-------|---------------|----------|
| **Free** | $0 | Limited | Watermark, Web export only |
| **Starter** | $9.99/mo | 50 | APK export, No watermark |
| **Pro** | $29.99/mo | 200 | Priority queue, HD assets |
| **Studio** | $99.99/mo | 1000 | White-label, API access |

## 🔒 Security & Guards

- **Code Guards**: All generated files pass through `guard.py` before disk write
- **AST Scanner**: Blocks dangerous APIs (`OS.execute`, `HTTPClient`, filesystem access)
- **Sandboxed Execution**: Generation and testing in ephemeral Docker containers
- **Perceptual Hash**: Asset plagiarism detection for marketplace

## 📝 License

MIT License - see [LICENSE](LICENSE) file for details.

---

**Built with ❤️ using Godot, FastAPI, LangGraph, and Next.js**
