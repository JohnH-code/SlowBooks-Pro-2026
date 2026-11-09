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


# Customers: QuickBooks keeps the bill-to in BADDR1-5 and the ship-to in
# SADDR1-5, written every which way (Alderella's own customers below).


def _b(name, *lines):
    row = {"NAME": name}
    row.update({f"BADDR{i}": ln for i, ln in enumerate(lines, 1)})
    return _address(row, "BADDR")


def test_a_province_spelled_out_with_a_comma_before_the_postal_code():
    a = _b(
        "Agazi Kahsay",
        "Agazi Kahsay",
        "9100 Jane St, Bld L, Suite 77",
        "Vaughan, Ontario, L4K 0A4",
    )
    assert (a["street1"], a["city"], a["state"], a["zip"], a["country"]) == (
        "9100 Jane St, Bld L, Suite 77",
        "Vaughan",
        "ON",
        "L4K 0A4",
        "CA",
    )
    a = _b(
        "Stoneman, Carl",
        "Stoneman, Carl",
        "89 Rushingbrook Drive",
        "Richmond Hill Ontario L4S2A3",
    )
    assert (a["city"], a["state"], a["zip"]) == ("Richmond Hill", "ON", "L4S 2A3")
    a = _b("No16", "No16", "100 Sheppard Ave W", "Toronto ON M2N 1M6")
    assert (a["city"], a["state"], a["zip"]) == ("Toronto", "ON", "M2N 1M6")


def test_a_us_state_spelled_out_and_an_attention_after_the_city():
    a = _b(
        "Cellino and Barnes Law",
        "Cellino and Barnes Law",
        "350 Main St, 2500 Main Place Tower",
        "Buffalo, New York 14202",
        "Attn: Gregory Pajak",
    )
    assert a == {
        "street1": "350 Main St, 2500 Main Place Tower",
        "street2": "Attn: Gregory Pajak",
        "city": "Buffalo",
        "state": "NY",
        "zip": "14202",
        "country": "US",
    }


def test_the_name_in_full_or_with_someone_to_attend_is_the_name():
    a = _b(
        "Dunlop Developments (Barrie) I",
        "Dunlop Developments (Barrie) Inc.",
        "9100 Jane St, Suite 77, Bld L",
        "Vaughan, ON  L4K 0A4",
    )
    assert (a["street1"], a["street2"]) == ("9100 Jane St, Suite 77, Bld L", None)
    a = _b(
        "Eshel Law Firm",
        "Eshel Law Firm - Selvi Pavelendram",
        "7481 Woodbine Ave, Suite 202",
        "Markham, ON  L3R 2W1",
    )
    assert (a["street1"], a["street2"]) == (
        "7481 Woodbine Ave, Suite 202",
        "Attn: Selvi Pavelendram",
    )
    a = _b(
        "Salehi Law",
        "Salehi Law Attn Tara Dharmarajan",
        "500 King St W, Suite 300",
        "Toronto, Ontario, M5V 1L9",
    )
    assert a["street2"] == "Attn: Tara Dharmarajan"
    # only the name, or the name and an attention: no address to speak of
    assert not any(_b("VRBO", "VRBO").values())
    assert _b("Affinity Law", "Affinity Law", "Attn:  Shahzed Ayub")["street1"] == (
        "Attn:  Shahzed Ayub"
    )


def test_another_country_and_its_postal_code_on_a_line_of_its_own():
    a = _b(
        "STS Capital Partners Inc",
        "STS Capital Partners Inc.",
        "Cedar Court, Ground Floor",
        "Wildey Business Park",
        "Wildey, St Michael, Barbados",
        "BB14006",
    )
    assert a == {
        "street1": "Cedar Court, Ground Floor",
        "street2": "Wildey Business Park",
        "city": "Wildey",
        "state": "St Michael",
        "zip": "BB14006",
        "country": "BB",
    }


def test_customers_take_the_bill_to_and_the_ship_to():
    from app.services.iif_import import _customer_fields

    f = _customer_fields(
        {
            "NAME": "Coppinwood Golf Club",
            "BADDR1": "Coppinwood Golf Club",
            "BADDR2": "2324 Concession 4",
            "BADDR3": "Claremont, ON  L0C 1A0",
            "SADDR1": "Coppinwood Golf Club",
            "SADDR2": "1 Clubhouse Rd",
            "SADDR3": "Claremont, ON  L0C 1A0",
        }
    )
    assert (f["bill_address1"], f["bill_city"], f["bill_zip"], f["bill_country"]) == (
        "2324 Concession 4",
        "Claremont",
        "L0C 1A0",
        "CA",
    )
    assert (f["ship_address1"], f["ship_city"], f["ship_country"]) == (
        "1 Clubhouse Rd",
        "Claremont",
        "CA",
    )
    # an older file's ADDR lines are still the bill-to
    f = _customer_fields(
        {"NAME": "X", "ADDR1": "1 Main St", "ADDR2": "Oakville, ON  L6J 1P5"}
    )
    assert (f["bill_address1"], f["bill_city"]) == ("1 Main St", "Oakville")
    assert "ship_address1" not in f
