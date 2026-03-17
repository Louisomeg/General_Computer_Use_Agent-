# =============================================================================
# Agent Registry — discover and get agents by name
# =============================================================================
# Usage:
#   from agents.registry import register, get_agent, list_agents
#
# Register an agent (in its own file):
#   @register("cad")
#   class CADAgent: ...
#
# Get an agent (from the planner):
#   agent = get_agent("cad", client=client, executor=executor)
#   result = agent.execute(task)

_AGENTS = {}


def register(name: str):
    """Decorator that registers an agent class by name."""
    def wrapper(cls):
        _AGENTS[name] = cls
        return cls
    return wrapper


def get_agent(name: str, **kwargs):
    """Create and return an agent instance by name.

    Any kwargs are passed to the agent's __init__.
    Raises KeyError if the agent name isn't registered.
    """
    if name not in _AGENTS:
        available = ", ".join(_AGENTS.keys()) or "none"
        raise KeyError(f"Unknown agent: '{name}'. Available: {available}")
    return _AGENTS[name](**kwargs)


def list_agents() -> list[str]:
    """Return all registered agent names."""
    return list(_AGENTS.keys())
