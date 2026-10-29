"""Exercise interrupted publication with real Twine against a loopback-only index."""

from collections import Counter
from email import policy
from email.parser import BytesParser
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import threading
import zipfile

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "ci" / "prepare_publish.py"
VERSION = "0.0.0"
pytestmark = [pytest.mark.external, pytest.mark.slow]


def make_artifacts(directory, project):
    directory.mkdir()
    stem = project.replace("-", "_")
    base = f"{stem}-{VERSION}"
    metadata = (
        f"Metadata-Version: 2.1\nName: {project}\nVersion: {VERSION}\n"
        "Summary: Loopback publication fixture\n"
    ).encode()
    wheel = directory / f"{base}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"{base}.dist-info/METADATA", metadata)
        archive.writestr(
            f"{base}.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(f"{base}.dist-info/RECORD", "")
    sdist = directory / f"{base}.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        root = tarfile.TarInfo(base)
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        member = tarfile.TarInfo(f"{base}/PKG-INFO")
        member.size = len(metadata)
        archive.addfile(member, io.BytesIO(metadata))
    return wheel.name, sdist.name


@pytest.fixture
def registry():
    published = {}
    attempts = []
    fail_once = set()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            segments = self.path.strip("/").split("/")
            if len(segments) != 4 or segments[0] != "pypi" or segments[2:] != [VERSION, "json"]:
                self.send_error(404)
                return
            project = segments[1]
            files = published.get(project)
            if not files:
                self.send_error(404)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "info": {"name": project, "version": VERSION},
                        "urls": [
                            {"filename": name, "digests": {"sha256": digest}}
                            for name, digest in sorted(files.items())
                        ],
                    }
                ).encode()
            )

        def do_POST(self):
            assert self.path == "/legacy/"
            body = self.rfile.read(int(self.headers["Content-Length"]))
            message = BytesParser(policy=policy.default).parsebytes(
                f"Content-Type: {self.headers['Content-Type']}\r\nMIME-Version: 1.0\r\n\r\n".encode()
                + body
            )
            content = next(
                part
                for part in message.iter_parts()
                if part.get_param("name", header="content-disposition") == "content"
            )
            filename = content.get_filename()
            project = (
                "adversarial-friends" if filename.startswith("adversarial_friends-") else "afriend"
            )
            status = 200
            if filename in fail_once:
                fail_once.remove(filename)
                # A nonduplicate 400 interrupts Twine without its 503 retry sleeps.
                status = 400
            elif filename in published.get(project, {}):
                status = 409
            else:
                published.setdefault(project, {})[filename] = hashlib.sha256(
                    content.get_payload(decode=True)
                ).hexdigest()
            attempts.append((project, filename, status))
            self.send_response(status)
            self.end_headers()
            self.wfile.write(b"Temporary fixture rejection" if status == 400 else b"")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        yield url, published, attempts, fail_once
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.fixture
def twine():
    uvx = shutil.which("uvx")
    if uvx is None:
        pytest.skip("uvx is required for real Twine publication integration")
    return [uvx, "--from", "twine==7.0.0", "twine"]


def prepare(tmp_path, dist, url, project, attempt):
    stage = tmp_path / f"stage-{project}-{attempt}"
    output = tmp_path / f"output-{project}-{attempt}"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--project",
            project,
            "--version",
            VERSION,
            "--dist",
            str(dist),
            "--stage",
            str(stage),
            "--index-url",
            url,
            "--github-output",
            str(output),
        ],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    return result, stage, output


def upload(twine, url, stage):
    files = sorted(stage.iterdir())
    assert files, "the publisher must not run when pending=false"
    # Explicit loopback URL and fixture credentials prevent consulting user PyPI settings.
    env = {key: value for key, value in os.environ.items() if not key.startswith("TWINE_")}
    return subprocess.run(
        [
            *twine,
            "upload",
            "--non-interactive",
            "--disable-progress-bar",
            "--repository-url",
            f"{url}/legacy/",
            "--username",
            "fixture",
            "--password",
            "fixture",
            *map(str, files),
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )


def test_partial_canonical_upload_retries_only_missing_sdist(tmp_path, registry, twine):
    url, published, attempts, fail_once = registry
    dist = tmp_path / "dist"
    wheel, sdist = make_artifacts(dist, "afriend")
    fail_once.add(sdist)
    first, stage, output = prepare(tmp_path, dist, url, "afriend", 1)
    assert first.returncode == 0, first.stderr
    assert output.read_text() == "pending=true\n"
    interrupted = upload(twine, url, stage)
    assert interrupted.returncode != 0
    assert set(published.get("afriend", {})) == {wheel}, interrupted.stdout + interrupted.stderr
    second, stage, output = prepare(tmp_path, dist, url, "afriend", 2)
    assert second.returncode == 0, second.stderr
    assert [path.name for path in stage.iterdir()] == [sdist]
    assert output.read_text() == "pending=true\n"
    retry = upload(twine, url, stage)
    assert retry.returncode == 0, retry.stdout + retry.stderr
    assert set(published["afriend"]) == {wheel, sdist}
    assert attempts == [("afriend", wheel, 200), ("afriend", sdist, 400), ("afriend", sdist, 200)]


def test_alias_failure_retry_does_not_resend_completed_canonical(tmp_path, registry, twine):
    url, published, attempts, fail_once = registry
    canonical = tmp_path / "canonical"
    canonical_names = make_artifacts(canonical, "afriend")
    alias = tmp_path / "alias"
    alias_names = make_artifacts(alias, "adversarial-friends")
    first, stage, _ = prepare(tmp_path, canonical, url, "afriend", 1)
    assert first.returncode == 0, first.stderr
    result = upload(twine, url, stage)
    assert result.returncode == 0, result.stdout + result.stderr
    fail_once.add(alias_names[0])
    first_alias, stage, _ = prepare(tmp_path, alias, url, "adversarial-friends", 1)
    assert first_alias.returncode == 0, first_alias.stderr
    assert upload(twine, url, stage).returncode != 0
    retry, stage, output = prepare(tmp_path, canonical, url, "afriend", 2)
    assert retry.returncode == 0, retry.stderr
    assert output.read_text() == "pending=false\n"
    assert list(stage.iterdir()) == []
    retry_alias, stage, _ = prepare(tmp_path, alias, url, "adversarial-friends", 2)
    assert retry_alias.returncode == 0, retry_alias.stderr
    result = upload(twine, url, stage)
    assert result.returncode == 0, result.stdout + result.stderr
    assert set(published["afriend"]) == set(canonical_names)
    assert set(published["adversarial-friends"]) == set(alias_names)
    assert Counter(name for project, name, _ in attempts if project == "afriend") == Counter(
        canonical_names
    )


def test_forged_existing_hash_rejects_before_any_retry_upload(tmp_path, registry, twine):
    url, published, attempts, _ = registry
    dist = tmp_path / "dist"
    wheel, sdist = make_artifacts(dist, "afriend")
    first, stage, _ = prepare(tmp_path, dist, url, "afriend", 1)
    assert first.returncode == 0, first.stderr
    result = upload(twine, url, stage)
    assert result.returncode == 0, result.stdout + result.stderr
    published["afriend"][wheel] = "0" * 64
    before = list(attempts)
    retry, stage, output = prepare(tmp_path, dist, url, "afriend", 2)
    assert retry.returncode == 1
    assert "SHA256 mismatch" in retry.stderr
    assert not stage.exists()
    assert not output.exists()
    assert attempts == before == [("afriend", wheel, 200), ("afriend", sdist, 200)]
