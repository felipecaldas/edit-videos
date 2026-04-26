"""Unit tests for TAB-168: fetch_brand_image_params activity and workflow wiring."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# fetch_brand_image_params — Supabase response handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_returns_style_id_and_terms_when_row_found():
    """Returns recraft_style_id and negative_prompt_terms from a valid DB row."""
    from videomerge.temporal.activities import fetch_brand_image_params

    mock_row = [{"recraft_style_id": "style-abc123", "negative_prompt_terms": ["blurry logo", "fake UI"]}]

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = mock_row

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("videomerge.temporal.activities.SUPABASE_URL", "https://test.supabase.co"), \
         patch("videomerge.temporal.activities.SUPABASE_ANON_KEY", "anon-key"), \
         patch("httpx.AsyncClient", return_value=mock_client):

        result = await fetch_brand_image_params("client-42")

    assert result["recraft_style_id"] == "style-abc123"
    assert result["negative_prompt_terms"] == ["blurry logo", "fake UI"]


@pytest.mark.asyncio
async def test_returns_none_style_id_when_not_set():
    """Returns recraft_style_id=None and logs warning when field is absent/null."""
    from videomerge.temporal.activities import fetch_brand_image_params

    mock_row = [{"recraft_style_id": None, "negative_prompt_terms": []}]

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = mock_row

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("videomerge.temporal.activities.SUPABASE_URL", "https://test.supabase.co"), \
         patch("videomerge.temporal.activities.SUPABASE_ANON_KEY", "anon-key"), \
         patch("httpx.AsyncClient", return_value=mock_client):

        result = await fetch_brand_image_params("client-42")

    assert result["recraft_style_id"] is None
    assert result["negative_prompt_terms"] == []


@pytest.mark.asyncio
async def test_returns_empty_params_when_no_row_found():
    """Returns safe empty result when brand_profiles has no row for the client."""
    from videomerge.temporal.activities import fetch_brand_image_params

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = []  # empty list = no matching row

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("videomerge.temporal.activities.SUPABASE_URL", "https://test.supabase.co"), \
         patch("videomerge.temporal.activities.SUPABASE_ANON_KEY", "anon-key"), \
         patch("httpx.AsyncClient", return_value=mock_client):

        result = await fetch_brand_image_params("unknown-client")

    assert result == {"recraft_style_id": None, "negative_prompt_terms": []}


@pytest.mark.asyncio
async def test_returns_empty_params_when_supabase_not_configured():
    """Returns safe empty result without crashing when SUPABASE_URL is not set."""
    from videomerge.temporal.activities import fetch_brand_image_params

    with patch("videomerge.temporal.activities.SUPABASE_URL", None), \
         patch("videomerge.temporal.activities.SUPABASE_ANON_KEY", None):

        result = await fetch_brand_image_params("client-42")

    assert result == {"recraft_style_id": None, "negative_prompt_terms": []}


@pytest.mark.asyncio
async def test_returns_empty_params_on_supabase_error():
    """Returns safe empty result when the Supabase HTTP call fails."""
    from videomerge.temporal.activities import fetch_brand_image_params

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=Exception("connection refused"))

    with patch("videomerge.temporal.activities.SUPABASE_URL", "https://test.supabase.co"), \
         patch("videomerge.temporal.activities.SUPABASE_ANON_KEY", "anon-key"), \
         patch("httpx.AsyncClient", return_value=mock_client):

        result = await fetch_brand_image_params("client-42")

    assert result == {"recraft_style_id": None, "negative_prompt_terms": []}


@pytest.mark.asyncio
async def test_uses_user_jwt_in_auth_header_when_provided():
    """When user_access_token is given it is used as the Bearer token."""
    from videomerge.temporal.activities import fetch_brand_image_params

    captured_headers = {}

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = [{"recraft_style_id": "s1", "negative_prompt_terms": []}]

    async def mock_get(url, headers=None, **kwargs):
        captured_headers.update(headers or {})
        return mock_response

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = mock_get

    with patch("videomerge.temporal.activities.SUPABASE_URL", "https://test.supabase.co"), \
         patch("videomerge.temporal.activities.SUPABASE_ANON_KEY", "anon-key"), \
         patch("httpx.AsyncClient", return_value=mock_client):

        await fetch_brand_image_params("client-42", user_access_token="user-jwt-token")

    assert captured_headers.get("Authorization") == "Bearer user-jwt-token"
    assert captured_headers.get("apikey") == "anon-key"


@pytest.mark.asyncio
async def test_falls_back_to_anon_key_when_no_jwt():
    """When user_access_token is absent, anon key is used as the Bearer token."""
    from videomerge.temporal.activities import fetch_brand_image_params

    captured_headers = {}

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = [{"recraft_style_id": None, "negative_prompt_terms": []}]

    async def mock_get(url, headers=None, **kwargs):
        captured_headers.update(headers or {})
        return mock_response

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = mock_get

    with patch("videomerge.temporal.activities.SUPABASE_URL", "https://test.supabase.co"), \
         patch("videomerge.temporal.activities.SUPABASE_ANON_KEY", "anon-key"), \
         patch("httpx.AsyncClient", return_value=mock_client):

        await fetch_brand_image_params("client-42")

    assert captured_headers.get("Authorization") == "Bearer anon-key"


# ---------------------------------------------------------------------------
# build_negative_prompt — extra_terms integration
# ---------------------------------------------------------------------------

def test_build_negative_prompt_includes_brand_terms():
    """build_negative_prompt merges default terms with brand-specific extra_terms."""
    from videomerge.services.brand_prompt import build_negative_prompt

    result = build_negative_prompt(extra_terms=["competitor logo", "wrong colors"])

    assert "competitor logo" in result
    assert "wrong colors" in result
    # Default terms still present
    assert "blurry" in result


def test_build_negative_prompt_no_duplicates():
    """Extra terms that overlap with defaults are deduplicated."""
    from videomerge.services.brand_prompt import build_negative_prompt

    result = build_negative_prompt(extra_terms=["blurry", "custom term"])
    terms = [t.strip() for t in result.split(",")]

    assert terms.count("blurry") == 1
    assert "custom term" in result


def test_build_negative_prompt_empty_extra_terms():
    """Passing an empty list for extra_terms returns only default terms."""
    from videomerge.services.brand_prompt import build_negative_prompt

    result_default = build_negative_prompt()
    result_empty = build_negative_prompt(extra_terms=[])

    assert result_default == result_empty
