from __future__ import annotations

from typing import Any

import pytest
import yaml

from elva_cli.core.api.http import HttpError
from elva_cli.core.spec import fetch as fetch_mod
from elva_cli.core.spec.fetch import SpecFetchError, fetch_spec
from elva_cli.core.spec.normalize import to_yaml

BASE_URL = "https://api.getelva.ai"
URL = "https://x.dev/openapi.json"


def _send(monkeypatch: pytest.MonkeyPatch, result: Any) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake(url: str, **kwargs: Any) -> Any:
        seen.update(kwargs, url=url)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(fetch_mod, "send_json", fake)
    return seen


class TestFetchSpec:
    def test_it_posts_the_url_to_the_proxy_without_a_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen = _send(monkeypatch, {"content": "openapi: 3.0.3\n"})
        assert fetch_spec(base_url=BASE_URL, url=URL, timeout=5) == b"openapi: 3.0.3\n"
        assert seen["url"] == f"{BASE_URL}/api/fetch-file"
        assert seen["payload"] == {"url": URL}
        assert seen["token"] is None

    def test_an_upstream_404_names_the_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _send(monkeypatch, HttpError(404, "Failed to fetch file: Not Found"))
        with pytest.raises(SpecFetchError, match=r"could not fetch https://x\.dev"):
            fetch_spec(base_url=BASE_URL, url=URL, timeout=5)

    def test_too_large_names_the_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _send(monkeypatch, HttpError(413, None))
        with pytest.raises(SpecFetchError, match="10 MB"):
            fetch_spec(base_url=BASE_URL, url=URL, timeout=5)

    @pytest.mark.parametrize("status", [502, 504])
    def test_an_upstream_failure_says_unreachable(
        self, monkeypatch: pytest.MonkeyPatch, status: int
    ) -> None:
        _send(monkeypatch, HttpError(status, "Spec URL returned 500"))
        with pytest.raises(SpecFetchError, match="could not be reached: Spec URL returned 500"):
            fetch_spec(base_url=BASE_URL, url=URL, timeout=5)

    def test_a_refusal_carries_the_servers_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _send(monkeypatch, HttpError(422, "blocked private address"))
        with pytest.raises(SpecFetchError, match=r"could not fetch .*: blocked private address"):
            fetch_spec(base_url=BASE_URL, url=URL, timeout=5)

    def test_a_response_without_content_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _send(monkeypatch, {"fileSize": 10})
        with pytest.raises(SpecFetchError, match="unexpected response"):
            fetch_spec(base_url=BASE_URL, url=URL, timeout=5)


class TestToYaml:
    def test_a_json_object_becomes_yaml(self) -> None:
        out = to_yaml(b'{"openapi": "3.0.3", "paths": {}}')
        assert out.lstrip()[:1] not in (b"{", b"[")
        assert yaml.safe_load(out) == {"openapi": "3.0.3", "paths": {}}

    def test_key_order_is_preserved(self) -> None:
        out = to_yaml(b'{"z": 1, "a": 2, "m": 3}').decode()
        assert out.index("z:") < out.index("a:") < out.index("m:")

    def test_unicode_is_kept_readable(self) -> None:
        out = to_yaml('{"title": "Café"}'.encode())
        assert "Café" in out.decode()

    def test_a_repeated_subtree_does_not_become_an_anchor(self) -> None:
        shared = '{"x": {"a": 1}, "y": {"a": 1}}'
        out = to_yaml(shared.encode()).decode()
        assert "&id" not in out
        assert "*id" not in out

    def test_yaml_input_is_left_alone(self) -> None:
        original = b"openapi: 3.0.3  # keep this comment\npaths: {}\n"
        assert to_yaml(original) == original

    def test_a_json_array_is_left_alone(self) -> None:
        assert to_yaml(b"[1, 2, 3]") == b"[1, 2, 3]"

    def test_unparseable_bytes_are_left_alone(self) -> None:
        assert to_yaml(b"not a spec at all") == b"not a spec at all"
