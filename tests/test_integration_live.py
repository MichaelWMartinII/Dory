"""
Integration test — live Ollama memory extraction.

Skipped automatically if Ollama is not running or qwen3:8b is not available.

This test simulates a realistic developer session: a scripted conversation about
building a new project. The Observer pipeline calls qwen3:8b to extract durable
facts into the Dory graph, then assertions verify the graph is populated correctly.
"""
import pytest

OLLAMA_MODEL = "qwen3:8b"


def _ollama_available() -> bool:
    try:
        import ollama
        models = ollama.list()
        names = [m.get("name", m.get("model", "")) for m in models.get("models", [])]
        return any(OLLAMA_MODEL in name for name in names)
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _ollama_available(),
    reason=f"Ollama not running or {OLLAMA_MODEL} not available",
)

# ---------------------------------------------------------------------------
# Scripted developer conversation
# ---------------------------------------------------------------------------
# A realistic back-and-forth about starting a new FastAPI project. Claude plays
# the user; the assistant lines represent what a developer partner might say.
# The conversation contains several durable facts worth extracting:
#   - New REST API project for tracking workout sessions
#   - Stack: FastAPI + PostgreSQL, fully async with asyncpg
#   - Deployment: Docker on a self-hosted VPS
#   - Future plan: scikit-learn ML for plateau detection
# ---------------------------------------------------------------------------

CONVERSATION = [
    ("user",
     "Starting a new project today — a REST API for tracking workout sessions. "
     "Going with FastAPI and PostgreSQL."),
    ("assistant",
     "Good choices. FastAPI gives you automatic OpenAPI docs out of the box. "
     "Using SQLAlchemy or asyncpg for the DB layer?"),
    ("user",
     "asyncpg directly — I want full async performance without ORM overhead. "
     "The app will be write-heavy so raw async queries make sense."),
    ("assistant",
     "Makes sense for a workout tracker. Will you containerize it?"),
    ("user",
     "Yes, Docker on a self-hosted VPS. Prefer self-hosting to keep infrastructure costs low."),
    ("assistant",
     "Solid plan. Postgres + FastAPI containers behind nginx is a proven setup. "
     "Any ML components planned?"),
    ("user",
     "Not at launch, but I want to add workout plateau detection later. "
     "Probably scikit-learn — nothing fancy, just time-series features."),
    ("assistant",
     "scikit-learn with a rolling feature window would work well. "
     "You could train weekly with new session data."),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_observer_logs_all_turns(db_path):
    """Observer must log every conversation turn to the episodic store."""
    from dory.graph import Graph
    from dory.pipeline.observer import Observer

    g = Graph(path=db_path)
    obs = Observer(g, db_path=db_path, model=OLLAMA_MODEL, backend="ollama", threshold=100)

    for role, content in CONVERSATION:
        obs.add_turn(role, content)

    stats = obs.flush()
    assert stats["turns_logged"] == len(CONVERSATION)


def test_observer_runs_extraction(db_path):
    """flush() must trigger at least one LLM extraction call."""
    from dory.graph import Graph
    from dory.pipeline.observer import Observer

    g = Graph(path=db_path)
    obs = Observer(g, db_path=db_path, model=OLLAMA_MODEL, backend="ollama", threshold=100)

    for role, content in CONVERSATION:
        obs.add_turn(role, content)

    stats = obs.flush()
    assert stats["extractions_run"] >= 1
    assert stats["errors"] == 0


def test_observer_writes_nodes_to_graph(db_path):
    """After extraction, the graph should contain meaningful technology nodes."""
    from dory.graph import Graph
    from dory.pipeline.observer import Observer

    g = Graph(path=db_path)
    obs = Observer(g, db_path=db_path, model=OLLAMA_MODEL, backend="ollama", threshold=100)

    for role, content in CONVERSATION:
        obs.add_turn(role, content)

    obs.flush()

    nodes = g.all_nodes()
    assert len(nodes) >= 2, f"Expected >= 2 nodes, got {len(nodes)}"

    # At least one of the key technologies should be recognized
    node_text = " ".join(n.content.lower() for n in nodes)
    known_terms = ["fastapi", "postgresql", "postgres", "docker", "asyncpg",
                   "scikit", "sklearn", "workout", "api", "python"]
    found = [t for t in known_terms if t in node_text]
    assert found, f"No expected terms found in extracted nodes. Contents: {[n.content for n in nodes]}"


def test_observer_creates_edges(db_path):
    """Extracted nodes should be connected with typed edges."""
    from dory.graph import Graph
    from dory.pipeline.observer import Observer

    g = Graph(path=db_path)
    obs = Observer(g, db_path=db_path, model=OLLAMA_MODEL, backend="ollama", threshold=100)

    for role, content in CONVERSATION:
        obs.add_turn(role, content)

    obs.flush()

    edges = g.all_edges()
    assert len(edges) >= 1, "Expected at least one edge after extraction"


def test_dory_memory_full_pipeline(db_path):
    """End-to-end: DoryMemory add_turns → flush → query returns relevant context."""
    from dory.memory import DoryMemory

    mem = DoryMemory(
        db_path=db_path,
        extract_model=OLLAMA_MODEL,
        extract_backend="ollama",
    )

    for role, content in CONVERSATION:
        mem.add_turn(role, content)

    stats = mem.flush()

    # Consolidation stats present
    assert "pruned_edges" in stats

    # Graph is queryable and returns relevant context
    context = mem.query("FastAPI PostgreSQL project")
    assert isinstance(context, str)
    assert len(context) > 20  # not empty, not just the "no memories" placeholder
