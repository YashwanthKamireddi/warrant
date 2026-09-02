"""What a consumer gets when they install this, rather than when they clone it.

Everything here is invisible from inside the repo and load-bearing outside it:
a package whose annotations do not ship is an untyped package no matter how
carefully it is annotated, and a distribution name that collides with something
already on PyPI installs somebody else's library.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import warrant

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_the_package_ships_its_type_information():
    """Without py.typed, every annotation in this package is invisible.

    PEP 561: a type checker ignores a dependency's inline annotations unless the
    package declares itself typed. The file has no contents; its presence is the
    whole declaration.
    """
    assert (Path(warrant.__file__).parent / "py.typed").is_file()


def test_the_marker_is_included_in_the_wheel():
    """Being in the tree is not the same as being in the artifact."""
    wheel = PYPROJECT["tool"]["hatch"]["build"]["targets"]["wheel"]
    # hatchling ships every file inside a declared package directory, so listing
    # the package is what carries py.typed. If this ever becomes an explicit
    # include list, py.typed has to be on it.
    assert "engine/warrant" in wheel["packages"]


def test_the_distribution_name_does_not_collide_with_pypi():
    """`warrant` on PyPI is a Boto3 Cognito client. Ours is `warrant-pay`."""
    assert PYPROJECT["project"]["name"] == "warrant-pay"


def test_the_version_is_declared_in_exactly_one_place():
    """Two versions that can disagree eventually do."""
    assert PYPROJECT["project"]["version"] == warrant.__version__


def test_the_public_api_is_importable_from_the_top_level():
    """What __all__ promises has to actually be there."""
    for name in warrant.__all__:
        assert hasattr(warrant, name), f"warrant.__all__ names {name}, which is missing"


def test_nothing_in_the_public_api_is_private():
    assert not [n for n in warrant.__all__ if n.startswith("_") and n != "__version__"]


def test_the_cli_exposes_both_the_console_and_the_service():
    """`serve` is the demonstration; `api` is the thing that goes near money."""
    from warrant.cli import build_parser

    actions = build_parser()._subparsers._group_actions[0].choices  # type: ignore[attr-defined]
    assert "serve" in actions
    assert "api" in actions


def test_the_integration_guide_exists_and_is_executable_by_the_build():
    """Prose is not executed, so a doc gate is the only thing holding it true."""
    assert (ROOT / "docs" / "INTEGRATION.md").is_file()
    makefile = (ROOT / "Makefile").read_text()
    assert "docs-examples" in makefile
