"""Unit checks for the HTTP/1.1 WebSocket Upgrade header layout."""

from cycronet._websocket import _normalise_headers


def test_chrome_upgrade_header_layout() -> None:
    headers, origin = _normalise_headers(
        [
            ("pragma", "no-cache"),
            ("cache-control", "no-cache"),
            ("user-agent", "Mozilla/5.0"),
            ("accept-encoding", "gzip, deflate, br, zstd"),
            ("accept-language", "zh-CN,zh;q=0.9"),
            ("cookie", "sessionKey=example"),
        ],
        "https://claude.ai",
    )

    assert origin == "https://claude.ai"
    assert headers == [
        ("Pragma", "no-cache"),
        ("Cache-Control", "no-cache"),
        ("User-Agent", "Mozilla/5.0"),
        ("Upgrade", "websocket"),
        ("Origin", "https://claude.ai"),
        ("Sec-WebSocket-Version", "13"),
        ("Accept-Encoding", "gzip, deflate, br, zstd"),
        ("Accept-Language", "zh-CN,zh;q=0.9"),
        ("Cookie", "sessionKey=example"),
    ]


def test_origin_header_keeps_its_browser_position() -> None:
    headers, origin = _normalise_headers(
        [("Origin", "https://claude.ai"), ("Cookie", "a=b")],
        None,
    )

    assert origin == "https://claude.ai"
    assert headers[0:4] == [
        ("Upgrade", "websocket"),
        ("Origin", "https://claude.ai"),
        ("Sec-WebSocket-Version", "13"),
        ("Cookie", "a=b"),
    ]


if __name__ == "__main__":
    test_chrome_upgrade_header_layout()
    test_origin_header_keeps_its_browser_position()
    print("WebSocket header-order checks passed")
