#!/usr/bin/env python3
"""Verify published release bytes and stage only distributions still missing.

This helper never uploads. A retry must use the original downloaded release
artifacts: rebuilding an sdist can change its bytes and must fail verification.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

PROJECTS = ("afriend", "adversarial-friends", "afriends")
_NOT_PUBLISHED = object()


class PublishPreparationError(Exception):
    """An index response or local artifact cannot safely support publication."""


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _index_base(index_url: str) -> str:
    parts = urlsplit(index_url)
    official = index_url.rstrip("/") in ("https://pypi.org", "https://test.pypi.org")
    loopback = (
        parts.scheme == "http"
        and parts.hostname in ("127.0.0.1", "localhost", "::1")
        and not parts.username
        and not parts.password
        and parts.path in ("", "/")
        and not parts.query
        and not parts.fragment
    )
    if not official and not loopback:
        raise PublishPreparationError("index URL must be PyPI, TestPyPI, or loopback HTTP")
    return index_url.rstrip("/")


def _published_files(index_url: str, project: str, version: str, timeout: float) -> object:
    url = f"{_index_base(index_url)}/pypi/{project}/{version}/json"
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise PublishPreparationError(f"index query returned HTTP {response.status}")
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            return _NOT_PUBLISHED
        raise PublishPreparationError(f"index query failed: HTTP {exc.code}") from exc
    except (URLError, OSError, ValueError) as exc:
        raise PublishPreparationError(f"index query failed: {exc}") from exc


def _verify_metadata(
    metadata: object, project: str, version: str, artifacts: dict[str, bytes]
) -> set[str]:
    if not isinstance(metadata, dict):
        raise PublishPreparationError("index metadata must be a JSON object")
    info = metadata.get("info")
    if (
        not isinstance(info, dict)
        or not isinstance(info.get("name"), str)
        or _normalize(info["name"]) != project
        or info.get("version") != version
    ):
        raise PublishPreparationError(
            "index metadata project/version does not match requested release"
        )
    urls = metadata.get("urls")
    if not isinstance(urls, list) or not urls:
        raise PublishPreparationError("index metadata must contain a nonempty urls list")
    verified: set[str] = set()
    for entry in urls:
        if not isinstance(entry, dict):
            raise PublishPreparationError("malformed index file entry")
        name = entry.get("filename")
        if not isinstance(name, str) or name not in artifacts or name in verified:
            raise PublishPreparationError(f"unexpected or duplicate index filename: {name!r}")
        digests = entry.get("digests")
        digest = digests.get("sha256") if isinstance(digests, dict) else None
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise PublishPreparationError(f"missing or malformed SHA256 for {name}")
        if hashlib.sha256(artifacts[name]).hexdigest() != digest.lower():
            raise PublishPreparationError(
                f"SHA256 mismatch for {name}; use original release artifacts"
            )
        verified.add(name)
    return verified


def prepare_publish(
    project: str,
    version: str,
    dist: Path,
    stage: Path,
    index_url: str,
    github_output: Path | None = None,
    *,
    timeout: float = 15.0,
) -> bool:
    """Stage missing files after verifying all remote hashes; return pending status."""
    project = _normalize(project)
    if project not in PROJECTS:
        raise PublishPreparationError(f"unsupported project: {project}")
    if not re.fullmatch(r"[0-9][A-Za-z0-9.!+_-]*", version):
        raise PublishPreparationError("invalid release version")
    if stage.is_symlink() or (stage.exists() and (not stage.is_dir() or any(stage.iterdir()))):
        raise PublishPreparationError("stage directory must be fresh or empty")
    if stage.resolve() == dist.resolve():
        raise PublishPreparationError("stage directory must differ from artifact directory")
    stem = project.replace("-", "_")
    names = (f"{stem}-{version}-py3-none-any.whl", f"{stem}-{version}.tar.gz")
    artifacts: dict[str, bytes] = {}
    for name in names:
        path = dist / name
        if path.is_symlink() or not path.is_file():
            raise PublishPreparationError(f"missing original artifact: {name}")
        artifacts[name] = path.read_bytes()
    metadata = _published_files(index_url, project, version, timeout)
    verified = (
        set()
        if metadata is _NOT_PUBLISHED
        else _verify_metadata(metadata, project, version, artifacts)
    )
    # Validate the complete response before creating any uploadable output.
    stage.mkdir(parents=True, exist_ok=True)
    for name in sorted(verified):
        print(f"Verified {name}")
    missing = sorted(artifacts.keys() - verified)
    for name in missing:
        with (stage / name).open("xb") as output:
            output.write(artifacts[name])
        print(f"Staged {name}")
    pending = bool(missing)
    if github_output is not None:
        with github_output.open("a", encoding="utf-8") as output:
            output.write(f"pending={str(pending).lower()}\n")
    print(f"pending={str(pending).lower()}")
    return pending


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, choices=PROJECTS)
    parser.add_argument("--version", required=True)
    parser.add_argument("--dist", required=True, type=Path)
    parser.add_argument("--stage", required=True, type=Path)
    parser.add_argument("--index-url", required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    try:
        prepare_publish(
            args.project, args.version, args.dist, args.stage, args.index_url, args.github_output
        )
    except (PublishPreparationError, OSError) as exc:
        print(f"Publish preparation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
