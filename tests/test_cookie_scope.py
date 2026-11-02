from core.cookie_scope import (
    DEFAULT_COOKIE_DOMAINS,
    COOKIE_SCOPE_KNOWN,
    COOKIE_SCOPE_ALL,
    is_cookie_eligible,
    resolve_cookies_for_request,
)


def test_is_cookie_eligible_known_domains():
    assert is_cookie_eligible("https://www.youtube.com/watch?v=123") is True
    assert is_cookie_eligible("https://youtu.be/123") is True
    assert is_cookie_eligible("https://music.youtube.com/watch?v=123") is True
    assert is_cookie_eligible("https://www.tiktok.com/@user/video/123") is True
    assert is_cookie_eligible("https://vm.tiktok.com/123") is True
    assert is_cookie_eligible("https://www.instagram.com/reel/123") is True
    assert is_cookie_eligible("https://twitter.com/user/status/123") is True
    assert is_cookie_eligible("https://x.com/user/status/123") is True


def test_is_cookie_eligible_untrusted_or_adult_domains():
    assert is_cookie_eligible("https://www.pornhub.com/view_video.php?viewkey=123") is False
    assert is_cookie_eligible("https://vimeo.com/123456") is False
    assert is_cookie_eligible("https://example.com/video.mp4") is False
    assert is_cookie_eligible("https://twitch.tv/videos/123") is False


def test_is_cookie_eligible_scope_all():
    assert is_cookie_eligible("https://www.pornhub.com/view_video.php?viewkey=123", scope_mode="all") is True
    assert is_cookie_eligible("https://vimeo.com/123456", scope_mode=COOKIE_SCOPE_ALL) is True
    assert is_cookie_eligible("https://example.com/video.mp4", scope_mode="all") is True


def test_is_cookie_eligible_invalid_inputs():
    assert is_cookie_eligible("") is False
    assert is_cookie_eligible(None) is False
    assert is_cookie_eligible("not a url at all") is False


def test_resolve_cookies_for_request():
    # When browser is None or empty
    assert resolve_cookies_for_request("https://youtube.com/watch?v=123", None) is None
    assert resolve_cookies_for_request("https://youtube.com/watch?v=123", "None") is None
    assert resolve_cookies_for_request("https://youtube.com/watch?v=123", "disabled") is None

    # Known domain, valid browser -> returned
    assert resolve_cookies_for_request("https://youtube.com/watch?v=123", "firefox") == "firefox"
    assert resolve_cookies_for_request("https://x.com/status/123", "Chrome") == "chrome"

    # Untrusted domain, valid browser -> None under known_only
    assert resolve_cookies_for_request("https://pornhub.com/view", "firefox") is None
    assert resolve_cookies_for_request("https://vimeo.com/123", "firefox") is None

    # Untrusted domain under scope "all" -> returned
    assert resolve_cookies_for_request("https://pornhub.com/view", "firefox", scope_mode="all") == "firefox"

    # Explicit toggle overrides
    # If user explicitly disabled cookies on YouTube, returns None
    assert resolve_cookies_for_request("https://youtube.com/watch?v=123", "firefox", explicit_enabled=False) is None
    # If user explicitly enabled cookies on Pornhub/Vimeo, returns browser
    assert resolve_cookies_for_request("https://pornhub.com/view", "firefox", explicit_enabled=True) == "firefox"
