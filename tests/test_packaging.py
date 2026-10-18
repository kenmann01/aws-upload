"""Packaging smoke test: both source packages must be importable."""


def test_both_packages_importable():
    import riskservice
    import simaws

    assert "deployable" in riskservice.__doc__
    assert "simulation" in simaws.__doc__
