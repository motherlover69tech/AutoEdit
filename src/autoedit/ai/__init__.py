"""Versioned local-AI contracts, persistence, and deterministic resolution."""

from autoedit.ai.artifacts import AIArtifactStore, ArtifactIntegrityError
from autoedit.ai.contracts import AIResultArtifact
from autoedit.ai.speaker_mapping import (
    ConfirmedSpeakerMapping,
    PriorConfirmedSpeaker,
    SpeakerIdentityEvidence,
    SpeakerMappingResolution,
    SpeakerResolutionPolicy,
    resolve_speaker_mappings,
)

__all__ = [
    "AIArtifactStore",
    "AIResultArtifact",
    "ArtifactIntegrityError",
    "ConfirmedSpeakerMapping",
    "PriorConfirmedSpeaker",
    "SpeakerIdentityEvidence",
    "SpeakerMappingResolution",
    "SpeakerResolutionPolicy",
    "resolve_speaker_mappings",
]
