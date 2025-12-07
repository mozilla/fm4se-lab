"""
ai_experiments

Experiments around using LLM agents (CrewAI + DeepSeek) to analyse Firefox
crash reports, missing information, and patch synthesis.
"""

from . import config, bugzilla, phabricator, diff_utils, context_builders, agents, tasks, pipelines  # noqa: F401