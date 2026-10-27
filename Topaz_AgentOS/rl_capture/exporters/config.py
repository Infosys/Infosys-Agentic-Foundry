"""Default export shaping configuration."""

DEFAULT_LABEL_MAPPING = {
    "approve": 1.0,
    "up": 1.0,
    "success": 1.0,
    "complete": 1.0,
    "pass": 0.5,
    "tie": 0.0,
    "reject": -1.0,
    "down": -1.0,
    "block": -1.0,
    "failed": -1.0,
    "dlq": -1.0,
}

DEFAULT_EXPORT_FILTERS = {
    "min_confidence": 0.0,
    "channels": [],
    "raw_labels": [],
    "fidelity": [],
}
