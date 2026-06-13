"""Pure unit tests for URL normalization logic.

No network access needed — tests the _normalize_url function directly.
These can run without any containers or servers.
"""

import sys
import os

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from mcp_server import _normalize_url
except ImportError:
    pytestmark = pytest.mark.skip("Cannot import mcp_server — run from project root")
    _normalize_url = None


@pytest.fixture
def normalize():
    """Provide the normalize function."""
    if _normalize_url is None:
        pytest.skip("Cannot import _normalize_url")
    return _normalize_url


class TestInstagramNormalization:
    """Instagram URL normalization."""

    def test_strip_igsh_param(self, normalize):
        """Strips ?igsh= tracking parameter from Instagram URLs."""
        url = "https://www.instagram.com/reel/C8xK2pNOabc/?igsh=MWUxcjN2OTRqamlvdQ=="
        result = normalize(url)
        assert "igsh" not in result
        assert "instagram.com" in result
        assert "/reel/C8xK2pNOabc/" in result

    def test_strip_utm_params(self, normalize):
        """Strips utm_source, utm_medium, etc. from Instagram URLs."""
        url = "https://www.instagram.com/reel/DAB123/?utm_source=ig_web_copy_link&utm_medium=share"
        result = normalize(url)
        assert "utm_source" not in result
        assert "utm_medium" not in result
        assert "/reel/DAB123/" in result

    def test_strip_multiple_params(self, normalize):
        """Strips all query parameters from Instagram URLs."""
        url = "https://www.instagram.com/p/CxYz123/?igsh=abc&utm_source=copy&foo=bar"
        result = normalize(url)
        assert "?" not in result
        assert "/p/CxYz123/" in result

    def test_post_url(self, normalize):
        """Handles Instagram /p/ post URLs."""
        url = "https://www.instagram.com/p/CxPost123/?igsh=test"
        result = normalize(url)
        assert "/p/CxPost123/" in result
        assert "igsh" not in result


class TestTikTokNormalization:
    """TikTok URL normalization."""

    def test_strip_is_from_webapp(self, normalize):
        """Strips is_from_webapp param from TikTok URLs."""
        url = "https://www.tiktok.com/@chef/video/7234567890123456789?is_from_webapp=1&sender_device=pc"
        result = normalize(url)
        assert "is_from_webapp" not in result
        assert "sender_device" not in result
        assert "/video/7234567890123456789/" in result

    def test_strip_all_tiktok_params(self, normalize):
        """All query parameters are stripped from TikTok URLs."""
        url = "https://www.tiktok.com/@user/video/123?lang=en&q=recipe&t=1234"
        result = normalize(url)
        assert "?" not in result
        assert "/video/123/" in result

    def test_vm_tiktok_domain(self, normalize):
        """Handles vm.tiktok.com short URLs (has tiktok.com in domain)."""
        # Note: vm.tiktok.com contains "tiktok.com" so should be caught
        url = "https://vm.tiktok.com/ZMrABC123/"
        result = normalize(url)
        # Should strip params if any, keep path with trailing slash
        assert result.endswith("/")


class TestWwwPrefix:
    """www. prefix handling."""

    def test_instagram_with_www(self, normalize):
        """www.instagram.com is handled correctly."""
        url = "https://www.instagram.com/reel/TEST123/?igsh=abc"
        result = normalize(url)
        assert "igsh" not in result

    def test_instagram_without_www(self, normalize):
        """instagram.com (no www) is handled correctly."""
        url = "https://instagram.com/reel/TEST123/?igsh=abc"
        result = normalize(url)
        assert "igsh" not in result

    def test_tiktok_with_www(self, normalize):
        """www.tiktok.com is handled correctly."""
        url = "https://www.tiktok.com/@user/video/999?is_from_webapp=1"
        result = normalize(url)
        assert "is_from_webapp" not in result


class TestUppercaseDomains:
    """Case-insensitive domain matching."""

    def test_uppercase_instagram(self, normalize):
        """INSTAGRAM.COM (uppercase) is still recognized."""
        url = "https://WWW.INSTAGRAM.COM/reel/UPPER123/?igsh=test"
        result = normalize(url)
        assert "igsh" not in result

    def test_mixed_case_tiktok(self, normalize):
        """Mixed case TikTok domain is recognized."""
        url = "https://Www.TikTok.Com/@user/video/456?param=val"
        result = normalize(url)
        assert "param" not in result


class TestTrailingSlash:
    """Trailing slash normalization."""

    def test_adds_trailing_slash(self, normalize):
        """Instagram/TikTok URLs without trailing slash get one added."""
        url = "https://www.instagram.com/reel/NOSLASH"
        result = normalize(url)
        assert result.endswith("/"), f"Expected trailing slash: {result}"

    def test_no_double_trailing_slash(self, normalize):
        """URLs already with trailing slash don't get doubled."""
        url = "https://www.instagram.com/reel/HASSLASH/"
        result = normalize(url)
        assert not result.endswith("//"), f"Double trailing slash: {result}"

    def test_double_slash_in_input(self, normalize):
        """Input with double trailing slash is normalized to single."""
        url = "https://www.instagram.com/reel/DOUBLE//"
        result = normalize(url)
        # rstrip("/") + "/" should give single slash
        assert result.endswith("/")
        assert not result.endswith("//")


class TestNonSocialUrls:
    """Non-social media URLs should pass through unchanged."""

    def test_allrecipes_unchanged(self, normalize):
        """allrecipes.com URLs pass through unchanged."""
        url = "https://www.allrecipes.com/recipe/10813/best-chocolate-chip-cookies/"
        result = normalize(url)
        assert result == url

    def test_blog_with_params_unchanged(self, normalize):
        """Blog URLs with query params are NOT stripped (only social media is)."""
        url = "https://www.seriouseats.com/recipe?print=true&scale=2"
        result = normalize(url)
        assert result == url

    def test_youtube_unchanged(self, normalize):
        """YouTube URLs pass through unchanged (not Instagram/TikTok)."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        result = normalize(url)
        assert result == url

    def test_plain_domain_unchanged(self, normalize):
        """Plain domain URLs pass through."""
        url = "https://example.com/my-recipe"
        result = normalize(url)
        assert result == url
