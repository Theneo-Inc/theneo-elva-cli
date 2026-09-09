from __future__ import annotations

import pytest

from elva_cli.core.spec.detect import SpecFormat, detect_format, read_meta

OPENAPI_YAML = b"""openapi: 3.0.3
info:
  title: Payments
  version: "1.0"
paths: {}
"""

OPENAPI_JSON = b'{"openapi": "3.0.3", "info": {"title": "Payments"}, "paths": {}}'

SWAGGER_JSON = b'{"swagger": "2.0", "info": {"title": "Legacy"}}'

POSTMAN = b"""{
  "info": {
    "_postman_id": "0c1f0d3e-1111-2222-3333-444455556666",
    "name": "Payments",
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
  },
  "item": []
}"""


class TestDetectFormat:
    @pytest.mark.parametrize(
        "data",
        [
            pytest.param(OPENAPI_YAML, id="yaml"),
            pytest.param(OPENAPI_JSON, id="json"),
            pytest.param(SWAGGER_JSON, id="swagger-2.0"),
        ],
    )
    def test_openapi_is_recognised(self, data: bytes) -> None:
        assert detect_format(data) is SpecFormat.OPENAPI

    def test_postman_is_recognised(self) -> None:
        assert detect_format(POSTMAN) is SpecFormat.POSTMAN

    def test_a_postman_collection_mentioning_swagger_is_still_postman(self) -> None:
        """The reason Postman is checked first: a collection may well have a
        request named "swagger" or a description referring to one."""
        data = b"""{
          "info": {
            "_postman_id": "abc",
            "name": "swagger: legacy endpoints",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
          }
        }"""
        assert detect_format(data) is SpecFormat.POSTMAN

    @pytest.mark.parametrize(
        "data",
        [
            pytest.param(b"", id="empty"),
            pytest.param(b"just some prose", id="prose"),
            pytest.param(b'{"info": {"title": "no version marker"}}', id="json-without-marker"),
            pytest.param(b"# openapi is mentioned but not as a key", id="mention-only"),
        ],
    )
    def test_anything_else_is_undetectable(self, data: bytes) -> None:
        assert detect_format(data) is None

    def test_a_marker_past_the_sniff_window_is_not_found(self) -> None:
        """Documented behaviour, not an accident: detection reads a bounded
        head so a large spec is not scanned twice. --format is the way out."""
        data = b"#" * 9000 + b"\nopenapi: 3.0.3\n"
        assert detect_format(data) is None

    def test_leading_whitespace_and_braces_do_not_hide_the_marker(self) -> None:
        assert detect_format(b'\n\n  {\n  "openapi": "3.1.0"\n}') is SpecFormat.OPENAPI


def test_format_values_are_the_flag_values() -> None:
    """--format takes these strings, so they are a user-facing contract."""
    assert [fmt.value for fmt in SpecFormat] == ["openapi", "postman"]


class TestReadMeta:
    """--name defaults to info.title, and --dry-run reports what it found."""

    def test_it_reads_title_version_and_operations(self) -> None:
        meta = read_meta(OPENAPI_YAML)
        assert meta.title == "Payments"
        assert meta.version == "1.0"
        assert meta.endpoints == 0

    def test_operations_are_counted_not_paths(self) -> None:
        """One path with GET and POST is two endpoints, which is what Elva
        reports back after the import."""
        data = b"""openapi: 3.0.3
info:
  title: T
paths:
  /a:
    get: {}
    post: {}
    parameters: []
  /b:
    delete: {}
"""
        assert read_meta(data).endpoints == 3

    def test_json_is_parsed_by_the_same_reader(self) -> None:
        assert read_meta(OPENAPI_JSON).title == "Payments"

    def test_an_unquoted_yaml_version_is_not_lost_to_float(self) -> None:
        """`version: 1.0` parses as a float; str() of it still has to render."""
        data = b"openapi: 3.0.3\ninfo:\n  title: T\n  version: 1.0\npaths: {}\n"
        assert read_meta(data).version == "1.0"

    @pytest.mark.parametrize(
        "data",
        [
            pytest.param(b"{{{ not parseable", id="broken"),
            pytest.param(b"- just\n- a list\n", id="not-a-mapping"),
            pytest.param(b"openapi: 3.0.3\n", id="no-info"),
            pytest.param(b"openapi: 3.0.3\ninfo: a string\n", id="info-not-a-mapping"),
        ],
    )
    def test_anything_unreadable_yields_an_empty_meta_rather_than_raising(
        self, data: bytes
    ) -> None:
        """This runs before the upload; a document the CLI cannot read may
        still be one the server accepts."""
        meta = read_meta(data)
        assert meta.title is None
        assert meta.version is None

    def test_a_missing_paths_block_leaves_the_count_unknown(self) -> None:
        """Unknown is not zero -- zero would trigger the empty-import warning."""
        assert read_meta(b"openapi: 3.0.3\ninfo:\n  title: T\n").endpoints is None
