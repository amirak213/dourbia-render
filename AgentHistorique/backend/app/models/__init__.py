"""SQLAlchemy models package.

Import model modules here so Alembic autogenerate discovers all tables.
"""

from app.database import Base
from app.models.circuit import Circuit
from app.models.circuit_monument import CircuitMonument
from app.models.destination import Destination
from app.models.document_chunk import DocumentChunk
from app.models.memory import ChatMessage, UserPreference, UserSession
from app.models.monument import Monument
from app.models.monument_distance import MonumentDistance
from app.models.reference_circuit import ReferenceCircuit

__all__ = [
    "Base",
    "ChatMessage",
    "Circuit",
    "CircuitMonument",
    "Destination",
    "DocumentChunk",
    "Monument",
    "MonumentDistance",
    "ReferenceCircuit",
    "UserPreference",
    "UserSession",
]
