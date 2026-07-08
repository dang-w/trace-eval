"""Run configuration.

The model string lives here as a config value (not hardcoded deep in the runner)
so it can be swapped without touching the run loop. The CLI can override it per run.
"""

# A current, capable default. Override per run via the CLI's --model flag.
DEFAULT_MODEL = "claude-opus-4-8"

# Sample-task answers are short and verifiable, so a small cap keeps runs cheap and
# fast. Raise this for tasks that need longer outputs.
DEFAULT_MAX_TOKENS = 1024
