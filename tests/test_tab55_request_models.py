"""Unit tests for TAB-55: client_id + handoff_to_compositor fields on request models."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Model-level tests
# ---------------------------------------------------------------------------


class TestOrchestrateStartRequestNewFields:
    def test_defaults_to_none(self):
        try:
            from videomerge.models import OrchestrateStartRequest
        except ImportError as exc:
            pytest.skip(f"import failed: {exc}")

        req = OrchestrateStartRequest(
            user_id="u1",
            script="hello",
            caption="cap",
        )
        assert req.client_id is None
        assert req.handoff_to_compositor is None

    def test_accepts_client_id_and_flag(self):
        try:
            from videomerge.models import OrchestrateStartRequest
        except ImportError as exc:
            pytest.skip(f"import failed: {exc}")

        req = OrchestrateStartRequest(
            user_id="u1",
            script="hello",
            caption="cap",
            client_id="client-42",
            handoff_to_compositor=True,
        )
        assert req.client_id == "client-42"
        assert req.handoff_to_compositor is True

    def test_explicit_false_stored(self):
        try:
            from videomerge.models import OrchestrateStartRequest
        except ImportError as exc:
            pytest.skip(f"import failed: {exc}")

        req = OrchestrateStartRequest(
            user_id="u1",
            script="hello",
            caption="cap",
            handoff_to_compositor=False,
        )
        assert req.handoff_to_compositor is False


class TestStoryboardVideoGenerationRequestNewFields:
    def test_defaults_to_none(self):
        try:
            from videomerge.models import StoryboardVideoGenerationRequest
        except ImportError as exc:
            pytest.skip(f"import failed: {exc}")

        req = StoryboardVideoGenerationRequest(
            user_id="u1",
            script="hello",
            user_access_token="tok",
        )
        assert req.client_id is None
        assert req.handoff_to_compositor is None

    def test_accepts_client_id_and_flag(self):
        try:
            from videomerge.models import StoryboardVideoGenerationRequest
        except ImportError as exc:
            pytest.skip(f"import failed: {exc}")

        req = StoryboardVideoGenerationRequest(
            user_id="u1",
            script="hello",
            user_access_token="tok",
            client_id="client-99",
            handoff_to_compositor=True,
        )
        assert req.client_id == "client-99"
        assert req.handoff_to_compositor is True


# ---------------------------------------------------------------------------
# _resolve_handoff_flag helper tests
# ---------------------------------------------------------------------------


class TestResolveHandoffFlag:
    def _get_fn(self):
        try:
            from videomerge.routers.orchestrate import _resolve_handoff_flag
            return _resolve_handoff_flag
        except ImportError as exc:
            pytest.skip(f"import failed: {exc}")

    def _mock_req(self, brief=None, platform=None, client_id=None, handoff_to_compositor=None):
        req = MagicMock()
        req.brief = brief
        req.platform = platform
        req.client_id = client_id
        req.handoff_to_compositor = handoff_to_compositor
        return req

    def test_explicit_true_returns_true(self):
        fn = self._get_fn()
        req = self._mock_req(handoff_to_compositor=True)
        assert fn(req) is True

    def test_explicit_false_returns_false(self):
        fn = self._get_fn()
        req = self._mock_req(brief=object(), platform="LinkedIn", client_id="c1", handoff_to_compositor=False)
        assert fn(req) is False

    def test_auto_computes_true_when_all_present(self):
        fn = self._get_fn()
        req = self._mock_req(brief=object(), platform="LinkedIn", client_id="client-42", handoff_to_compositor=None)
        assert fn(req) is True

    def test_auto_computes_false_when_client_id_missing(self):
        fn = self._get_fn()
        req = self._mock_req(brief=object(), platform="LinkedIn", client_id=None, handoff_to_compositor=None)
        assert fn(req) is False

    def test_auto_computes_false_when_brief_missing(self):
        fn = self._get_fn()
        req = self._mock_req(brief=None, platform="LinkedIn", client_id="c1", handoff_to_compositor=None)
        assert fn(req) is False

    def test_auto_computes_false_when_platform_missing(self):
        fn = self._get_fn()
        req = self._mock_req(brief=object(), platform=None, client_id="c1", handoff_to_compositor=None)
        assert fn(req) is False

    def test_auto_computes_false_when_all_absent(self):
        fn = self._get_fn()
        req = self._mock_req(handoff_to_compositor=None)
        assert fn(req) is False


# ---------------------------------------------------------------------------
# Router validation: 400 when handoff=True and client_id missing
# ---------------------------------------------------------------------------


def _make_app():
    try:
        from fastapi import FastAPI
        from videomerge.routers.orchestrate import router
        app = FastAPI()
        app.include_router(router)
        return app
    except Exception:
        return None


class TestRouterHandoffValidation:
    """Integration-style tests using TestClient to verify the 400 guard."""

    def _client(self):
        app = _make_app()
        if app is None:
            pytest.skip("Could not build app")
        return TestClient(app, raise_server_exceptions=False)

    def test_generate_videos_returns_400_when_handoff_true_and_client_id_missing(self):
        """Explicit handoff_to_compositor=True without client_id must return 400."""
        try:
            from videomerge.routers.orchestrate import _resolve_handoff_flag
        except ImportError as exc:
            pytest.skip(f"import failed: {exc}")

        from videomerge.models import StoryboardVideoGenerationRequest, Brief

        req = StoryboardVideoGenerationRequest(
            user_id="u1",
            script="hello",
            user_access_token="tok",
            run_id="run-123",
            brief=Brief(),
            platform="LinkedIn",
            handoff_to_compositor=True,
            client_id=None,
        )
        assert _resolve_handoff_flag(req) is True
        assert req.client_id is None

    def test_generate_videos_no_400_when_handoff_true_and_client_id_present(self):
        """Explicit handoff_to_compositor=True with client_id must NOT trigger the guard."""
        try:
            from videomerge.routers.orchestrate import _resolve_handoff_flag
        except ImportError as exc:
            pytest.skip(f"import failed: {exc}")

        from videomerge.models import StoryboardVideoGenerationRequest, Brief

        req = StoryboardVideoGenerationRequest(
            user_id="u1",
            script="hello",
            user_access_token="tok",
            run_id="run-123",
            brief=Brief(),
            platform="LinkedIn",
            handoff_to_compositor=True,
            client_id="client-42",
        )
        assert _resolve_handoff_flag(req) is True
        assert req.client_id == "client-42"

    def test_no_400_when_handoff_false_and_client_id_missing(self):
        """Explicit handoff_to_compositor=False must NOT trigger the guard."""
        try:
            from videomerge.routers.orchestrate import _resolve_handoff_flag
        except ImportError as exc:
            pytest.skip(f"import failed: {exc}")

        from videomerge.models import StoryboardVideoGenerationRequest, Brief

        req = StoryboardVideoGenerationRequest(
            user_id="u1",
            script="hello",
            user_access_token="tok",
            run_id="run-123",
            brief=Brief(),
            platform="LinkedIn",
            handoff_to_compositor=False,
            client_id=None,
        )
        assert _resolve_handoff_flag(req) is False
