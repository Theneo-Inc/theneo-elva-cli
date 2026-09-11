"""Normalising a spec's byte form before it is stored.

The web app converts JSON specs to YAML on the way in -- its editor works in
YAML -- so a collection created through it holds an indented document rather
than the single minified line a CDN typically serves. Doing the same here keeps
a CLI import readable, and close to byte-identical with one made from the web
app.
"""

from __future__ import annotations


def to_yaml(data: bytes) -> bytes:
    """A JSON document re-serialised as indented YAML; anything else unchanged.

    Only JSON is touched. Re-emitting a YAML document through a parser would
    drop its comments and reorder its keys, and it is already the readable form
    this exists to produce.
    """
    import json

    try:
        document = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return data
    if not isinstance(document, dict):
        return data

    import yaml

    class _Dumper(_base()):  # type: ignore[misc]
        def ignore_aliases(self, data: object) -> bool:
            # A spec carries no anchors worth keeping; without this a repeated
            # sub-object would come back as `&id001`/`*id001` references.
            return True

    return yaml.dump(
        document,
        Dumper=_Dumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=4096,
    ).encode("utf-8")


def _base() -> type:
    """libyaml's dumper where the wheel was built with it, PyYAML's otherwise.

    This runs on every JSON import, `--dry-run` included, and the pure-Python
    emitter is where the time goes: a 0.5 MB spec measured 1.07s against 0.30s.
    Near the 10 MB limit that is the difference between a pause and a command
    that looks hung. The two emit the same document -- same key order, same
    unicode, same lack of anchors -- so this only picks the faster one.
    """
    import yaml

    return getattr(yaml, "CSafeDumper", yaml.SafeDumper)
