"""AI-agent layer: local analysis and cloud-augmented coaching."""

from .coach import CoachAgent, CoachRequest, CoachResponse
from . import progress

__all__ = ["CoachAgent", "CoachRequest", "CoachResponse", "progress"]
