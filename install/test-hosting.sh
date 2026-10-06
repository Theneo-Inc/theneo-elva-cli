#!/bin/sh
set -eu

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT INT TERM

curl -fsS -D "$tmp/headers" http://127.0.0.1:5000/ -o "$tmp/install.sh"
cmp install/install.sh "$tmp/install.sh"
sh -n "$tmp/install.sh"
grep -iq '^Content-Type: text/plain; charset=utf-8' "$tmp/headers"
grep -iq '^Cache-Control: public, max-age=300' "$tmp/headers"
curl -fsS http://127.0.0.1:5000/install.sh -o "$tmp/direct.sh"
cmp install/install.sh "$tmp/direct.sh"
status="$(curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:5000/not-found)"
[ "$status" = 404 ]
