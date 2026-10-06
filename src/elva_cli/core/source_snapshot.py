"""Bounded, filtered snapshots of a local working tree; never execute project code."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pathspec import GitIgnoreSpec

from elva_cli.errors import UsageError

MAX_FILES = 500
MAX_BYTES = 4 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024
EXTENSIONS = frozenset(
    [
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".py",
        ".go",
        ".java",
        ".kt",
        ".kts",
        ".rb",
        ".php",
        ".cs",
        ".rs",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".xml",
        ".gradle",
        ".csproj",
        ".txt",
    ]
)
MANIFESTS = frozenset({"Dockerfile", "Gemfile", "go.mod", "go.sum"})
EXCLUDED = frozenset(
    {
        "node_modules",
        "vendor",
        "dist",
        "build",
        "target",
        "venv",
        "__pycache__",
        "coverage",
        "tests",
        "test",
        "__tests__",
        "fixtures",
        "credentials",
        "secrets",
        "outputs",
    }
)
SECRET_NAMES = re.compile(r"^(?:credentials|secrets)(?:\..*)?$|^id_(?:rsa|ed25519)$", re.I)
TOKENS = re.compile(
    r"(?:gh[pors]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|AIza[\w-]{30,}|(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}|xox[bp]-[A-Za-z0-9-]{10,}|eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,})"
)
ASSIGNMENT = re.compile(
    r"(['\"]?\b[\w-]*(?:password|passwd|secret|token|api[_-]?key)[\w-]*['\"]?\s*[:=]\s*)(['\"])([^'\"\n]+)\2",
    re.I,
)
BARE_ASSIGNMENT = re.compile(
    r"(^[ \t]*[\w-]*(?:password|passwd|secret|token|api[_-]?key)[\w-]*[ \t]*:[ \t]*)"
    r"(?![\s\"\'|>\[{])([^\s#]+)",
    re.I | re.M,
)
PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
)
DATABASE_URL = re.compile(
    r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)s?://[^\s'\"`<>]+", re.I
)


@dataclass(frozen=True)
class Snapshot:
    payload: dict[str, Any]
    root: Path
    bytes: int
    excluded: int
    redactions: int


def _read(path: Path) -> bytes:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise UsageError("Source snapshot can contain only regular files.")
    # Windows lacks the POSIX flags. Keep byte reads and verify file identity
    # before reading so a replacement or symlink cannot bypass filtering.
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0)
    )
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise UsageError("Source snapshot can contain only regular files.")
        if not os.path.samestat(before, info):
            raise UsageError("Source file changed while preparing the snapshot. Try again.")
        return stream.read(MAX_FILE_BYTES + 1)


def _git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), *args],
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (
        result.stdout.decode("utf-8", errors="replace").strip() if result.returncode == 0 else None
    )


def source_root(cwd: Path, selected: Path | None) -> Path:
    if selected is not None:
        root = (cwd / selected).resolve()
    else:
        root = next((p for p in (cwd, *cwd.parents) if (p / ".git").exists()), cwd).resolve()
    if not root.is_dir():
        raise UsageError("--path must point to an API source directory.")
    return root


def build_snapshot(cwd: Path, selected: Path | None = None) -> Snapshot:
    root = source_root(cwd, selected)
    in_git = _git(root, "rev-parse", "--is-inside-work-tree") == "true"
    files: list[dict[str, str]] = []
    total = excluded = redactions = 0
    rules: dict[Path, list[tuple[Path, str, GitIgnoreSpec]]] = {}

    def read_rules(parent: Path, names: tuple[str, ...]) -> list[tuple[Path, str, GitIgnoreSpec]]:
        parsed = []
        for ignore_name in names:
            ignore = parent / ignore_name
            if ignore.is_file() and not ignore.is_symlink():
                try:
                    raw = _read(ignore)
                    if len(raw) > MAX_FILE_BYTES:
                        raise UsageError(f"Ignore file is too large: {ignore}")
                    parsed.append(
                        (
                            parent,
                            ignore_name,
                            GitIgnoreSpec.from_lines(raw.decode("utf-8").splitlines()),
                        )
                    )
                except (OSError, UnicodeError) as exc:
                    raise UsageError(
                        f"Could not read ignore rules: {ignore}. No source was uploaded."
                    ) from exc
        return parsed

    checkout = next(
        (p for p in (root, *root.parents) if (p / ".git").exists()),
        cwd.resolve() if cwd.resolve() in root.parents else root,
    )
    ancestors = []
    ancestor = root.parent
    while root != checkout and (ancestor == checkout or checkout in ancestor.parents):
        ancestors.append(ancestor)
        if ancestor == checkout:
            break
        ancestor = ancestor.parent
    rules[root.parent] = [
        rule
        for parent in reversed(ancestors)
        for rule in read_rules(parent, (".gitignore", ".elvaignore"))
    ]
    for directory, directories, names in os.walk(root, followlinks=False):
        parent = Path(directory)
        inherited = list(rules.get(parent.parent, []))
        inherited.extend(read_rules(parent, (".gitignore", ".elvaignore")))
        rules[parent] = inherited

        def ignored(
            candidate: Path,
            is_dir: bool = False,
            active_rules: list[tuple[Path, str, GitIgnoreSpec]] = inherited,
        ) -> bool:
            decisions = {".gitignore": False, ".elvaignore": False}
            for base, kind, specification in active_rules:
                match = specification.check_file(
                    candidate.relative_to(base).as_posix() + ("/" if is_dir else "")
                )
                if match.include is not None:
                    decisions[kind] = match.include
            return any(decisions.values())

        kept = []
        for name in sorted(directories):
            candidate = parent / name
            if (
                name.startswith(".")
                or name.lower() in EXCLUDED
                or candidate.is_symlink()
                or ignored(candidate, True)
            ):
                excluded += 1
            else:
                kept.append(name)
        directories[:] = kept
        git_ignored: set[str] = set()
        if in_git and names:
            relative_names = [(parent / n).relative_to(root).as_posix() for n in names]
            try:
                checked = subprocess.run(
                    [
                        "git",
                        "--no-optional-locks",
                        "-c",
                        "core.fsmonitor=false",
                        "-C",
                        str(root),
                        "check-ignore",
                        "--no-index",
                        "-z",
                        "--stdin",
                    ],
                    input=("\0".join(relative_names) + "\0").encode(),
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
                if checked.returncode not in {0, 1}:
                    raise UsageError("Could not check Git ignore rules. No source was uploaded.")
                git_ignored = set(checked.stdout.decode().split("\0"))
            except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
                raise UsageError(
                    "Could not check Git ignore rules. No source was uploaded."
                ) from exc
        for name in sorted(names):
            candidate = parent / name
            relative = candidate.relative_to(root).as_posix()
            if (
                name.startswith(".")
                or SECRET_NAMES.search(name)
                or candidate.is_symlink()
                or relative in git_ignored
                or ignored(candidate)
                or (candidate.suffix.lower() not in EXTENSIONS and name not in MANIFESTS)
                or name.endswith((".lock", "-lock.json"))
                or ".test." in name
                or ".spec." in name
            ):
                excluded += 1
                continue
            if len(relative) > 500 or any(ord(c) < 32 for c in relative) or "\\" in relative:
                raise UsageError("Source contains an unsupported filename.")
            try:
                raw = _read(candidate)
                if len(raw) > MAX_FILE_BYTES:
                    raise UsageError(
                        f"Source file exceeds 256 KiB: {relative}. "
                        "Narrow --path or use .elvaignore."
                    )
                if b"\0" in raw:
                    excluded += 1
                    continue
                content = raw.decode("utf-8")
            except UnicodeError:
                excluded += 1
                continue
            except OSError as exc:
                raise UsageError(f"Could not read source file: {relative}") from exc
            for pattern in (PRIVATE_KEY, TOKENS, DATABASE_URL):
                content, count = pattern.subn("[REDACTED]", content)
                redactions += count
            content, count = ASSIGNMENT.subn(lambda m: m[1] + m[2] + "[REDACTED]" + m[2], content)
            redactions += count
            content, count = BARE_ASSIGNMENT.subn(lambda m: m[1] + "[REDACTED]", content)
            redactions += count
            total += len(content.encode("utf-8"))
            files.append({"path": relative, "content": content})
            if len(files) > MAX_FILES or total > MAX_BYTES:
                raise UsageError(
                    "Source snapshot exceeds 500 files or 4 MiB. "
                    "Select the API directory with --path or add .elvaignore rules."
                )
    if not files:
        raise UsageError(
            "No source files found. Run inside the API checkout or select it with --path."
        )
    payload: dict[str, Any] = {"name": root.name[:100], "files": files}
    commit = _git(root, "rev-parse", "HEAD")
    if commit and re.fullmatch(r"[a-f0-9]{40,64}", commit):
        payload["commitSha"] = commit
        branch = _git(root, "branch", "--show-current")
        if branch:
            payload["branch"] = branch[:200]
        payload["dirty"] = bool(_git(root, "status", "--porcelain"))
    return Snapshot(payload, root, total, excluded, redactions)
