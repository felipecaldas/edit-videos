import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from videomerge.services.subtitles import (
    map_language_to_whisper_code,
    run_whisper_segments,
    run_whisper_segments_with_info,
    build_chunks_from_words,
    write_srt_from_chunks,
    _format_timestamp_srt,
    _clean_chunk_text,
)
from videomerge.models import TranscriptionRequest, TranscriptionResponse
from videomerge.routers.subtitles import transcribe_mp3
from fastapi import HTTPException


class TestLanguageMapping:
    """Test language mapping functionality."""

    def test_portuguese_mapping(self):
        """Test Portuguese language mappings."""
        assert map_language_to_whisper_code("Portuguese") == "pt"
        assert map_language_to_whisper_code("portuguese") == "pt"
        assert map_language_to_whisper_code("PORTUGUESE") == "pt"

    def test_english_variants_mapping(self):
        """Test English language variant mappings."""
        assert map_language_to_whisper_code("English (US)") == "en"
        assert map_language_to_whisper_code("english (us)") == "en"
        assert map_language_to_whisper_code("English (AU)") == "en"
        assert map_language_to_whisper_code("English (CA)") == "en"
        assert map_language_to_whisper_code("English (UK)") == "en"

    def test_standard_codes_mapping(self):
        """Test standard language code mappings."""
        assert map_language_to_whisper_code("en") == "en"
        assert map_language_to_whisper_code("pt") == "pt"
        assert map_language_to_whisper_code("en-US") == "en"
        assert map_language_to_whisper_code("en-AU") == "en"
        assert map_language_to_whisper_code("en-CA") == "en"
        assert map_language_to_whisper_code("en-GB") == "en"

    def test_english_general_mapping(self):
        """Test general English mapping."""
        assert map_language_to_whisper_code("English") == "en"
        assert map_language_to_whisper_code("english") == "en"

    def test_unknown_language_fallback(self):
        """Test that unknown languages default to en."""
        assert map_language_to_whisper_code("UnknownLang") == "en"
        assert map_language_to_whisper_code("fr") == "en"
        assert map_language_to_whisper_code("") == "en"

    def test_whitespace_handling(self):
        """Test that whitespace is properly stripped."""
        assert map_language_to_whisper_code("  Portuguese  ") == "pt"
        assert map_language_to_whisper_code("\tEnglish (US)\n") == "en"


class TestTimestampFormatting:
    """Test SRT timestamp formatting."""

    def test_format_timestamp_srt(self):
        """Test SRT timestamp formatting."""
        assert _format_timestamp_srt(0) == "00:00:00,000"
        assert _format_timestamp_srt(1.5) == "00:00:01,500"
        assert _format_timestamp_srt(61.123) == "00:01:01,123"
        assert _format_timestamp_srt(3661.999) == "01:01:01,999"


class TestTextCleaning:
    """Test text cleaning functionality."""

    def test_clean_chunk_text_basic(self):
        """Test basic text cleaning."""
        tokens = ["Hello", "world"]
        assert _clean_chunk_text(tokens, False) == "Hello world"

    def test_clean_chunk_text_with_punctuation(self):
        """Test text cleaning removes trailing punctuation when not last."""
        tokens = ["Hello", "world", "!"]
        assert _clean_chunk_text(tokens, False) == "Hello world"

    def test_clean_chunk_text_keep_punctuation_when_last(self):
        """Test text cleaning keeps punctuation when it's the last chunk."""
        tokens = ["Hello", "world", "!"]
        assert _clean_chunk_text(tokens, True) == "Hello world!"

    def test_clean_chunk_text_with_quotes(self):
        """Test text cleaning removes quotes."""
        tokens = ['"Hello"', "'world'"]
        assert _clean_chunk_text(tokens, True) == "Hello world"


class TestSRTGeneration:
    """Test SRT file generation."""

    def test_write_srt_from_chunks(self, tmp_path):
        """Test writing SRT file from chunks."""
        chunks = [
            {"start": 0, "end": 2, "text": "Hello world"},
            {"start": 2, "end": 4, "text": "How are you"},
        ]

        srt_path = tmp_path / "test.srt"
        write_srt_from_chunks(chunks, srt_path)

        content = srt_path.read_text(encoding="utf-8")
        expected = "1\n00:00:00,000 --> 00:00:02,000\nHello world\n\n2\n00:00:02,000 --> 00:00:04,000\nHow are you\n\n"
        assert content == expected


class TestWhisperIntegration:
    """Test Whisper integration with mocked model."""

    @patch('videomerge.services.subtitles.WhisperModel')
    def test_run_whisper_segments_with_language_mapping(self, mock_whisper_model):
        """Test that run_whisper_segments uses the language mapping."""
        # Setup mock
        mock_model = Mock()
        mock_whisper_model.return_value = mock_model

        mock_segments = [Mock()]
        mock_segments[0].text = "Test transcription"
        mock_segments[0].start = 0.0
        mock_segments[0].end = 2.0
        mock_model.transcribe.return_value = (mock_segments, {})

        # Test with frontend language name
        audio_path = Path("/test/audio.mp3")
        segments = run_whisper_segments(audio_path, language="English (US)")

        # Verify WhisperModel was called with mapped language code
        mock_whisper_model.assert_called_once_with("small", device="cpu", compute_type="int8")
        mock_model.transcribe.assert_called_once_with(
            str(audio_path),
            language="en-US",  # Should be mapped from "English (US)"
            task="transcribe",
            vad_filter=True,
            word_timestamps=True,
        )

        assert segments == mock_segments

    @patch('videomerge.services.subtitles.WhisperModel')
    def test_run_whisper_segments_with_standard_code(self, mock_whisper_model):
        """Test that run_whisper_segments works with standard language codes."""
        # Setup mock
        mock_model = Mock()
        mock_whisper_model.return_value = mock_model

        mock_segments = [Mock()]
        mock_segments[0].text = "Test transcription"
        mock_model.transcribe.return_value = (mock_segments, {})

        # Test with standard language code
        audio_path = Path("/test/audio.mp3")
        segments = run_whisper_segments(audio_path, language="pt")

        # Verify WhisperModel was called with the code as-is
        mock_model.transcribe.assert_called_once_with(
            str(audio_path),
            language="pt",
            task="transcribe",
            vad_filter=True,
            word_timestamps=True,
        )

    @patch('videomerge.services.subtitles.WhisperModel')
    def test_run_whisper_segments_with_unknown_language(self, mock_whisper_model):
        """Test that run_whisper_segments defaults unknown languages to en-US."""
        # Setup mock
        mock_model = Mock()
        mock_whisper_model.return_value = mock_model

        mock_segments = [Mock()]
        mock_model.transcribe.return_value = (mock_segments, {})

        # Test with unknown language
        audio_path = Path("/test/audio.mp3")
        segments = run_whisper_segments(audio_path, language="UnknownLang")

        # Verify WhisperModel was called with en-US as default
        mock_model.transcribe.assert_called_once_with(
            str(audio_path),
            language="en-US",  # Should default to en-US for unknown languages
            task="transcribe",
            vad_filter=True,
            word_timestamps=True,
        )


class TestChunkBuilding:
    """Test chunk building from segments."""

    def test_build_chunks_from_words_basic(self):
        """Test basic chunk building."""
        # Mock segment with words
        mock_segment = Mock()
        mock_segment.words = [
            Mock(word="Hello", start=0.0, end=0.5),
            Mock(word="world", start=0.5, end=1.0),
            Mock(word="how", start=1.0, end=1.5),
            Mock(word="are", start=1.5, end=2.0),
            Mock(word="you", start=2.0, end=2.5),
        ]

        segments = [mock_segment]
        chunks = build_chunks_from_words(segments, max_words=2, min_chunk_duration=0.6)

        # Should create multiple chunks
        assert len(chunks) > 1
        assert all("start" in chunk for chunk in chunks)
        assert all("end" in chunk for chunk in chunks)
        assert all("text" in chunk for chunk in chunks)

    def test_build_chunks_from_words_without_words(self):
        """Test chunk building when segments don't have words."""
        # Mock segment without words
        mock_segment = Mock()
        mock_segment.text = "Hello world how are you"
        mock_segment.start = 0.0
        mock_segment.end = 2.5
        mock_segment.words = None

        segments = [mock_segment]
        chunks = build_chunks_from_words(segments, max_words=2, min_chunk_duration=0.6)

        # Should create chunks by splitting text
        assert len(chunks) > 1
        assert all("start" in chunk for chunk in chunks)
        assert all("end" in chunk for chunk in chunks)
        assert all("text" in chunk for chunk in chunks)

    def test_build_chunks_empty_segments(self):
        """Test chunk building with empty segments."""
        chunks = build_chunks_from_words([])
        assert chunks == []


class TestTranscriptionEndpoint:
    """Test the transcription endpoint."""

    @patch('videomerge.routers.subtitles.run_whisper_segments_with_info')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_file')
    @patch('pathlib.Path.stat')
    def test_transcribe_mp3_success_with_language(self, mock_stat, mock_is_file, mock_exists, mock_transcribe):
        """Test successful transcription with specified language."""
        # Setup mocks
        mock_exists.return_value = True
        mock_is_file.return_value = True
        mock_stat.return_value = Mock(st_size=1000)
        
        # Mock Whisper response
        mock_segment = Mock()
        mock_segment.text = "Hello world"
        mock_info = Mock()
        mock_info.language = "en"
        mock_info.language_probability = 0.95
        mock_transcribe.return_value = ([mock_segment], mock_info)
        
        # Test request
        req = TranscriptionRequest(
            mp3_path="/data/shared/test.mp3",
            language="English",
            model_size="small"
        )
        
        response = transcribe_mp3(req)
        
        assert isinstance(response, TranscriptionResponse)
        assert response.text == "Hello world"
        assert response.detected_language == "en"
        assert response.confidence == 0.95
        mock_transcribe.assert_called_once()

    @patch('videomerge.routers.subtitles.run_whisper_segments_with_info')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_file')
    @patch('pathlib.Path.stat')
    def test_transcribe_mp3_success_auto_detect(self, mock_stat, mock_is_file, mock_exists, mock_transcribe):
        """Test successful transcription with auto-detected language."""
        # Setup mocks
        mock_exists.return_value = True
        mock_is_file.return_value = True
        mock_stat.return_value = Mock(st_size=1000)
        
        # Mock Whisper response
        mock_segment = Mock()
        mock_segment.text = "Olá mundo"
        mock_info = Mock()
        mock_info.language = "pt"
        mock_info.language_probability = 0.88
        mock_transcribe.return_value = ([mock_segment], mock_info)
        
        # Test request without language
        req = TranscriptionRequest(
            mp3_path="/data/shared/test.mp3",
            model_size="small"
        )
        
        response = transcribe_mp3(req)
        
        assert isinstance(response, TranscriptionResponse)
        assert response.text == "Olá mundo"
        assert response.detected_language == "pt"
        assert response.confidence == 0.88
        mock_transcribe.assert_called_once()

    def test_transcribe_mp3_invalid_path(self):
        """Test transcription with invalid path (not in /data/shared)."""
        req = TranscriptionRequest(
            mp3_path="/invalid/path/test.mp3"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            transcribe_mp3(req)
        
        assert exc_info.value.status_code == 400
        assert "must be located in /data/shared" in str(exc_info.value.detail)

    @patch('pathlib.Path.exists')
    def test_transcribe_mp3_file_not_found(self, mock_exists):
        """Test transcription with non-existent file."""
        mock_exists.return_value = False
        
        req = TranscriptionRequest(
            mp3_path="/data/shared/notfound.mp3"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            transcribe_mp3(req)
        
        assert exc_info.value.status_code == 404
        assert "not found" in str(exc_info.value.detail)

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_file')
    def test_transcribe_mp3_not_a_file(self, mock_is_file, mock_exists):
        """Test transcription with path that is not a file."""
        mock_exists.return_value = True
        mock_is_file.return_value = False
        
        req = TranscriptionRequest(
            mp3_path="/data/shared/not_a_file"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            transcribe_mp3(req)
        
        assert exc_info.value.status_code == 400
        assert "not a file" in str(exc_info.value.detail)

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_file')
    @patch('pathlib.Path.stat')
    def test_transcribe_mp3_wrong_extension(self, mock_stat, mock_is_file, mock_exists):
        """Test transcription with non-MP3 file."""
        mock_exists.return_value = True
        mock_is_file.return_value = True
        mock_stat.return_value = Mock(st_size=1000)
        
        req = TranscriptionRequest(
            mp3_path="/data/shared/test.wav"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            transcribe_mp3(req)
        
        assert exc_info.value.status_code == 400
        assert ".mp3 extension" in str(exc_info.value.detail)

    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_file')
    @patch('pathlib.Path.stat')
    def test_transcribe_mp3_empty_file(self, mock_stat, mock_is_file, mock_exists):
        """Test transcription with empty file."""
        mock_exists.return_value = True
        mock_is_file.return_value = True
        mock_stat.return_value = Mock(st_size=0)
        
        req = TranscriptionRequest(
            mp3_path="/data/shared/empty.mp3"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            transcribe_mp3(req)
        
        assert exc_info.value.status_code == 400
        assert "empty" in str(exc_info.value.detail)
