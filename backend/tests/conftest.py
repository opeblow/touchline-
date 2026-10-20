import pytest

from touchline.sim import build_league, simulate_match
from touchline.sim.scenario import PRESETS


@pytest.fixture(scope="session")
def league():
    return build_league()


@pytest.fixture(scope="session")
def comeback(league):
    """The demo storyline, events only (fast)."""
    return simulate_match(
        league[0], league[1], seed=7, scenario=PRESETS["comeback"], with_tracking=False, match_id="t-comeback"
    )


@pytest.fixture(scope="session")
def tracked(league):
    """A short-scenario match with full tracking, shared across tests."""
    return simulate_match(league[2], league[5], seed=3, scenario=PRESETS["classic"], match_id="t-tracked")
