"""Compatibility exports for Agent Governance ORM models.

Canonical definitions live in ``app.features.agent_governance.models``.
"""

from app.features.agent_governance.models import (
    AgentDefinition,
    AgentDefinitionRevision,
    MCPServer,
    SkillDefinition,
    SkillDefinitionRevision,
)

__all__ = [
    "AgentDefinition",
    "AgentDefinitionRevision",
    "SkillDefinition",
    "SkillDefinitionRevision",
    "MCPServer",
]
