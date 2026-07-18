"""Versioned local-AI contracts, persistence, and deterministic resolution."""

from autoedit.ai.activity_from_turns import (
    ActivityProjectionError,
    ArtifactImportError,
    ArtifactImportResult,
    activity_from_turns,
    import_artifact,
    project_resolved_turns,
)
from autoedit.ai.artifacts import AIArtifactStore, ArtifactIntegrityError
from autoedit.ai.contracts import AIResultArtifact
from autoedit.ai.gpu_measurement import GPUSample, summarize_gpu_acceptance, validate_sampling
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
    "ActivityProjectionError",
    "ArtifactImportError",
    "ArtifactImportResult",
    "GPUSample",
    "activity_from_turns",
    "import_artifact",
    "project_resolved_turns",
    "summarize_gpu_acceptance",
    "validate_sampling",
    "ConfirmedSpeakerMapping",
    "PriorConfirmedSpeaker",
    "SpeakerIdentityEvidence",
    "SpeakerMappingResolution",
    "SpeakerResolutionPolicy",
    "resolve_speaker_mappings",
]
