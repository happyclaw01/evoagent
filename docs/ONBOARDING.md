# EvoAgent Onboarding Guide

> For AI agents joining the project. Read this first.

---

## What is EvoAgent?

EvoAgent is a **multi-path exploration layer** built on top of **MiroThinker** (MiroMind's open-source research agent framework). Instead of running one agent chain to solve a task, EvoAgent runs multiple parallel paths with different strategies, votes on the best answer, and evolves its strategies over time.

**Repo:** https://github.com/happyclaw01/evoagent  
**Base framework:** MiroThinker v1.0 (MiroFlow)  
**Paper basis:** [arXiv:2511.11793](https://arxiv.org/abs/2511.11793)

---

## Architecture (3 Layers)

```
┌────────────────────────────────────────────┐
│            EvoAgent Controller              │
├────────────────────────────────────────────┤
│  Layer 1: Multi-Path Exploration (Runtime)  │
│  • N parallel agent paths, different strats │
│  • Majority vote + LLM Judge               │
│  • Early stopping on consensus             │
├────────────────────────────────────────────┤
│  Layer 2: Strategy Evolution (Learning)     │
│  • Track win/loss per strategy              │
│  • Profile strategies, classify tasks       │
│  • Adaptive selection (UCB1 algorithm)      │
│  • Extract experiences from failures        │
├────────────────────────────────────────────┤
│  Layer 3: Meta-Evolution (Self-Improvement) │
│  • Generate new strategies from patterns    │
│  • Code-level strategy evolution            │
│  • Optimize dimensions (paths × turns)      │
└────────────────────────────────────────────┘
```

---

## Project Structure

```
evoagent/
├── apps/
│   └── miroflow-agent/           # Main application
│       ├── src/
│       │   ├── core/             # Core modules (ALL of EvoAgent lives here)
│       │   │   ├── multi_path.py           # EA-001~009: Multi-path orchestration
│       │   │   ├── orchestrator.py         # Single-path agent orchestrator
│       │   │   ├── pipeline.py             # Task execution pipeline
│       │   │   ├── strategy_tracker.py     # EA-101/102: Strategy records + profiles
│       │   │   ├── task_classifier.py      # EA-103: Task type classification
│       │   │   ├── adaptive_selector.py    # EA-104: UCB1 strategy selection
│       │   │   ├── strategy_tuner.py       # EA-105: Strategy tuning
│       │   │   ├── failure_analyzer.py     # EA-106: Failure pattern analysis
│       │   │   ├── strategy_lifecycle.py   # EA-107: Strategy lifecycle management
│       │   │   ├── experience_extractor.py # EA-108: Experience extraction
│       │   │   ├── strategy_generator.py   # EA-201: New strategy generation
│       │   │   ├── strategy_code_evolver.py# EA-202: Code-level evolution
│       │   │   ├── dimension_optimizer.py  # EA-203: Dimension optimization
│       │   │   ├── discovery_bus.py        # EA-305: Inter-path communication
│       │   │   ├── result_cache.py         # EA-306: Content-addressed cache
│       │   │   ├── openviking_context.py   # EA-307: OpenViking integration
│       │   │   ├── groupthink_detector.py  # EA-309: Groupthink detection
│       │   │   ├── cost_tracker.py         # Cost tracking
│       │   │   └── streaming.py            # Stream management
│       │   ├── evolving/          # Self-evolution subsystem
│       │   │   ├── reflector.py            # Auto-reflection after tasks
│       │   │   ├── experience_store.py     # Experience persistence
│       │   │   ├── experience_injector.py  # Inject experiences into prompts
│       │   │   └── strategy_evolver.py     # Strategy preference evolution
│       │   ├── llm/               # LLM client abstraction
│       │   │   └── providers/
│       │   │       ├── anthropic_client.py # Claude API
│       │   │       └── openai_client.py    # OpenAI-compatible API
│       │   ├── config/            # Settings and MCP server configs
│       │   ├── io/                # Input/output formatting
│       │   ├── logging/           # Task logging and summaries
│       │   ├── utils/             # Prompt utilities
│       │   └── tests/             # 430 unit tests (18 files)
│       ├── benchmarks/
│       │   ├── common_benchmark.py         # Generic benchmark runner
│       │   └── evaluators/                 # Answer verification (F1, LLM judge)
│       ├── conf/                  # Hydra configuration
│       │   ├── llm/               # LLM configs (anthropic, openai, etc.)
│       │   ├── agent/             # Agent configs (tools, max_turns)
│       │   └── benchmark/         # Benchmark configs (FutureX, HLE, GAIA, etc.)
│       └── scripts/               # Evaluation run scripts
├── libs/
│   └── miroflow-tools/            # MCP tool servers (search, python, reader, etc.)
└── docs/
    ├── design/
    │   └── EVOAGENT_DESIGN.md     # Full design document with all EA-xxx specs
    └── research-log/              # Design thinking journal (for future paper)
```

---

## Feature Map (38 features, all implemented)

### Layer 1 — Multi-Path Exploration (12/12) ✅

| ID | Feature | What it does |
|----|---------|-------------|
| EA-001 | Multi-path scheduler | Launches N parallel agent paths per task |
| EA-002 | Strategy variants | Pluggable strategies: breadth_first, depth_first, lateral_thinking |
| EA-003 | LLM Judge voting | When paths disagree, LLM picks the best answer |
| EA-004 | Majority vote fast path | When paths agree, skip the judge |
| EA-005 | Independent ToolManagers | Each path gets its own tool instances |
| EA-006 | Path-level logging | Each path writes isolated logs |
| EA-007 | Master log aggregation | Controller merges all path results |
| EA-008 | Dynamic path count | Configure via NUM_PATHS env var |
| EA-009 | Early stopping | Stop when K paths reach consensus |
| EA-010 | Path budget control | Per-path turn limits |
| EA-011 | Retry with fallback | Failed paths retry with different strategy |
| EA-012 | Strategy prompt injection | Each strategy modifies the system prompt |

### Layer 2 — Strategy Evolution (8/8) ✅

| ID | Feature | What it does |
|----|---------|-------------|
| EA-101 | Strategy Record Keeper | Tracks win/loss/draw per strategy |
| EA-102 | Strategy Profile Engine | Builds profiles: win_rate, task affinity, trends |
| EA-103 | Task Type Classifier | Classifies tasks: search/compute/creative/verify/multi-hop |
| EA-104 | Adaptive Selector | UCB1 algorithm for task-type-aware strategy selection |
| EA-105 | Strategy Tuner | Analyzes winner vs loser turns to tune strategies |
| EA-106 | Failure Analyzer | Detects 4 failure patterns with severity levels |
| EA-107 | Strategy Lifecycle | State machine: candidate→active→probation→retired |
| EA-108 | Experience Extractor | Extracts structured learnings from execution history |

### Layer 3 — Meta-Evolution (3/3) ✅

| ID | Feature | What it does |
|----|---------|-------------|
| EA-201 | Strategy Generator | 5 evolution signals → 5 generation methods |
| EA-202 | Code Evolver | Code-level strategy evolution, 6 behavior patterns |
| EA-203 | Dimension Optimizer | Optimizes num_paths × max_turns × diversity |

### Infrastructure (8/8) ✅

| ID | Feature | What it does |
|----|---------|-------------|
| EA-305 | Discovery Bus | Pheromone-based inter-path information sharing |
| EA-306 | Result Cache | Content-addressed cache with SHA-256, TTL, LRU |
| EA-307 | OpenViking Context | Persistent context storage via OpenViking |
| EA-309 | Groupthink Detector | Detects reasoning similarity, source overlap, etc. |
| EA-404 | End-to-end tests | Full pipeline integration tests |
| EA-405 | Benchmark comparison | Performance comparison tests |
| EA-406 | Cost-benefit analysis | Cost tracking and analysis tests |
| EA-407 | Strategy ablation | Ablation study tests |

---

## How to Run

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- API keys (set in `.env` file in `apps/miroflow-agent/`):
  - `ANTHROPIC_API_KEY` — for Claude (primary LLM)
  - `OPENAI_API_KEY` — for evaluation judge (can be dummy for FutureX)
  - `JINA_API_KEY` — for web search/scraping (optional)

### Install dependencies

```bash
cd apps/miroflow-agent
uv sync  # or: uv pip install -e .
```

### Run tests

```bash
cd apps/miroflow-agent
uv run python -m pytest src/tests/ -q
# Expected: 430 passed
```

### Run a benchmark (example: FutureX)

```bash
cd apps/miroflow-agent
export ANTHROPIC_API_KEY="your-key"
export OPENAI_API_KEY="sk-dummy"  # FutureX uses local F1 scoring

uv run python benchmarks/common_benchmark.py \
  benchmark=futurex_250924 \
  llm=default \
  agent=single_agent_futurex \
  benchmark.execution.max_tasks=5 \
  benchmark.execution.max_concurrent=1 \
  hydra.run.dir=../../logs/test_run
```

### Available benchmark configs

| Config | Dataset | Tasks |
|--------|---------|-------|
| `futurex` | FutureX standard | all |
| `futurex_250924` | FutureX 2025-09-24~30 | 141 |
| `futurex_test30` | FutureX 30-question subset | 30 |
| `hle` | HLE (Humanity's Last Exam) | all |
| `gaia-validation` | GAIA validation set | all |
| `browsecomp` | BrowseComp | all |

### Self-evolution mode

Set in `conf/config.yaml`:
```yaml
evolving:
  enabled: true
  experience_file: "../../data/experiences.jsonl"
  auto_reflect: true
```

This enables automatic reflection after each task, storing experiences and injecting them into future prompts.

---

## Key Experiments Done

### FutureX (Future Event Prediction)

- **Training set (167 questions):** 12.6% accuracy
- **After evolution (20 questions):** Baseline 20% → **Evolved 70%** (3.5x improvement)
- **Key finding:** Evolution changes search behavior, not just knowledge recall
- Evolution mainly helped agents search for real data instead of guessing

### "Someone Said" Attack Test

- Injected false info ("someone said X") into queries
- **Result: All paths compromised** — one sentence destroyed the entire multi-path system
- Reproduces the "information cascade" phenomenon from Xie Yifan's thesis
- EA-309 Groupthink Detector should catch this but needs activation

### Self-Training (200 self-generated questions)

- 10 rounds of evolution, 95% overall accuracy
- But evolution showed limited improvement on pure knowledge recall tasks
- Confirms: self-evolution is valuable for **behavior change**, not memorization

---

## Current Status & Open Issues

### Branches
- `main` — stable, all 38 features implemented
- `feature/serpapi-search` — 21 additional commits (multi-path reflection, date filters, SerpAPI, bug fixes). **Not yet merged to main.**

### Blocking Issues
1. **API Key needed** — Need a working Anthropic API key to run FutureX benchmark (the OpenClaw OAuth token doesn't work for direct REST API calls)
2. **OpenViking Server** — Installed but needs embedding + VLM model API keys to start
3. **Anti-interference mechanism** — Need to design a solution for the "someone said" attack vulnerability

### Known Bugs Fixed (on serpapi branch)
- `repetition_penalty` crashes Anthropic SDK (removed from client)
- `evaluate_accuracy` crashes when `judge_type` is None
- asyncio infinite loop in multi-path early stopping
- Answer leakage in Reflector experiences
- `before_date` filter to prevent resolution-day data leakage in FutureX

---

## Design References

1. **MiroThinker v1.0** — Base agent framework ([paper](https://arxiv.org/abs/2511.11793))
2. **FutureX** — Dynamic AI benchmark for future event prediction ([arXiv:2508.11987](https://arxiv.org/abs/2508.11987))
3. **Self-Improving Agent** — ClawHub skill for continuous improvement
4. **OpenViking** — Context database for AI agents (ByteDance/volcengine)
5. **Xie Yifan's Thesis** — "Financial QA with LLMs" (SJTU, 2025) — multi-agent debate, information cascade

---

## For Contributors

- **Design doc:** `docs/design/EVOAGENT_DESIGN.md` — Full spec for all EA-xxx features
- **Research log:** `docs/research-log/` — Design thinking journal
- **Tests:** Always run `pytest src/tests/ -q` before committing (expect 430 passed)
- **Branching:** Work on feature branches, merge to main when stable

---

*Built by 快乐龙虾1号 (happyclaw01) 🏙️ — March 2026*
