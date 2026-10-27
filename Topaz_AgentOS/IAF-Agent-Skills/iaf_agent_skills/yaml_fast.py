"""YAML loading backed by LibYAML (the C parser) when it is available.

Why: PyYAML ships a compiled LibYAML extension but does not use it unless you ask.
On this tenant the difference is measured at ~8x — and the workstream index parses
6.3 MB of YAML on every page load, so that is 4.2s versus 0.5s of wall clock.

Scope, deliberately narrow:

* READ ONLY. There is a CSafeDumper too, but writing is left alone — a different
  dumper can re-flow existing files (quoting, key order, line wrapping), which would
  produce enormous, meaningless diffs in the tenant's checked-in YAML and risks
  changing content. Loading cannot alter a file, so it carries no such risk.
* `CSafeLoader` accepts the same safe YAML subset as `SafeLoader`: no arbitrary object
  construction. This is a speed change, not a capability change.
* Falls back silently to the pure-Python loader where LibYAML is absent, so the module
  is safe to import anywhere.

The faster parser is a floor-raiser, not the fix. Parsing megabytes of execution
history to render a summary page is waste in any language; see the caching in
workstream_store.list_summaries() for the part that actually removes the work.
"""

from __future__ import annotations

from typing import Any

import yaml

try:  # pragma: no cover - depends on the local PyYAML build
    from yaml import CSafeLoader as _SafeLoader
    USING_LIBYAML = True
except ImportError:  # pragma: no cover
    from yaml import SafeLoader as _SafeLoader  # type: ignore[assignment]
    USING_LIBYAML = False


def safe_load(text: str) -> Any:
    """Drop-in replacement for yaml.safe_load using LibYAML when present."""
    return yaml.load(text, Loader=_SafeLoader)
