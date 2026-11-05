"""Which directory counts as a CLI's installation root (§12.2).

`policy_for` grants the directory above `bin/` so a CLI can read its own
libraries -- opencode keeps a 61MB `node_modules/` there. The rule was
"the parent of any directory named bin", and a crossexam of sandbox.py
pointed out what that grants when the binary is a real file rather than a
symlink: `~/bin/tool` resolves to `~/bin`, whose parent is the home
directory the sandbox exists to remove.
"""

from pathlib import Path

from afriend import sandbox


def _tool(directory: Path, name: str = "tool") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return path


def test_a_general_purpose_bin_does_not_grant_its_parent(tmp_path, monkeypatch):
    """`~/bin/tool` and `~/.local/bin/tool` are the normal shape for a
    curl-installer or a single-file binary. Granting their parent hands a
    confined friend the whole home directory -- and the report still says it
    was confined."""
    home = tmp_path / "home"
    tool = _tool(home / "bin")
    monkeypatch.setattr(sandbox.shutil, "which", lambda _binary: str(tool))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    policy = sandbox.policy_for(tmp_path / "work", "tool", (), ())

    assert home not in policy.read_paths, [str(p) for p in policy.read_paths]
    assert (home / "bin") in policy.read_paths


def test_a_real_install_root_beside_bin_is_still_granted(tmp_path, monkeypatch):
    """The case the rule exists for: a package-manager layout where the
    CLI's libraries are its siblings' siblings, which is why granting only
    `bin/` left opencode unable to read itself."""
    root = tmp_path / "home" / ".opencode"
    tool = _tool(root / "bin", "opencode")
    (root / "node_modules").mkdir(parents=True)
    monkeypatch.setattr(sandbox.shutil, "which", lambda _binary: str(tool))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))

    policy = sandbox.policy_for(tmp_path / "work", "opencode", (), ())

    assert root in policy.read_paths, [str(p) for p in policy.read_paths]


def test_the_home_directory_is_never_an_install_root(tmp_path, monkeypatch):
    """Even a home directory that happens to contain a `lib/` is not one:
    the sandbox's whole purpose is removing the rest of the home directory,
    so no heuristic may hand it back."""
    home = tmp_path / "home"
    tool = _tool(home / "bin")
    (home / "lib").mkdir(parents=True)
    monkeypatch.setattr(sandbox.shutil, "which", lambda _binary: str(tool))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    policy = sandbox.policy_for(tmp_path / "work", "tool", (), ())

    assert home not in policy.read_paths, [str(p) for p in policy.read_paths]


def _npm_global(home: Path, scope: str | None, package: str) -> tuple[Path, Path, Path]:
    """`npm install -g --prefix ~/.local` layout: `bin/<cli>` links to a
    script inside the package, whose dependencies sit beside that script's
    directory rather than beside any `bin/`."""
    lib = home / ".local" / "lib" / "node_modules"
    package_root = (lib / scope / package) if scope else (lib / package)
    (package_root / "node_modules" / "dep").mkdir(parents=True)
    (package_root / "package.json").write_text("{}")
    script = _tool(package_root / "dist", "main.mjs")
    link_dir = home / ".local" / "bin"
    link_dir.mkdir(parents=True)
    link = link_dir / "cli"
    link.symlink_to(script)
    return link, package_root, lib


def test_an_npm_package_script_gets_its_package_root(tmp_path, monkeypatch):
    """kimi's shape: `~/.local/bin/kimi` -> `.../@moonshot-ai/kimi-code/dist/
    main.mjs`. Granting only `dist/` killed it on ERR_MODULE_NOT_FOUND for a
    dependency in the package's own `node_modules/`."""
    home = tmp_path / "home"
    link, package_root, lib = _npm_global(home, "@moonshot-ai", "kimi-code")
    monkeypatch.setattr(sandbox.shutil, "which", lambda _binary: str(link))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    policy = sandbox.policy_for(tmp_path / "work", "cli", (), ())

    assert package_root.resolve() in policy.read_paths, [str(p) for p in policy.read_paths]
    # One package, never the shared global node_modules or anything above it.
    for wider in (lib, lib / "@moonshot-ai", home / ".local", home):
        assert wider.resolve() not in policy.read_paths


def test_an_unscoped_npm_package_script_gets_its_package_root(tmp_path, monkeypatch):
    home = tmp_path / "home"
    link, package_root, lib = _npm_global(home, None, "some-cli")
    monkeypatch.setattr(sandbox.shutil, "which", lambda _binary: str(link))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    policy = sandbox.policy_for(tmp_path / "work", "cli", (), ())

    assert package_root.resolve() in policy.read_paths
    assert lib.resolve() not in policy.read_paths


def test_a_node_modules_directory_without_a_package_json_is_not_granted(tmp_path):
    """No manifest, no package: the rule must not guess a root."""
    script = _tool(tmp_path / "node_modules" / "loose" / "dist", "main.mjs")
    assert sandbox._node_package_root(script.resolve()) is None
