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

    class _Dumper(yaml.SafeDumper):
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
