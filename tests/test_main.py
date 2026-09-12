import pytest

import main


@pytest.fixture(autouse=True)
def reset_mode():
    main.MODE = main.OFF
    yield
    main.MODE = main.OFF


def test_pattern_strs_align_with_mode_constants():
    assert main.PATTERN_STRS[main.OFF] == "off"
    assert main.PATTERN_STRS[main.CLOCK] == "clock"
    assert main.PATTERN_STRS[main.FLOWER] == "flower"
    assert len(main.PATTERN_STRS) == main.MAX_MODE + 1


# --- parse_http_request -----------------------------------------------------


def test_parse_get_request():
    req = main.parse_http_request(b"GET / HTTP/1.1\r\nHost: lotus\r\n\r\n")
    assert req["method"] == "GET"
    assert req["path"] == "/"
    assert req["http_version"] == "HTTP/1.1"
    assert req["headers"] == {"Host": "lotus"}
    assert req["body"] == ""


def test_parse_post_with_json_body():
    raw = (
        b"POST / HTTP/1.1\r\n"
        b"Host: lotus\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: 21\r\n"
        b"\r\n"
        b'{"pattern": "flower"}'
    )
    req = main.parse_http_request(raw)
    assert req["method"] == "POST"
    assert req["headers"]["Content-Type"] == "application/json"
    assert req["body"] == '{"pattern": "flower"}'


def test_parse_path_pattern():
    req = main.parse_http_request(b"POST /sweep HTTP/1.1\r\n\r\n")
    assert req["path"] == "/sweep"


def test_parse_query_string_is_split_off_path():
    req = main.parse_http_request(b"GET /x?a=1&b=two&flag HTTP/1.1\r\n\r\n")
    assert req["path"] == "/x"
    assert req["query"] == {"a": "1", "b": "two", "flag": ""}


def test_header_values_may_contain_colons():
    req = main.parse_http_request(b"GET / HTTP/1.1\r\nHost: 10.0.0.5:80\r\n\r\n")
    assert req["headers"]["Host"] == "10.0.0.5:80"


# --- match_pattern ----------------------------------------------------------


@pytest.mark.parametrize("name", main.PATTERN_STRS)
def test_match_pattern_sets_mode_for_every_known_name(name):
    main.MODE = main.WIFI
    assert main.match_pattern(name) is True
    assert main.PATTERN_STRS[main.MODE] == name


def test_match_pattern_off_from_any_mode():
    main.MODE = main.FLOWER
    assert main.match_pattern("off") is True
    assert main.MODE == main.OFF


def test_match_pattern_rejects_unknown():
    main.MODE = main.SWEEP
    assert main.match_pattern("disco") is False
    assert main.MODE == main.SWEEP


def test_match_pattern_any_picks_a_different_animated_pattern():
    for start in range(main.RANDOM, main.MAX_MODE + 1):
        for _ in range(20):
            main.MODE = start
            assert main.match_pattern("any") is True
            assert main.MODE != start
            assert main.RANDOM <= main.MODE <= main.MAX_MODE


# --- current_pattern --------------------------------------------------------


def test_current_pattern_reports_connecting_while_wifi_down():
    main.MODE = main.WIFI
    assert main.current_pattern() == "connecting"


@pytest.mark.parametrize("mode", range(main.OFF, main.MAX_MODE + 1))
def test_current_pattern_names_every_mode(mode):
    main.MODE = mode
    assert main.current_pattern() == main.PATTERN_STRS[mode]
