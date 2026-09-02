# Releasing Elva CLI

Releases are cut by pushing a git tag. Nothing else. There is no version to bump,
no file to edit, no credential to hold.

```bash
git tag v0.1.0
git push origin v0.1.0
```

GitHub Actions builds, validates and publishes to PyPI. The rest of this document
explains what that does and what to do when it goes wrong.

---

## How versioning works

The version is derived from the git tag by `hatch-vcs`. `pyproject.toml` declares
`dynamic = ["version"]` and has no version string in it, on purpose - a hand-edited
version and a tag will eventually disagree, and the tag is the one users can verify.

| Git state | Version produced | Publishable |
|---|---|---|
| On tag `v0.0.2`, clean tree | `0.0.2` | yes |
| One commit past the tag | `0.0.2.post1.dev1+g1a2b3c4` | **no** |
| Untagged repo | `0.0.post1.dev2+gc657326` | **no** |
| Shallow clone (no tags fetched) | `0.0.post1.devN+g...` | **no** |

The leading `v` is stripped automatically, so tag `v0.0.2` yields version `0.0.2`.

**Anything after a `+` is a PEP 440 local version segment, and PyPI rejects every
upload that has one.** This is a registry rule, not a configuration problem. It means
releases can only be built from an exact tag on a clean tree. The workflow enforces
this rather than letting you discover it as a rejected upload.

---

## Before you tag

```bash
ruff check . && ruff format --check .
mypy
pytest
```

Then confirm the artifact you are about to ship actually works, built the same way CI
builds it:

```bash
rm -rf dist && uv build
uvx twine check dist/*

python3 -m venv /tmp/rc && /tmp/rc/bin/pip install dist/*.whl
cd /tmp && /tmp/rc/bin/elva --version    # run from outside the source tree
```

Running from outside the source tree matters: inside it, Python may import `elva_cli`
from `src/` rather than from the installed wheel, which hides packaging mistakes.

Choose the version:

- **`0.0.x`** Increase when adding small update or patch.
- **`0.x.0`** Increase when adding any minor feature, update, new command, etc.
- **`1.0.0`** Major releases are done only by team agreement and when updating business logic, large feature or something new worth updating.

---

## Releasing

```bash
git tag v0.0.2
git push origin v0.0.2
```

Watch **Actions -> release**. The `pypi` job pauses for a required reviewer; approve it.

Then verify from the outside, not from your machine's cache:

```bash
uvx --refresh --from elva-cli==0.0.2 elva --version
```

`--refresh` is not optional here. `uv` will happily reuse a locally installed or cached
build and report a version that never came from PyPI. Anyone who has run
`uv tool install --editable` on this repo will see their local build instead unless they
pass it.

---

## What the pipeline does

`.github/workflows/release.yml`, in order:

1. **Checkout with `fetch-depth: 0`.** A shallow clone has no tags, so `hatch-vcs`
   silently produces a dev version. This is the single most common cause of a broken
   release with tag-derived versioning.
2. **`uv build`** -- sdist and wheel.
3. **Version guard.** Fails if the version contains `+` (local segment) or `dev`. Better
   a red build than a rejected upload against a version number you can never reuse.
4. **`twine check`** -- metadata and long-description rendering.
5. **Wheel smoke test.** Installs the built wheel into a clean venv and runs
   `elva --version` from `/tmp`. Catches broken `[project.scripts]`, a misconfigured
   `src/` layout, and missing package data -- none of which show up in an editable
   install.
6. **Publish.** Waits on the `pypi` environment approval, then uploads via PyPI Trusted
   Publishing.

### Trusted publishing

There is no API token anywhere -- not in GitHub secrets, not on anyone's laptop. At
release time GitHub issues a short-lived OIDC token proving "I am `release.yml` in
`Theneo-Inc/theneo-elva-cli`, running in the `pypi` environment". PyPI checks that
against the publisher registered for the project and only then accepts the upload.

Consequences worth knowing:

- The **GitHub environment name is part of the identity.** Renaming or deleting the
  `pypi` environment breaks publishing.
- **Renaming the workflow file breaks publishing.** The publisher references
  `release.yml` by filename.
- Changing either requires updating the publisher config on PyPI, which needs the
  **Owner** role.

---

## Rehearsing on TestPyPI

Actions -> release -> **Run workflow** publishes to TestPyPI instead of PyPI.

Note that a manual dispatch from an untagged commit will fail the version guard, which
is correct. To rehearse a real upload, tag first, then dispatch.

Installing from TestPyPI needs a fallback index, because TestPyPI does not carry
`typer`:

```bash
python3 -m venv /tmp/tv && /tmp/tv/bin/pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ elva-cli
```

---

## Things that cannot be undone

- **A version number is burned forever.** Once `0.0.2` is uploaded you can never upload
  a file to `0.0.2` again, even after deleting the release. Deleting frees the name for
  nobody. If a release is bad, ship `0.0.3`.
- **Prefer yanking to deleting.** Yanking hides a release from new installs while
  keeping it resolvable for anyone who pinned it, so you do not break existing
  lockfiles. Deleting breaks them.
- **Metadata is frozen per release.** The description, classifiers and license shown on
  PyPI come from the uploaded artifact. Fixing them requires a new version.
- **Project names normalise.** `elva-cli`, `elva_cli` and `Elva.CLI` are all the same
  project on PyPI.

---

## Troubleshooting

**`Version ... has a PEP 440 local segment` (build job fails)**
You tagged, but HEAD has moved past the tag, or the tree is dirty. `git describe --tags`
should print exactly your tag with no suffix.

**Version came out as `0.0.post1.devN`**
`fetch-depth: 0` is missing from the checkout step, or the tag was never pushed. Tags do
not travel with `git push`; they need `git push origin vX.Y.Z`.

**`invalid-publisher` / OIDC or permissions error on the publish job**
The identity does not match the registered publisher. All five must agree exactly, and
they are case-sensitive: project name, owner, repository name, workflow filename,
environment name. A green build with a red publish points here, not at your code. Only a
project **Owner** on PyPI can inspect or fix this.

**`File already exists`**
That version is burned. Bump and retag.

**`403 Forbidden` on upload**
Either the publisher was never registered for this project, or the release job is
missing `permissions: id-token: write`.

**Published fine, but `elva --version` shows the old version**
Local cache or an editable tool install shadowing it. Check `uv tool list`, then
`uvx --refresh --from elva-cli==<version> elva --version`.

---

## Access

Publishing needs no personal credentials -- CI does it. Accounts matter only for
administration:

- **Owner** on the PyPI project: manage trusted publishers, collaborators, yank or
  delete releases.
- **Maintainer**: upload only. Not enough to fix the publishing configuration.

Keep **at least two Owners**. A single-owner package on one person's personal account
means that if they leave, recovering the name goes through PyPI support.
