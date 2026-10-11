def route(item):
    """Decide adaptation type. Default: persistent memory."""
    if item.get("ephemeral"): return "working_context"
    if item.get("repeated_capability_gap") and item.get("retrieval_ok") and item.get("authorized_data"): return "parameter_learning_candidate"
    return "persistent_memory"
