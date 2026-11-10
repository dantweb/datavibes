"""Regional city heat maps: nine datasets generated from one region table."""

import importlib.util
import sys
from pathlib import Path

import pytest

from datavibes import DatasetSDK
from datavibes.store.filestore import FileStore

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("make_region_city_maps", ROOT / "scripts" / "make_region_city_maps.py")
generator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = generator  # dataclasses look their module up here
spec.loader.exec_module(generator)


def test_generated_files_are_up_to_date():
    assert generator.main(["--check"]) == 0, "run: python scripts/make_region_city_maps.py"


@pytest.mark.parametrize("region", generator.REGIONS, ids=lambda region: region.slug)
def test_every_region_dataset_validates(region, tmp_path, fixed_clock):
    sdk = DatasetSDK(root=ROOT / "datasets", clock=fixed_clock, store=FileStore(tmp_path),
                     env_file=tmp_path / "none.env", config_file=tmp_path / "none.yaml")
    sdk.validate(generator.slug_of(region))


def test_natural_earth_codes_differ_where_they_should():
    assert generator.map_codes(["SSD", "PSE", "XKX", "ESH", "SOM", "CYP", "FRA"]) == [
        "SDS", "PSX", "KOS", "SAH", "SOM", "SOL", "CYP", "CYN", "FRA"]


def test_europe_stops_russia_at_the_urals_and_others_do_not():
    europe = next(region for region in generator.REGIONS if region.slug == "europe")
    ussr = next(region for region in generator.REGIONS if region.slug == "former-ussr")
    assert 'FILTER(?iso != "RUS" || ?lon <= 60.0)' in generator.render(europe)
    assert "?lon <=" not in generator.render(ussr)


def test_region_query_lists_match_the_requested_regions():
    query = {region.number: set(region.query) for region in generator.REGIONS}
    assert query[1] == {"USA", "CAN", "MEX"}
    assert {"TUR", "EGY", "IRQ", "IRN", "SYR", "JOR", "ISR", "PSE", "SAU", "YEM", "OMN", "ARE"} <= query[3]
    assert {"AFG", "PAK", "IND", "BGD", "NPL", "BTN"} <= query[4]
    assert {"MMR", "THA", "LAO", "KHM", "VNM", "IDN", "MYS", "SGP", "PHL"} <= query[5]
    assert {"CHN", "PRK", "KOR", "JPN", "TWN"} <= query[6]
    assert {"RUS", "UKR", "BLR", "ARM", "AZE", "GEO", "KAZ", "UZB", "TJK", "TKM", "KGZ", "MNG"} <= query[7]
    assert not {"EST", "LVA", "LTU", "JPN"} & query[7]
    assert {"NGA", "ZAF", "EGY", "ETH"} <= query[8] and {"BRA", "ARG", "MEX"} <= query[9]
