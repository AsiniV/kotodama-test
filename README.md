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
| 0 | Foundation (Docker, DB, Core) | 1-2 | ✅ Complete |
| 1 | Core Agents + Infrastructure | 3-4 | ✅ Complete |
| 2 | RAG + Incremental Updates | 5-6 | ✅ Complete |
| 3 | UI/UX (Wizard, Preview) | 7-8 | ✅ Complete |
| 4 | Art Pipeline | 9-10 | ✅ Complete |
| 5 | Quest & Dialogue Systems | 11-12 | ✅ Complete |
| 6 | Procedural Levels | 13-14 | ✅ Complete |
| 7 | Enhanced Playtester + Save/Load | 15-16 | ✅ Complete |
| 8 | Localization + Monetization | 17-18 | ✅ Complete |
| 9 | Export + Marketplace + Launch | 19-20 | ✅ Complete |

**🎉 All 10 phases complete! The full Kotodama platform is production-ready.**

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
- **Perceptual Hash**: Asset plagiarism detection for marketplace (0.85 similarity threshold)
- **Module Marketplace Security**: Automatic static code analysis before publication

## 🚀 Phase 9: Export + Marketplace (Latest)

### Multi-Platform Export

| Platform | Format | Tools | Status |
|----------|--------|-------|--------|
| **Web** | HTML5 + WASM | Godot Headless, Brotli | ✅ Ready |
| **Android** | APK/AAB | Godot Headless, Fastlane | ✅ Ready |
| **iOS** | IPA | Godot Headless, Fastlane | ✅ Ready |
| **Windows** | EXE | Godot Headless | ✅ Ready |
| **macOS** | APP/DMG | Godot Headless | ✅ Ready |
| **Linux** | X11/Wayland | Godot Headless | ✅ Ready |

### Module Marketplace

- **Security Scanner**: AST-based detection of malicious code patterns
- **Plagiarism Detection**: Perceptual hashing for asset verification
- **Categories**: Player Controllers, Enemy AI, Inventory, Quest Systems, Dialogue, UI, Audio, VFX
- **Pricing**: Free or credit-based (author sets price, 25-30% platform commission)
- **Search**: Full-text search with filters by category, rating, price

### Key Services

```python
# Marketplace Service
marketplace_service.submit_module()      # Submit with auto-security scan
marketplace_service.search_modules()     # Search with filters
marketplace_service.check_plagiarism()   # Perceptual hash comparison
marketplace_service.validate_code()      # AST security validation

# Export Service
export_service.create_export_job()       # Queue export request
export_service.build_web()               # Web export with compression
export_service.build_android()           # APK with signing
export_service.build_ios()               # IPA with signing
export_service.upload_to_store()         # Fastlane store upload
```

## 📝 License

MIT License - see [LICENSE](LICENSE) file for details.

---

## 🎯 Production Status

**Kotodama v2.0 is production-ready!** All 10 development phases have been completed and tested:

- ✅ **11 AI Agents** fully operational via LangGraph orchestration
- ✅ **Quest & Dialogue Systems** with state machine graphs and branching trees
- ✅ **Procedural Level Generation** (BSP, Cellular Automata, WFC)
- ✅ **AI Playtester** with bot-player simulation and stability scoring
- ✅ **Save/Load System** with automatic serialization
- ✅ **Localization Support** with automatic text extraction
- ✅ **Asset Pipeline** with Stable Diffusion integration
- ✅ **Lore RAG** with PGVector for personalized universes
- ✅ **Module Marketplace** with AST security scanning and plagiarism detection
- ✅ **Multi-Platform Export** (Web, Android, iOS, Windows, macOS, Linux)

### Quick Links

- [API Documentation](http://localhost:8000/docs) - FastAPI Swagger UI
- [Technical Specification](SPECIFICATION.md) - Full v2.0 spec
- [Phase 9 Report](PHASE9_COMPLETION_REPORT.md) - Latest deliverables

---

**Built with ❤️ using Godot 4.3+, FastAPI, LangGraph, and Next.js 15**
