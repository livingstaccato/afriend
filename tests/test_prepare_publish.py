"""Release retries verify immutable bytes before staging missing distributions."""

from contextlib import contextmanager, suppress
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "ci" / "prepare_publish.py"
VERSION = "1.2.3"


def artifacts(tmp_path, project="afriend"):
    dist = tmp_path / "dist"
    dist.mkdir()
    stem = project.replace("-", "_")
    names = [f"{stem}-{VERSION}-py3-none-any.whl", f"{stem}-{VERSION}.tar.gz"]
    for name in names:
        (dist / name).write_bytes(f"original {name}".encode())
    return dist, names


def metadata(dist, names, project="afriend", version=VERSION):
    return {
        "info": {"name": project, "version": version},
        "urls": [
            {
                "filename": name,
                "digests": {"sha256": hashlib.sha256((dist / name).read_bytes()).hexdigest()},
            }
            for name in names
        ],
    }


@contextmanager
def index(status, payload, delay=0):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            time.sleep(delay)
            self.send_response(status)
            self.end_headers()
            with suppress(BrokenPipeError):
                self.wfile.write(
                    payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                )

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def run_prepare(tmp_path, dist, url, project="afriend"):
    return subprocess.run(
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
            str(tmp_path / "stage"),
            "--index-url",
            url,
            "--github-output",
            str(tmp_path / "output"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("project", ["afriend", "adversarial-friends", "afriends"])
def test_new_release_stages_exact_pair(tmp_path, project):
    dist, names = artifacts(tmp_path, project)
    (dist / "unrelated.whl").write_bytes(b"never upload me")
    with index(404, {}) as (url, requests):
        result = run_prepare(tmp_path, dist, url, project)
    assert result.returncode == 0, result.stderr
    assert requests == [f"/pypi/{project}/{VERSION}/json"]
    assert sorted(path.name for path in (tmp_path / "stage").iterdir()) == sorted(names)
    assert (tmp_path / "output").read_text() == "pending=true\n"
    for name in names:
        assert (tmp_path / "stage" / name).read_bytes() == (dist / name).read_bytes()


@pytest.mark.parametrize("count", [1, 2])
def test_existing_matching_files_are_verified_and_only_missing_are_staged(tmp_path, count):
    dist, names = artifacts(tmp_path)
    with index(200, metadata(dist, names[:count])) as (url, _):
        result = run_prepare(tmp_path, dist, url)
    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in (tmp_path / "stage").iterdir()) == sorted(names[count:])
    assert (tmp_path / "output").read_text() == f"pending={'true' if count == 1 else 'false'}\n"
    for name in names[:count]:
        assert f"Verified {name}" in result.stdout


@pytest.mark.parametrize(
    "failure",
    ["hash", "name", "version", "unknown", "duplicate", "digest", "urls", "info", "empty"],
)
def test_bad_remote_metadata_fails_without_staging(tmp_path, failure):
    dist, names = artifacts(tmp_path)
    payload = metadata(dist, names)
    if failure == "hash":
        payload["urls"][0]["digests"]["sha256"] = "0" * 64
    elif failure == "name":
        payload["info"]["name"] = "other"
    elif failure == "version":
        payload["info"]["version"] = "9.9.9"
    elif failure == "unknown":
        payload["urls"][0]["filename"] = "unexpected.whl"
    elif failure == "duplicate":
        payload["urls"].append(payload["urls"][0])
    elif failure == "digest":
        payload["urls"][0]["digests"] = {}
    elif failure == "urls":
        payload["urls"] = None
    elif failure == "info":
        payload["info"] = None
    else:
        payload["urls"] = []
    with index(200, payload) as (url, _):
        result = run_prepare(tmp_path, dist, url)
    assert result.returncode == 1
    assert "Publish preparation failed:" in result.stderr
    assert not (tmp_path / "output").exists()
    assert not (tmp_path / "stage").exists()


@pytest.mark.parametrize(
    ("status", "payload"), [(503, {}), (200, b"invalid json"), (200, []), (200, None)]
)
def test_network_and_json_errors_fail_closed(tmp_path, status, payload):
    dist, _ = artifacts(tmp_path)
    with index(status, payload) as (url, _):
        result = run_prepare(tmp_path, dist, url)
    assert result.returncode == 1
    assert "Publish preparation failed:" in result.stderr
    assert not (tmp_path / "output").exists()
    assert not (tmp_path / "stage").exists()


def test_stale_stage_is_rejected_without_deleting_contents(tmp_path):
    dist, _ = artifacts(tmp_path)
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "stale.whl").write_bytes(b"keep")
    with index(404, {}) as (url, _):
        result = run_prepare(tmp_path, dist, url)
    assert result.returncode == 1
    assert "Publish preparation failed:" in result.stderr
    assert (stage / "stale.whl").read_bytes() == b"keep"
    assert not (tmp_path / "output").exists()


def test_timeout_fails_closed(tmp_path):
    assert SCRIPT.exists(), "publish preparation helper is required"
    spec = importlib.util.spec_from_file_location("prepare_publish", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dist, _ = artifacts(tmp_path)
    with (
        index(200, {}, delay=0.1) as (url, _),
        pytest.raises(module.PublishPreparationError, match="query"),
    ):
        module.prepare_publish("afriend", VERSION, dist, tmp_path / "stage", url, timeout=0.01)
    assert not (tmp_path / "stage").exists()


def test_existing_empty_stage_and_output_append(tmp_path):
    dist, names = artifacts(tmp_path)
    stage = tmp_path / "stage"
    stage.mkdir()
    output = tmp_path / "output"
    output.write_text("previous=value\n")
    with index(404, {}) as (url, _):
        result = run_prepare(tmp_path, dist, url)
    assert result.returncode == 0, result.stderr
    assert sorted(path.name for path in stage.iterdir()) == sorted(names)
    assert output.read_text() == "previous=value\npending=true\n"


def test_missing_original_artifact_fails_before_query(tmp_path):
    dist, names = artifacts(tmp_path)
    (dist / names[1]).unlink()
    with index(404, {}) as (url, requests):
        result = run_prepare(tmp_path, dist, url)
    assert result.returncode == 1
    assert "missing original artifact" in result.stderr
    assert requests == []
    assert not (tmp_path / "output").exists()


def test_remote_project_name_normalization(tmp_path):
    dist, names = artifacts(tmp_path, "adversarial-friends")
    payload = metadata(dist, names, project="Adversarial_Friends")
    with index(200, payload) as (url, _):
        result = run_prepare(tmp_path, dist, url, "adversarial-friends")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "output").read_text() == "pending=false\n"


@pytest.mark.parametrize(
    "url", ["http://pypi.org", "https://example.com", "https://pypi.org/other"]
)
def test_untrusted_index_url_rejected(tmp_path, url):
    dist, _ = artifacts(tmp_path)
    result = run_prepare(tmp_path, dist, url)
    assert result.returncode == 1
    assert "index URL must be" in result.stderr
    assert not (tmp_path / "stage").exists()
