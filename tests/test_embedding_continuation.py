from services.whisperx_service.embedding_continuation import validate_postgap_continuations


def test_postgap_label_continues_when_embedding_is_decisive():
    turns = [
        {"turn_id": "history-s1", "start": 0.0, "end": 0.5, "diarizer_speaker_id": "S1", "overlap": False, "_embedding": [0.0, 1.0]},
        {"turn_id": "pregap-s0", "start": 0.5, "end": 1.0, "diarizer_speaker_id": "S0", "overlap": False, "_embedding": [1.0, 0.0]},
        {"turn_id": "postgap", "start": 4.0, "end": 5.0, "diarizer_speaker_id": "S1", "overlap": False, "_embedding": [0.99, 0.01]},
    ]
    result = validate_postgap_continuations(turns)
    assert result[2]["diarizer_speaker_id"] == "S0"
    assert result[2]["original_diarizer_speaker_id"] == "S1"
    assert result[2]["label_provenance"] == "embedding_continuation"
    assert all("_embedding" not in turn for turn in result)


def test_postgap_label_is_unchanged_without_or_with_ambiguous_embedding():
    no_embeddings = [
        {"turn_id": "a", "start": 0.0, "end": 1.0, "diarizer_speaker_id": "S0", "overlap": False},
        {"turn_id": "b", "start": 2.0, "end": 3.0, "diarizer_speaker_id": "S1", "overlap": False},
    ]
    assert validate_postgap_continuations(list(reversed(no_embeddings))) == no_embeddings

    ambiguous = [
        {"turn_id": "history-s1", "start": 0.0, "end": 0.5, "diarizer_speaker_id": "S1", "overlap": False, "_embedding": [1.0, 0.0]},
        {"turn_id": "pregap-s0", "start": 0.5, "end": 1.0, "diarizer_speaker_id": "S0", "overlap": False, "_embedding": [1.0, 0.0]},
        {"turn_id": "postgap", "start": 3.0, "end": 4.0, "diarizer_speaker_id": "S1", "overlap": False, "_embedding": [0.99, 0.01]},
    ]
    result = validate_postgap_continuations(ambiguous)
    assert result[2]["diarizer_speaker_id"] == "S1"
    assert "label_provenance" not in result[2]


def test_overlap_and_long_gap_never_relabel():
    turns = [
        {"turn_id": "a", "start": 0.0, "end": 1.0, "diarizer_speaker_id": "S0", "overlap": False, "_embedding": [1.0, 0.0]},
        {"turn_id": "b", "start": 7.0, "end": 8.0, "diarizer_speaker_id": "S1", "overlap": False, "_embedding": [1.0, 0.0]},
        {"turn_id": "c", "start": 8.1, "end": 9.0, "diarizer_speaker_id": "S0", "overlap": True, "_embedding": [1.0, 0.0]},
    ]
    result = validate_postgap_continuations(turns)
    assert [turn["diarizer_speaker_id"] for turn in result] == ["S0", "S1", "S0"]
