"""MCP Server tests for OnlyPans.

Tests the MCP conversion endpoint and helper functions.
MCP server runs on the host at port 8001 (SSE) / 8002 (HTTP).
"""

import sys
import os
import pytest
import requests

pytestmark = pytest.mark.mcp

# Add project root to path so we can import mcp_server functions directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════════════════════════
# URL Normalization (via direct import)
# ═══════════════════════════════════════════════════════════════════════════════


class TestNormalizeUrlDirect:
    """Test _normalize_url by importing from mcp_server directly."""

    @pytest.fixture(autouse=True)
    def _import_function(self):
        """Import the function, skip if mcp_server can't be imported."""
        try:
            from mcp_server import _normalize_url
            self.normalize = _normalize_url
        except ImportError:
            pytest.skip("Cannot import mcp_server (run from project root)")

    def test_instagram_strips_igsh(self):
        """Instagram URL with ?igsh= param is stripped to clean path."""
        url = "https://www.instagram.com/reel/ABC123/?igsh=somehash"
        result = self.normalize(url)
        assert "igsh" not in result
        assert "/reel/ABC123/" in result

    def test_instagram_strips_utm(self):
        """Instagram URL with utm params is stripped."""
        url = "https://www.instagram.com/reel/XYZ789/?utm_source=ig_web&utm_medium=copy_link"
        result = self.normalize(url)
        assert "utm" not in result
        assert "/reel/XYZ789/" in result

    def test_tiktok_strips_params(self):
        """TikTok URL with is_from_webapp param is stripped."""
        url = "https://www.tiktok.com/@user/video/1234567890?is_from_webapp=1&sender_device=pc"
        result = self.normalize(url)
        assert "is_from_webapp" not in result
        assert "/video/1234567890/" in result

    def test_preserves_non_social_urls(self):
        """Non-social URLs are returned unchanged."""
        url = "https://www.allrecipes.com/recipe/10813/best-chocolate-chip-cookies/"
        result = self.normalize(url)
        assert result == url

    def test_trailing_slash_normalization(self):
        """Instagram/TikTok paths get normalized trailing slash."""
        url = "https://www.instagram.com/reel/ABC123"
        result = self.normalize(url)
        assert result.endswith("/"), f"Should end with /: {result}"

    def test_case_insensitive_domain(self):
        """Domain matching is case-insensitive."""
        url = "https://WWW.INSTAGRAM.COM/reel/ABC123/?igsh=test"
        result = self.normalize(url)
        assert "igsh" not in result


# ═══════════════════════════════════════════════════════════════════════════════
# Blog Detection (via direct import)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBlogDetection:
    """Test is_blog_url by importing from mcp_server."""

    @pytest.fixture(autouse=True)
    def _import_function(self):
        try:
            from mcp_server import is_blog_url
            self.is_blog = is_blog_url
        except ImportError:
            pytest.skip("Cannot import mcp_server (run from project root)")

    def test_recipe_blog_detected(self):
        """Recipe blog URLs are identified as blogs."""
        assert self.is_blog("https://www.allrecipes.com/recipe/10813/cookies/")
        assert self.is_blog("https://minimalistbaker.com/best-vegan-brownies/")
        assert self.is_blog("https://www.seriouseats.com/best-pizza-dough")

    def test_instagram_not_blog(self):
        """Instagram URLs are NOT blogs."""
        assert not self.is_blog("https://www.instagram.com/reel/ABC123/")

    def test_tiktok_not_blog(self):
        """TikTok URLs are NOT blogs."""
        assert not self.is_blog("https://www.tiktok.com/@user/video/123456")

    def test_non_http_not_blog(self):
        """Non-HTTP URLs are not blogs."""
        assert not self.is_blog("ftp://files.example.com/recipe.pdf")
        assert not self.is_blog("not-a-url-at-all")


# ═══════════════════════════════════════════════════════════════════════════════
# Duplicate Detection (via direct import, needs running web app)
# ═══════════════════════════════════════════════════════════════════════════════


class TestDuplicateDetection:
    """Test _check_duplicate against the running test web app.

    NOTE: _check_duplicate uses RECIPE_GLASS_URL env var (defaults to localhost:5100).
    We override it to point at the test container (port 5101).
    """

    @pytest.fixture(autouse=True)
    def _import_function(self, monkeypatch):
        try:
            import mcp_server
            # Point duplicate check at test container
            monkeypatch.setattr(mcp_server, "RECIPE_GLASS_URL", "http://localhost:5101")
            self.check_dup = mcp_server._check_duplicate
        except ImportError:
            pytest.skip("Cannot import mcp_server (run from project root)")

    def test_new_url_returns_none(self):
        """A URL not in the DB returns None."""
        result = self.check_dup("https://example.com/never-seen-before-url-12345")
        assert result is None, f"Expected None for new URL, got {result}"

    def test_existing_url_returns_recipe(self):
        """A URL already in the DB returns the existing recipe."""
        # This URL is in our seeded test DB
        result = self.check_dup("https://example.com/carbonara")
        assert result is not None, "Should find existing carbonara recipe"
        assert "Carbonara" in result.get("title", ""), f"Unexpected result: {result}"


# ═══════════════════════════════════════════════════════════════════════════════
# Convert Endpoint (HTTP at port 8002)
# ═══════════════════════════════════════════════════════════════════════════════


class TestConvertEndpoint:
    """Test the MCP /convert HTTP endpoint."""

    def test_convert_endpoint_reachable(self, mcp_url):
        """MCP server /convert endpoint is reachable.

        NOTE: Uses a clearly fake URL to avoid accidentally creating real recipes
        on production. The test only verifies the endpoint accepts requests and
        returns a response (any status) — it does NOT need a real convertible URL.
        A 500 with a JSON error body is fine — it means the server processed the
        request but the URL wasn't convertible. A ConnectionError means it's down.
        """
        try:
            resp = requests.post(
                f"{mcp_url}/convert",
                json={"url": "https://example.com/test-endpoint-reachability-check"},
                timeout=60,
            )
            # Any response means the server is up and processing requests.
            # 4xx/5xx from a fake URL is expected — we only fail on no response.
            assert resp.status_code is not None, "Got a response from MCP server"
        except requests.ConnectionError:
            pytest.skip("MCP server not running on port 8002")

    def test_convert_endpoint_missing_url(self, mcp_url):
        """MCP /convert with missing URL returns error."""
        try:
            resp = requests.post(f"{mcp_url}/convert", json={}, timeout=10)
            assert resp.status_code >= 400, f"Expected error status, got {resp.status_code}"
        except requests.ConnectionError:
            pytest.skip("MCP server not running on port 8002")


# ═══════════════════════════════════════════════════════════════════════════════
# Search Recipes (direct function call)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSearchRecipes:
    """Test search_recipes MCP tool function.

    NOTE: search_recipes returns human-readable formatted text, not JSON.
    We override RECIPE_GLASS_URL to point at the test container.
    """

    @pytest.fixture(autouse=True)
    def _import_function(self, monkeypatch):
        try:
            import mcp_server
            monkeypatch.setattr(mcp_server, "RECIPE_GLASS_URL", "http://localhost:5101")
            self.search = mcp_server.search_recipes
        except ImportError:
            pytest.skip("Cannot import mcp_server (run from project root)")

    def test_search_returns_results(self):
        """search_recipes with a query returns formatted text with matches."""
        result = self.search(query="carbonara")
        assert isinstance(result, str), f"Expected string, got {type(result)}"
        assert "carbonara" in result.lower(), f"Expected 'carbonara' in result: {result[:200]}"
        assert "Found" in result or "#" in result, f"Expected formatted output: {result[:200]}"

    def test_search_by_category(self):
        """search_recipes with a category filter returns matching recipes."""
        result = self.search(category="italian")
        assert isinstance(result, str), f"Expected string, got {type(result)}"
        assert "Found" in result or "#" in result or "No recipes" in result
