"""Repository-wide deterministic test isolation."""
from __future__ import annotations

import os

# Never let a developer/worker's inherited environment turn the test suite into
# a live Ollama workload. Tests that exercise the client pass explicit Settings
# or opt in with monkeypatch inside their own scope.
os.environ["OLLAMA_BASE_URL"] = ""
os.environ["LLM_MODEL"] = ""
