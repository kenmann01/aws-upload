"""Packaging smoke test: both source packages must be importable."""


def test_both_packages_importable():
    import riskservice
    import simaws

    assert "deployable" in riskservice.__doc__
    assert "simulation" in simaws.__doc__


def test_python_dash_m_entrypoint_modules_import():
    import riskservice.__main__  # noqa: F401
    import simaws.__main__  # noqa: F401
