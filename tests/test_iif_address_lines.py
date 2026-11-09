"""John's build: a QuickBooks list row's address lines read the way the
company used them — street first or name first, a Canadian postal code in
two words, a country line — not by fixed position."""

from app.services.iif_import import _address, _parse_city_state_zip


def test_street_first_as_alderellas_vendors_are():
    a = _address(
        {
            "NAME": "Oakville Golf Club",
            "ADDR1": "1154 Sixth Line",
            "ADDR2": '"Oakville, ON  L6J 1P5"',
        }
    )
    assert a == {
        "street1": "1154 Sixth Line",
        "street2": None,
        "city": "Oakville",
        "state": "ON",
        "zip": "L6J 1P5",
        "country": "CA",
    }


def test_name_first_is_left_off():
    a = _address(
        {
            "NAME": "American Express",
            "ADDR1": "American Express",
            "ADDR2": "P.O. Box 2000",
            "ADDR3": "West Hill, ON  M1E 5H4",
        }
    )
    assert (a["street1"], a["city"], a["zip"]) == (
        "P.O. Box 2000",
        "West Hill",
        "M1E 5H4",
    )


def test_two_street_lines_and_a_country_line():
    a = _address(
        {
            "NAME": "Receiver General",
            "ADDR1": "Canada Revenue Agency",
            "ADDR2": "275 Pope Road, Suite 103",
            "ADDR3": "Summerside, PE  C1N 6A2",
            "ADDR4": "Canada",
        }
    )
    assert a["street1"] == "Canada Revenue Agency"
    assert a["street2"] == "275 Pope Road, Suite 103"
    assert (a["city"], a["state"], a["zip"], a["country"]) == (
        "Summerside",
        "PE",
        "C1N 6A2",
        "CA",
    )


def test_a_us_address_and_a_postal_code_without_its_space():
    us = _address({"NAME": "X", "ADDR1": "1 Main St", "ADDR2": "Buffalo, NY 14201"})
    assert (us["city"], us["state"], us["zip"], us["country"]) == (
        "Buffalo",
        "NY",
        "14201",
        "US",
    )
    ca = _address({"NAME": "Y", "ADDR1": "Toronto ON m5w5m5"})
    assert (ca["city"], ca["state"], ca["zip"]) == ("Toronto", "ON", "M5W 5M5")


def test_a_line_that_is_not_an_address_stays_a_street_line():
    a = _address({"NAME": "Petro Canada", "ADDR1": "PetroCanada"})
    assert a == {
        "street1": "PetroCanada",
        "street2": None,
        "city": None,
        "state": None,
        "zip": None,
        "country": None,
    }


def test_the_old_city_line_reader_keeps_a_postal_code_whole():
    assert _parse_city_state_zip("Oakville, ON  L6J 1P5") == (
        "Oakville",
        "ON",
        "L6J 1P5",
    )
    assert _parse_city_state_zip("Springfield, IL 62704") == (
        "Springfield",
        "IL",
        "62704",
    )
