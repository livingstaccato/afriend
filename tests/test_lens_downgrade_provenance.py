"""`--lens was given` must mean the operator gave it.

`runmeta._resolve_fresh_profile` writes a review profile's `lenses` into
`args.lens`, so the merged value cannot distinguish a typed flag from an
inherited setting. Testing it directly put a false statement about the
invocation into the run's durable downgrades and into report.md -- in the
record whose whole purpose is to say what the invocation was.
"""

import argparse

from afriend.commands.friends import _lens_was_passed


def _args(**over):
    base = {"lens": None, "_profile_settings_explicit": set()}
    base.update(over)
    return argparse.Namespace(**base)


def test_a_profile_supplied_lens_is_not_reported_as_given():
    args = _args(lens=["ops", "security"])
    assert _lens_was_passed(args) is False


def test_an_operator_supplied_lens_is_reported_as_given():
    args = _args(lens=["ops"], _profile_settings_explicit={"lens"})
    assert _lens_was_passed(args) is True


def test_no_lens_at_all_is_never_reported():
    assert _lens_was_passed(_args()) is False
    assert _lens_was_passed(_args(lens=[])) is False
    assert _lens_was_passed(_args(lens=[], _profile_settings_explicit={"lens"})) is False


def test_a_namespace_without_the_marker_keeps_its_own_value():
    """Hand-built namespaces carry no `_profile_settings_explicit`. They get
    the same benefit of the doubt `_mode_explicit` already gives them, so
    this change cannot silence a note for a caller that never had a
    profile."""
    bare = argparse.Namespace(lens=["ops"])
    assert _lens_was_passed(bare) is True
