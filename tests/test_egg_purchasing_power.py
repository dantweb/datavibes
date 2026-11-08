"""S15 — egg purchasing power: FAOSTAT harmonisation, ``scale``, xlsx + small-multiples writers.

All network is faked: FAOSTAT bulk zips are built in memory, World Bank pages
are recorded-shape JSON. Zero live calls.
"""

import csv
import io
import os
import re
import zipfile
from pathlib import Path

import pytest

from datavibes import DatasetSDK
from datavibes.context import FetchContext
from datavibes.errors import ConfigError
from datavibes.processing.functions import product, scale
from datavibes.processing.steps import DERIVE_FUNCTIONS
from datavibes.registry import SOURCE_REGISTRY, resolve_writer
from datavibes.schema.field import Field, Schema
from datavibes.sources.faostat import (
    ARCHIVE_REBASED, INDEX_EXTENDED, OBSERVED, extend_with_index, harmonise,
    rebase_archive, rebase_factor, rescale_before, rescale_from,
)
from datavibes.sources.ilostat import pick_one_per_year
from datavibes.store.filestore import FileStore
from tests.conftest import FakeResponse

DATASETS = Path(__file__).resolve().parents[1] / "datasets"
GOLDEN = Path(__file__).parent / "golden"
ITEM = "Hen eggs in shell, fresh"
LCU, SLC, PPI = ("Producer Price (LCU/tonne)", "Producer Price (SLC/tonne)",
                 "Producer Price Index (2014-2016 = 100)")


# ------------------------------------------------------------ pure harmonising
def test_rebase_factor_is_slc_over_lcu_of_the_first_shared_year():
    assert rebase_factor({1991: 6000.0, 1992: 5557.0}, {1991: 914.7, 1992: 847.2}) == pytest.approx(914.7 / 6000)
    assert rebase_factor({}, {1991: 1.0}) is None


def test_rebase_archive_converts_only_years_before_the_current_series():
    assert rebase_archive({1989: 5531.0, 1990: 5402.0, 1991: 1.0}, 0.5, before=1991) == {1989: 2765.5, 1990: 2701.0}


def test_rescale_from_fixes_a_switch_that_came_early():
    assert rescale_from({1988: 446400.0, 1989: 116.0}, since=1989, factor=10000) == {1988: 446400.0, 1989: 1160000.0}


def test_harmonise_can_skip_the_index_extension():
    assert harmonise({2002: 1.0}, {2002: 1.0}, {2001: 1.0, 2002: 1.0, 2003: 2.0}, {}, use_index=False) == {
        2002: (1.0, OBSERVED)}


def test_rescale_before_fixes_a_mid_series_currency_switch():
    assert rescale_before({1981: 30718.0, 1982: 46.0}, before=1982, factor=0.001) == {1981: pytest.approx(30.718), 1982: 46.0}


def test_extend_with_index_chains_forward_and_backward_from_the_nearest_anchor():
    observed = {1992: 568.0, 1993: 658.0}
    index = {1991: 50.0, 1992: 50.0, 1993: 70.0, 1994: 140.0}
    assert extend_with_index(observed, index) == {1991: 568.0, 1994: 1316.0}
    assert extend_with_index(observed, {}) == {}


def test_harmonise_tags_every_year_with_its_basis():
    series = harmonise(
        current_lcu={1991: 6000.0}, current_slc={1991: 900.0}, current_index={1991: 10.0, 1992: 20.0},
        archive_lcu={1990: 5400.0, 1991: 9999.0},
    )
    assert series == {1990: (810.0, ARCHIVE_REBASED), 1991: (900.0, OBSERVED), 1992: (1800.0, INDEX_EXTENDED)}
    assert 1990 not in harmonise({1991: 1.0}, {1991: 1.0}, {}, {1990: 5.0}, use_archive=False)


# --------------------------------------------------------------- the source
def _zip(rows, months=True):
    header = ["Area Code", "Area", "Item", "Element", "Year", *(["Months"] if months else []), "Unit", "Value"]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for area, item, element, year, value, *rest in rows:
        month = rest[0] if rest else "Annual value"
        writer.writerow(["1", area, item, element, year, *([month] if months else []), "x", value])
    payload = io.BytesIO()
    name = "Prices_E_All_Data_(Normalized).csv" if months else "PricesArchive_E_All_Data_(Normalized).csv"
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(name, buffer.getvalue().encode("latin-1"))
        archive.writestr("Prices_E_Flags.csv", "Flag\n")
    return payload.getvalue()


def _fao(country, iso_years):
    """Current + archive rows for one FAO area name from ``{year: (lcu, slc, ppi)}``."""
    return [row for year, (lcu, slc, ppi) in iso_years.items() for row in (
        (country, ITEM, LCU, year, lcu), (country, ITEM, SLC, year, slc), (country, ITEM, PPI, year, ppi))
        if row[4] is not None]


CURRENT = _zip(
    _fao("Russian Federation", {1992: (33333.0, 33.3, 1.0), 1993: (None, None, 2.0)})
    + _fao("Mexico", {1991: (2622.0, 2622.0, 10.0)})
    + _fao("China, mainland", {1991: (4152.0, 4152.0, 5.0)})
    + [("China", ITEM, SLC, 1991, 99999.0),                       # aggregate China: not mapped
       ("Mexico", "Hen eggs in shell, fresh", SLC, 1991, 1.0, "January"),  # monthly: ignored
       ("Mexico", "Cow milk, whole, fresh", SLC, 1991, 7.0)]      # other item: ignored
)
ARCHIVE = _zip([
    ("USSR", ITEM, LCU, 1990, 1900.0),
    ("Mexico", ITEM, LCU, 1981, 30718.0),
    ("Mexico", ITEM, LCU, 1990, 2610.0),
    ("China", ITEM, LCU, 1990, 39555.0),
], months=False)
AREAS = {
    "RUS": {"label": "USSR / Russia", "names": ["Russian Federation"], "archive_names": ["USSR"]},
    "MEX": {"label": "Mexico", "names": ["Mexico"]},
    "CHN": {"label": "China", "names": ["China, mainland"], "archive_names": ["China"]},
}


def _fao_responder(url, params, headers):
    if "PricesArchive" in url:
        return FakeResponse(content=ARCHIVE)
    if "Prices_E_All_Data" in url:
        return FakeResponse(content=CURRENT)
    raise AssertionError(f"unexpected url {url}")


def _source(**overrides):
    options = {"item": ITEM, "areas": AREAS,
               "archive_rescale": {"MEX": {"before": 1982, "factor": 0.001}},
               "archive_exclude": {"CHN": "inconsistent units"}}
    options.update(overrides)
    return SOURCE_REGISTRY["faostat-prices"](**options)


def test_source_harmonises_both_bulk_files_per_country(make_session, capsys):
    session = make_session(_fao_responder)
    rows = list(_source().fetch(FetchContext(config=None, clock=None, http=session)))
    by_key = {(row["iso3"], row["year"]): row for row in rows}
    assert by_key[("RUS", 1990)] == {"iso3": "RUS", "country": "USSR / Russia", "year": 1990,
                                    "price_slc_per_tonne": pytest.approx(1.8981, rel=1e-3),
                                    "price_basis": ARCHIVE_REBASED}
    assert by_key[("RUS", 1993)]["price_slc_per_tonne"] == pytest.approx(66.6)
    assert by_key[("RUS", 1993)]["price_basis"] == INDEX_EXTENDED
    assert by_key[("MEX", 1981)]["price_slc_per_tonne"] == pytest.approx(30.718)   # old pesos ÷ 1000
    assert by_key[("MEX", 1991)]["price_slc_per_tonne"] == 2622.0                  # monthly + milk ignored
    assert [row["year"] for row in rows if row["iso3"] == "CHN"] == [1991]          # archive excluded
    assert by_key[("CHN", 1991)]["price_slc_per_tonne"] == 4152.0                  # not the aggregate
    assert "archive series for CHN skipped — inconsistent units" in capsys.readouterr().err
    assert all(call["timeout"] == 120.0 for call in session.calls)


def test_source_rejects_incomplete_configuration():
    with pytest.raises(ConfigError):
        _source(item="")
    with pytest.raises(ConfigError):
        _source(areas={"USA": {"label": "US"}})
    with pytest.raises(ConfigError):
        _source(archive_rescale={"MEX": {"before": 1982}})
    with pytest.raises(ConfigError):
        _source(archive_rescale={"MEX": {"before": 1982, "from": 1990, "factor": 2}})
    with pytest.raises(ConfigError):
        _source(archive_exclude={"MEX": {"reason": "no year"}})


def test_source_can_drop_early_archive_years_and_skip_the_index(make_session, capsys):
    session = make_session(_fao_responder)
    rows = list(_source(archive_exclude={"MEX": {"before": 1990, "reason": "too coarse"}},
                        index_exclude={"RUS": "one anchor"}).fetch(FetchContext(config=None, clock=None, http=session)))
    assert [row["year"] for row in rows if row["iso3"] == "MEX"] == [1990, 1991]
    assert [row["year"] for row in rows if row["iso3"] == "RUS"] == [1990, 1992]   # no 1993 from the index
    err = capsys.readouterr().err
    assert "archive years of MEX before 1990 skipped — too coarse" in err
    assert "no index extension for RUS — one anchor" in err


# ------------------------------------------------------------------ ilostat
ILO_HEADER = '"ref_area","source","indicator","sex","classif1","classif2","time","obs_value"'
ILO_CSV = "\ufeff" + "\n".join([
    ILO_HEADER,
    '"MEX","BA:463","EAR","SEX_T","EDU_AGGREGATE_ADV","CUR_TYPE_USD","1991",16887',
    '"MEX","BA:463","EAR","SEX_T","EDU_AGGREGATE_ADV","CUR_TYPE_LCU","1991",1',      # LCU: ignored by the dataset
    '"MEX","BA:463","EAR","SEX_T","EDU_AGGREGATE_TOTAL","CUR_TYPE_USD","1991",9000',  # other level: ignored
    '"MEX","BB:1","EAR","SEX_T","EDU_AGGREGATE_ADV","CUR_TYPE_USD","1990",99999',     # shorter survey: ignored
    '"RUS","BA:1","EAR","SEX_T","EDU_AGGREGATE_ADV","CUR_TYPE_USD","1990",55',        # before exclude year
    '"RUS","BA:1","EAR","SEX_T","EDU_AGGREGATE_ADV","CUR_TYPE_USD","1992",500',
    '"RUS","BA:1","EAR","SEX_T","EDU_AGGREGATE_ADV","CUR_TYPE_USD","1993",bad',       # unparsable: ignored
])


GEO_CSV = "\n".join([
    ILO_HEADER,
    '"MEX","BA:463","EAR","SEX_T","GEO_COV_URB","CUR_TYPE_USD","1991",11277',
    '"MEX","BA:463","EAR","SEX_T","GEO_COV_NAT","CUR_TYPE_USD","1991",10609',        # national: ignored
])


def _ilo_responder(url, params, headers):
    assert params["sex"] == "SEX_T"
    assert params["ref_area"].startswith("USA+GBR") or params["ref_area"] == "MEX+RUS"
    assert params["id"] in ("EAR_EMTA_SEX_EDU_NB_A", "EAR_EMTA_SEX_EDU_CUR_NB_A", "EAR_EMTA_SEX_GEO_CUR_NB_A")
    return FakeResponse(text=GEO_CSV if "GEO" in params["id"] else ILO_CSV)


def _ilo(**overrides):
    options = {"indicator": "EAR_EMTA_SEX_EDU_NB_A", "ref_areas": ["MEX", "RUS"], "value_column": "earn",
               "filters": {"sex": "SEX_T", "classif1": "EDU_AGGREGATE_ADV"}, "source_column": "survey",
               "exclude_before": {"RUS": {"year": 1991, "reason": "implausible"}}}
    options.update(overrides)
    return SOURCE_REGISTRY["ilostat"](**options)


def test_pick_one_per_year_keeps_one_survey_unless_filling():
    observations = [("A", 2000, 1.0), ("A", 2001, 2.0), ("B", 1999, 9.0), ("B", 2000, 8.0)]
    assert pick_one_per_year(observations) == {2000: (1.0, "A"), 2001: (2.0, "A")}
    assert pick_one_per_year(observations, fill=True) == {1999: (9.0, "B"), 2000: (1.0, "A"), 2001: (2.0, "A")}


def test_ilostat_source_filters_picks_and_excludes(make_session, capsys):
    rows = list(_ilo().fetch(FetchContext(config=None, clock=None, http=make_session(_ilo_responder))))
    assert rows == [{"iso3": "MEX", "year": 1991, "earn": 16887.0, "survey": "BA:463"},
                    {"iso3": "RUS", "year": 1992, "earn": 500.0, "survey": "BA:1"}]
    assert "RUS before 1991 skipped — implausible" in capsys.readouterr().err


def test_ilostat_source_rejects_incomplete_configuration():
    for bad in ({"indicator": ""}, {"ref_areas": []}, {"exclude_before": {"RUS": {}}}):
        with pytest.raises(ConfigError):
            _ilo(**bad)


# ---------------------------------------------------------------- scale helper
def test_product_multiplies_pairwise_and_keeps_nulls():
    assert product([2.0, None, 3.0], [4.0, 1.0, None]) == [8.0, None, None]
    assert DERIVE_FUNCTIONS["product"] is product


def test_scale_multiplies_and_divides_and_keeps_nulls():
    assert scale([1000.0, None], factor=60, divisor=1_000_000) == [0.06, None]
    assert DERIVE_FUNCTIONS["scale"] is scale
    with pytest.raises(ValueError):
        scale([1.0], divisor=0)


# ------------------------------------------------------------------ writers
SCHEMA = Schema([Field(name="country"), Field(name="year", dtype="int"),
                 Field(name="eggs", dtype="float", unit="eggs"), Field(name="basis")])
ROWS = [
    {"country": "A", "year": 2000, "eggs": 100.0, "basis": "observed"},
    {"country": "A", "year": 2001, "eggs": 1000.0, "basis": "index-extended"},
    {"country": "A", "year": 2005, "eggs": 2000.0, "basis": "observed"},   # 2002–2004 gap
    {"country": "B", "year": 2000, "eggs": 10.0, "basis": "observed"},
]


def _svg(**overrides):
    options = {"x": "year", "y": "eggs", "facet": "country", "x_range": [1990, 2010], "y_scale": "log",
               "basis_column": "basis", "estimated": ["index-extended"], "facet_order": ["B", "A"],
               "title": "Eggs", "footer": ["Data: test"], "unit": "eggs"}
    options.update(overrides)
    return resolve_writer("svg-small-multiples", options)


def test_small_multiples_draw_one_panel_per_facet_in_the_declared_order():
    svg = _svg().render(ROWS)
    assert re.findall(r'<g aria-label="(\w)">', svg) == ["B", "A"]
    panel_a = svg.split('<g aria-label="A">')[1]
    assert len(re.findall(r'class="focus estimated"', panel_a)) == 1     # 2000→2001 is estimated
    assert len(re.findall(r'<path class="focus" d=', panel_a)) == 0      # 2001→2005 is a gap, not a line
    assert "<title>A 2001: 1,000 eggs (estimated)</title>" in panel_a
    assert ">2005: 2k<" in panel_a                                        # latest value, labelled
    ticks = re.findall(r'text-anchor="end">(\w+)</text>', panel_a)
    assert ticks == ["10", "100", "1k"]                                   # log decades within 10…2000
    assert ">1990<" in panel_a and ">2010<" in panel_a                    # pinned x range


def test_small_multiples_golden(tmp_path):
    dest = _svg().write(ROWS, SCHEMA, tmp_path / "chart.svg")
    assert dest.suffix == ".svg" and _svg().extension == "svg"
    _assert_golden(dest, "small_multiples.svg")


def test_small_multiples_reference_line_and_empty_panels():
    rows = [dict(row, ref=row["eggs"] / 2) for row in ROWS]
    svg = _svg(reference_y="ref", reference_label="everyone", show_empty=True, empty_note="no data",
               facet_order=["C", "B", "A"]).render(rows)
    assert re.findall(r'<g aria-label="(\w)">', svg) == ["C", "B", "A"]
    panel_c = svg.split('<g aria-label="C">')[1].split("</g>")[0]
    assert ">no data</text>" in panel_c and 'class="focus' not in panel_c
    assert svg.split('<g aria-label="A">')[1].count('class="reference"') == 1
    assert ">everyone</text>" in svg                                       # legend entry
    assert ">5</text>" not in svg and ">1</text>" not in svg                # domain: 5…2000 → ticks 10…1k


@pytest.mark.parametrize("bad", [{"y_scale": "sqrt"}, {"x_range": [2010, 1990]}, {"facet": ""}])
def test_small_multiples_reject_bad_options(bad):
    with pytest.raises(ConfigError):
        _svg(**bad)


def test_xlsx_writes_data_pivots_chart_and_about(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    writer = resolve_writer("xlsx", {
        "title": "Eggs", "attribution": "Data: test", "notes": ["a note"],
        "pivots": [{"sheet": "eggs", "index": "year", "columns": "country", "values": "eggs",
                    "order": ["B", "A"], "index_range": [1999, 2005],
                    "chart": {"title": "Eggs", "x_range": [1999, 2005], "log_y": True}}],
    })
    workbook = openpyxl.load_workbook(writer.write(ROWS, SCHEMA, tmp_path / "out.xlsx"))
    assert workbook.sheetnames == ["data", "eggs", "About"]
    assert [cell.value for cell in workbook["data"][1]] == ["country", "year", "eggs", "basis"]
    pivot = [[cell.value for cell in row] for row in workbook["eggs"].iter_rows()]
    assert pivot[0] == ["year", "B", "A"]
    assert pivot[1] == [1999, None, None]                    # index_range adds empty years
    assert pivot[2] == [2000, 10, 100]
    assert [row[0] for row in pivot[1:]] == list(range(1999, 2006))
    assert len(workbook["eggs"]._charts) == 1
    about = [[cell.value for cell in row][:2] for row in workbook["About"].iter_rows()]
    assert ["Note", "a note"] in about and ["eggs", "float"] in about


def test_xlsx_pivot_needs_its_keys():
    with pytest.raises(ConfigError):
        resolve_writer("xlsx", {"pivots": [{"sheet": "x", "index": "year"}]})


# ---------------------------------------------------------------- end to end
GNI = "NY.GNP.PCAP.CN"


def _wb(iso3, name, year, value, indicator=GNI):
    return {"indicator": {"id": indicator, "value": "x"}, "country": {"id": iso3[:2], "value": name},
            "countryiso3code": iso3, "date": str(year), "value": value, "obs_status": "", "decimal": 0}


WB_PAGE = [_wb("RUS", "Russian Federation", 1990, 4.345), _wb("RUS", "Russian Federation", 1992, 126.7),
           _wb("MEX", "Mexico", 1981, 90.27), _wb("MEX", "Mexico", 1991, 10890.0),
           _wb("CHN", "China", 1991, 1922.0), _wb("DEU", "Germany", 1991, 19950.0),  # no price → dropped
           _wb("AFG", "Afghanistan", 1991, 1.0)]                                     # not a target


RATES = [_wb("MEX", "Mexico", 1991, 2.0, "PA.NUS.FCRF"), _wb("RUS", "Russian Federation", 1990, 0.5, "PA.NUS.FCRF"),
         _wb("RUS", "Russian Federation", 1992, 0.25, "PA.NUS.FCRF")]


def _bis_zip(rows):
    """A BIS flat-CSV bulk zip: headers 'CODE:Label', cells 'code: label'."""
    columns = ["FREQ", "REF_AREA", "VALUE", "UNIT_MEASURE", "COVERED_AREA", "RE_TYPE", "RE_VINTAGE",
               "PRICED_UNIT", "TIME_PERIOD", "OBS_VALUE"]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([f"{column}:{column.title()}" for column in columns])
    for row in rows:
        writer.writerow([row.get(column, "") if column in ("TIME_PERIOD", "OBS_VALUE")
                         else (f"{row[column]}: label" if column in row else "") for column in columns])
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("WS_X_csv_flat.csv", buffer.getvalue())
    return payload.getvalue()


SPP = _bis_zip([
    {"FREQ": "Q", "REF_AREA": "MX", "VALUE": "N", "UNIT_MEASURE": "628", "TIME_PERIOD": "1991-Q1", "OBS_VALUE": "50"},
    {"FREQ": "Q", "REF_AREA": "MX", "VALUE": "N", "UNIT_MEASURE": "628", "TIME_PERIOD": "2025-Q1", "OBS_VALUE": "100"},
    {"FREQ": "Q", "REF_AREA": "MX", "VALUE": "N", "UNIT_MEASURE": "628", "TIME_PERIOD": "2025-Q2", "OBS_VALUE": "200"},
    {"FREQ": "Q", "REF_AREA": "MX", "VALUE": "R", "UNIT_MEASURE": "628", "TIME_PERIOD": "1991-Q1", "OBS_VALUE": "9"},   # real: ignored
    {"FREQ": "Q", "REF_AREA": "MX", "VALUE": "N", "UNIT_MEASURE": "628", "TIME_PERIOD": "1992-Q1", "OBS_VALUE": "NaN"},
])
DPP = _bis_zip([
    {"FREQ": "Q", "REF_AREA": "RU", "COVERED_AREA": "9", "RE_TYPE": "1", "RE_VINTAGE": "2", "PRICED_UNIT": "1",
     "TIME_PERIOD": "1992-Q1", "OBS_VALUE": "100"},
    {"FREQ": "A", "REF_AREA": "NO", "COVERED_AREA": "0", "RE_TYPE": "1", "RE_VINTAGE": "0", "PRICED_UNIT": "1",
     "TIME_PERIOD": "1990", "OBS_VALUE": "7.5"},
])


def _pinksheet_xlsx():
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Annual Prices (Nominal)"
    for row in (["World Bank Commodity Price Data (The Pink Sheet)"], [], [None, "Crude oil, average", "Silver"],
                [None, "($/bbl)", "($/troy oz)"], [1981, 35.0, 10.5], [1991, 20.0, 4.0], [1992, 19.0, "…"]):
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


PINK_LINK = "https://thedocs.worldbank.org/en/doc/abc-0050012026/related/CMO-Historical-Data-Annual.xlsx"
GNI_USD = [_wb("MEX", "Mexico", 1991, 3000.0, "NY.GNP.PCAP.CD")]


CPI_MEX = [_wb("MEX", "Mexico", year, 50.0 + (year - 1991) * 50.0 / 34, "FP.CPI.TOTL") for year in range(1991, 2026)]
BLS_BODY = {"status": "REQUEST_SUCCEEDED", "Results": {"series": [{"seriesID": "CUUR0000SETA01", "data": [
    {"year": "1991", "period": "M01", "value": "100.0"}, {"year": "1991", "period": "M02", "value": "102.0"},
    {"year": "1991", "period": "M13", "value": "999"}]}]}}
EUROSTAT_CUBE = {"id": ["geo", "time"], "size": [1, 1], "value": {"0": 100.0},
                 "dimension": {"geo": {"category": {"index": {"UK": 0}, "label": {"UK": "United Kingdom"}}},
                               "time": {"category": {"index": {"1991": 0}, "label": {"1991": "1991"}}}}}


def _dataset_responder(url, params, headers):
    if "api.bls.gov" in url:
        return FakeResponse(json_body=BLS_BODY)
    if "ec.europa.eu/eurostat" in url:
        return FakeResponse(json_body=EUROSTAT_CUBE)
    if "api.worldbank.org" in url and "FP.CPI.TOTL" in url:
        return FakeResponse(json_body=[{"page": 1, "pages": 1}, CPI_MEX])
    if url.endswith("commodity-markets"):
        return FakeResponse(text=f'<a href="{PINK_LINK}">Annual prices</a>')
    if url == PINK_LINK:
        return FakeResponse(content=_pinksheet_xlsx())
    if "api.worldbank.org" in url and "NY.GNP.PCAP.CD" in url:
        return FakeResponse(json_body=[{"page": 1, "pages": 1}, GNI_USD])
    if "data.bis.org" in url:
        return FakeResponse(content=SPP if "WS_SPP" in url else DPP)
    if "rplumber.ilo.org" in url:
        return _ilo_responder(url, params, headers)
    if "api.worldbank.org" in url and "PA.NUS.FCRF" in url:
        return FakeResponse(json_body=[{"page": 1, "pages": 1}, RATES])
    if "api.worldbank.org" in url:
        return FakeResponse(json_body=[{"page": 1, "pages": 1}, WB_PAGE])
    return _fao_responder(url, params, headers)


def _sdk(tmp_path, fixed_clock, name):
    return DatasetSDK(root=DATASETS, clock=fixed_clock, store=FileStore(tmp_path / name),
                      env_file=tmp_path / "none.env", config_file=tmp_path / "none.yaml")


def _assert_golden(path: Path, name: str):
    golden = GOLDEN / name
    if os.environ.get("UPDATE_GOLDEN") == "1":
        golden.write_bytes(path.read_bytes())
    assert path.read_bytes() == golden.read_bytes(), f"{name} drifted (UPDATE_GOLDEN=1 to accept)"


def test_dataset_validates(tmp_path, fixed_clock):
    _sdk(tmp_path, fixed_clock, "v").validate("egg-purchasing-power")


def test_dataset_end_to_end(tmp_path, fixed_clock, make_session, monkeypatch):
    pytest.importorskip("openpyxl")
    monkeypatch.setattr("datavibes.sources.worldbank.time.sleep", lambda seconds: None)
    paths = _sdk(tmp_path, fixed_clock, "e").run_outputs("egg-purchasing-power", http=make_session(_dataset_responder))
    assert [path.name for path in paths] == ["2026-06-01-00-00.csv", "2026-06-01-00-00.xlsx",
                                             "2026-06-01-00-00.svg", "2026-06-01-00-00.graduates.svg",
                                             "2026-06-01-00-00.urban.svg", "2026-06-01-00-00.house.svg",
                                             "2026-06-01-00-00.silver.svg", "2026-06-01-00-00.silver-lbs.svg",
                                             "2026-06-01-00-00.car.svg"]
    _assert_golden(paths[0], "egg_purchasing_power.csv")
    rows = list(csv.DictReader(paths[0].open(encoding="utf-8")))
    by_key = {(row["iso3"], row["year"]): row for row in rows}
    assert set(by_key) == {("RUS", "1990"), ("RUS", "1992"), ("MEX", "1981"), ("MEX", "1991"), ("CHN", "1991")}
    assert by_key[("RUS", "1990")]["country"] == "USSR / Russia"
    # 4.345 rubles ÷ (1.8981 rubles/tonne × 60 g ÷ 10⁶) ≈ 38 152 eggs a year
    assert float(by_key[("RUS", "1990")]["eggs_per_year"]) == pytest.approx(38152, rel=1e-3)
    assert float(by_key[("MEX", "1991")]["eggs_per_month"]) == pytest.approx(10890 / (2622 * 6e-5) / 12, abs=1)
    svg = paths[2].read_text(encoding="utf-8")
    assert re.findall(r'<g aria-label="([^"]+)">', svg) == ["USSR / Russia", "China", "Mexico"]
    # graduates: 16 887 USD × 2 MXN/USD ÷ (2622 MXN/t × 60 g ÷ 10⁶) eggs a month; LCU row ignored
    assert float(by_key[("MEX", "1991")]["graduate_earnings_lcu_month"]) == 33774.0
    assert float(by_key[("MEX", "1991")]["eggs_per_month_graduate"]) == pytest.approx(16887 * 2 / (2622 * 6e-5), abs=1)
    assert by_key[("RUS", "1992")]["graduate_earnings_survey"] == "BA:1"
    assert float(by_key[("RUS", "1990")]["eggs_per_month_graduate"]) == pytest.approx(55 * 0.5 / (1.8981 * 6e-5), rel=1e-3)
    graduates = paths[3].read_text(encoding="utf-8")
    assert len(re.findall(r'<g aria-label=', graduates)) == 20                    # every country, data or not
    assert "no ILOSTAT earnings by education" in graduates
    # urban employees: 11 277 MXN a month, national figure ignored
    assert float(by_key[("MEX", "1991")]["eggs_per_month_urban"]) == pytest.approx(11277 * 2 / (2622 * 6e-5), abs=1)
    assert by_key[("RUS", "1992")]["eggs_per_month_urban"] == ""
    urban = paths[4].read_text(encoding="utf-8")
    assert "no ILOSTAT urban earnings" in urban and "city worker" in urban
    # home: Mexico's 2025 anchor (31 397 MXN/m²) chained back to 1991 with the index (50 vs 150)
    assert by_key[("MEX", "1991")]["house_price_basis"] == "index-chained"
    assert float(by_key[("MEX", "1991")]["house_price_lcu_m2"]) == pytest.approx(31397 * 50 / 150)
    assert float(by_key[("MEX", "1991")]["eggs_per_house"]) == pytest.approx(31397 * 50 / 150 * 100 / (2622 * 6e-5), abs=1)
    # Russia 1992: an observed BIS level
    assert by_key[("RUS", "1992")]["house_price_basis"] == "observed"
    assert float(by_key[("RUS", "1992")]["eggs_per_house"]) == pytest.approx(100 * 100 / (33.3 * 6e-5), abs=1)
    assert by_key[("CHN", "1991")]["eggs_per_house"] == ""                       # no index for 1991
    house = paths[5].read_text(encoding="utf-8")
    assert "new 100 m² home" in house and "no national price level" in house
    # sterling silver: 3000 USD ÷ 12 ÷ (4.0 USD/oz × 0.925 ÷ 31.1034768 g/oz) ≈ 2 102 g a month
    assert float(by_key[("MEX", "1991")]["silver_usd_per_troy_oz"]) == 4.0
    assert float(by_key[("MEX", "1991")]["sterling_grams_per_month"]) == pytest.approx(3000 / 12 / (4.0 * 0.925 / 31.1034768), abs=1)
    assert by_key[("MEX", "1981")]["sterling_grams_per_month"] == ""          # no USD income in the fixture
    assert by_key[("RUS", "1990")]["country"] == "USSR / Russia"              # map step labels every row
    assert "sterling silver" in paths[6].read_text(encoding="utf-8")
    # car: Mexico's 2025 anchor (MXN 421 100) chained year by year with the CPI (index 50 in 1991, 100 in 2025)
    assert by_key[("MEX", "1991")]["car_price_basis"] == "CPI-chained"
    assert float(by_key[("MEX", "1991")]["car_price_lcu"]) == pytest.approx(421100 * 50 / 100)
    assert float(by_key[("MEX", "1991")]["eggs_per_car"]) == pytest.approx(421100 * 0.5 / (2622 * 6e-5), abs=1)
    assert "middle-class car" in paths[-1].read_text(encoding="utf-8")
    grams = 3000 / 12 / (4.0 * 0.925 / 31.1034768)
    assert float(by_key[("MEX", "1991")]["sterling_lbs_per_year"]) == pytest.approx(grams * 12 / 453.59237, abs=0.05)
    assert "pounds of sterling silver" in paths[7].read_text(encoding="utf-8")


def test_egg_weight_is_a_parameter(tmp_path, fixed_clock, make_session, monkeypatch):
    pytest.importorskip("openpyxl")
    monkeypatch.setattr("datavibes.sources.worldbank.time.sleep", lambda seconds: None)
    monkeypatch.setenv("EGG_WEIGHT_GRAMS", "50")
    paths = _sdk(tmp_path, fixed_clock, "w").run_outputs("egg-purchasing-power", http=make_session(_dataset_responder))
    rows = {row["iso3"] + row["year"]: row for row in csv.DictReader(paths[0].open(encoding="utf-8"))}
    assert float(rows["MEX1991"]["price_per_egg_lcu"]) == pytest.approx(2622 * 50e-6)


def test_one_writer_twice_needs_distinct_suffixes(tmp_path):
    from datavibes.config.models import DatasetConfig, DatasetMetadata, OutputSpec, SourceSpec

    def config(*outputs):
        return DatasetConfig(metadata=DatasetMetadata(slug="d", title="D", category="c"),
                             schema=SCHEMA, sources=[SourceSpec(type="static")], outputs=list(outputs))

    config(OutputSpec(name="csv"), OutputSpec(name="csv", suffix="copy"))
    with pytest.raises(ConfigError):
        config(OutputSpec(name="csv"), OutputSpec(name="csv"))
    with pytest.raises(ConfigError):
        OutputSpec(name="csv", suffix="Bad Suffix")


def test_small_multiples_wrap_long_footer_lines():
    svg = _svg(columns=1, footer=["word " * 200]).render(ROWS)
    footer_lines = re.findall(r'font-size="11">(word[^<]*)</text>', svg)
    assert len(footer_lines) > 1 and all(len(line) <= (280 + 48) / 6 for line in footer_lines)


def test_small_multiples_mark_isolated_years_with_a_dot():
    rows = [{"country": "A", "year": y, "eggs": 100.0, "basis": "observed"} for y in (1995, 2000, 2001, 2008)]
    panel = _svg().render(rows).split('<g aria-label="A">')[1]
    assert len(re.findall(r'<circle class="dot"[^>]*r="2.5"', panel)) == 1    # 1995 alone; 2008 is the last dot
    assert len(re.findall(r'<circle class="dot"[^>]*r="3"', panel)) == 1


# --------------------------------------------------------------- BIS + chaining
def test_annual_means_average_quarters_and_months():
    from datavibes.sources.bis import annual_means

    assert annual_means([("2024-Q1", 1.0), ("2024-Q2", 3.0), ("2025-07", 5.0), ("2026", 7.0)]) == {
        2024: 2.0, 2025: 5.0, 2026: 7.0}


def test_bis_series_source_filters_by_code_annualises_and_scales(make_session):
    session = make_session(lambda url, params, headers: FakeResponse(content=DPP))
    source = SOURCE_REGISTRY["bis-series"](
        dataflow="WS_DPP", value_column="level", basis_column="basis",
        series={"RUS": {"REF_AREA": "RU", "COVERED_AREA": "9", "RE_VINTAGE": "2"},
                "NOR": {"REF_AREA": "NO", "FREQ": "A", "multiplier": 1000},
                "FRA": {"REF_AREA": "FR"}})
    rows = list(source.fetch(FetchContext(config=None, clock=None, http=session)))
    assert rows == [{"iso3": "RUS", "year": 1992, "level": 100.0, "basis": "observed"},
                    {"iso3": "NOR", "year": 1990, "level": 7500.0, "basis": "observed"}]
    assert session.calls[0]["url"] == "https://data.bis.org/static/bulk/WS_DPP_csv_flat.zip"


def test_bis_series_source_rejects_incomplete_configuration():
    with pytest.raises(ConfigError):
        SOURCE_REGISTRY["bis-series"](dataflow="WS_SPP", value_column="x", series={})
    with pytest.raises(ConfigError):
        SOURCE_REGISTRY["bis-series"](dataflow="WS_SPP", value_column="x", series={"USA": {"FREQ": "Q"}})


def test_chain_index_fills_levels_from_the_nearest_anchor_per_group():
    from datavibes.registry import STEP_REGISTRY

    step = STEP_REGISTRY["chain_index"](column="level", index="idx", by=["iso3"], basis_column="basis")
    rows = [{"iso3": "A", "year": 2000, "idx": 50.0, "level": None, "basis": None},
            {"iso3": "A", "year": 2010, "idx": 100.0, "level": 1000.0, "basis": "anchor"},
            {"iso3": "A", "year": 2011, "idx": None, "level": None, "basis": None},
            {"iso3": "B", "year": 2000, "idx": 70.0, "level": None, "basis": None}]   # no level at all
    out = step.apply(rows, None)
    assert [(row["level"], row["basis"]) for row in out] == [
        (500.0, "index-chained"), (1000.0, "anchor"), (None, None), (None, None)]
    with pytest.raises(ConfigError):
        STEP_REGISTRY["chain_index"](column="level")


# ---------------------------------------------------------- Pink Sheet + steps
def test_parse_annual_sheet_reads_years_and_blanks():
    from datavibes.sources.worldbank_pinksheet import parse_annual_sheet

    rows = [("title",), (None, "Gold", "Silver"), (None, "($/oz)", "($/oz)"),
            (1960, 35.3, 0.9), ("1961", 35.4, "…"), ("note", 1, 2)]
    assert parse_annual_sheet(rows, {"Silver": "silver"}) == [{"year": 1960, "silver": 0.9},
                                                              {"year": 1961, "silver": None}]
    with pytest.raises(Exception):
        parse_annual_sheet(rows, {"Platinum": "pt"})


def test_pinksheet_source_follows_the_current_link(make_session):
    session = make_session(_dataset_responder)
    rows = SOURCE_REGISTRY["worldbank-pinksheet"](commodities={"Silver": "silver"}).fetch(
        FetchContext(config=None, clock=None, http=session))
    assert rows == [{"year": 1981, "silver": 10.5}, {"year": 1991, "silver": 4.0}, {"year": 1992, "silver": None}]
    assert [call["url"] for call in session.calls][-1] == PINK_LINK


def test_map_step_labels_rows_by_key():
    from datavibes.registry import STEP_REGISTRY

    rows = [{"iso3": "RUS", "country": "Russian Federation"}, {"iso3": "XXX", "country": "Keep"}]
    out = STEP_REGISTRY["map"](column="country", key="iso3", mapping={"RUS": "USSR / Russia"}).apply(rows, None)
    assert [row["country"] for row in out] == ["USSR / Russia", "Keep"]
    with pytest.raises(ConfigError):
        STEP_REGISTRY["map"](column="country", key="iso3", mapping={})


def test_lookup_matches_keys_regardless_of_type():
    from datavibes.registry import STEP_REGISTRY

    rows = [{"_source": "worldbank-pinksheet#3", "year": 1991, "silver": 4.0},
            {"_source": "worldbank-indicator#0", "year": "1991", "iso3": "MEX"}]
    out = STEP_REGISTRY["lookup"](from_source="worldbank-pinksheet", on="year",
                                  columns={"silver": "silver"}).apply(rows, None)
    assert out == [{"_source": "worldbank-indicator#0", "year": "1991", "iso3": "MEX", "silver": 4.0}]


# ------------------------------------------------------------- BLS + splicing
def test_year_windows_cover_the_range_in_tens():
    from datavibes.sources.bls import year_windows

    assert year_windows(1953, 1975) == [(1953, 1962), (1963, 1972), (1973, 1975)]


def test_bls_source_posts_windows_and_averages_months(make_session, fixed_clock):
    session = make_session(lambda url, body, headers: FakeResponse(json_body=BLS_BODY))
    rows = SOURCE_REGISTRY["bls-series"](series={"USA": "CUUR0000SETA01"}, value_column="cars",
                                         start_year=1991, end_year=2005).fetch(
        FetchContext(config=None, clock=fixed_clock, http=session))
    assert rows == [{"iso3": "USA", "year": 1991, "cars": 101.0}]          # M13 ignored
    assert [call["json"]["startyear"] for call in session.calls] == ["1991", "2001"]


def test_bls_source_reports_api_refusals(make_session, fixed_clock):
    from datavibes.errors import SourceFetchError

    session = make_session(lambda url, body, headers: FakeResponse(
        json_body={"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold"]}))
    with pytest.raises(SourceFetchError):
        SOURCE_REGISTRY["bls-series"](series={"USA": "X"}, value_column="v", start_year=2020,
                                      end_year=2021).fetch(FetchContext(config=None, clock=fixed_clock, http=session))


def test_chain_index_splices_indices_year_by_year():
    from datavibes.registry import STEP_REGISTRY

    step = STEP_REGISTRY["chain_index"](column="price", index=["car", "cpi"], by=["iso3"],
                                        basis_column="basis", chained_label=["car-chained", "cpi-chained"])
    # The car index stops in 2020; the anchor is 2022: CPI bridges 2022→2020, then the car index takes over.
    rows = [{"iso3": "GBR", "year": year, "car": car, "cpi": cpi, "price": None, "basis": None}
            for year, car, cpi in ((2018, 90.0, 80.0), (2019, 95.0, 90.0), (2020, 100.0, 100.0),
                                   (2021, None, 110.0), (2022, None, 121.0))]
    rows[-1].update(price=1210.0, basis="anchor")
    out = {row["year"]: (round(row["price"], 6), row["basis"]) for row in step.apply(rows, None)}
    assert out == {2018: (900.0, "car-chained"), 2019: (950.0, "car-chained"), 2020: (1000.0, "cpi-chained"),
                   2021: (1100.0, "cpi-chained"), 2022: (1210.0, "anchor")}
    with pytest.raises(ConfigError):
        STEP_REGISTRY["chain_index"](column="price", index=["a", "b"], chained_label=["x", "y", "z"])
