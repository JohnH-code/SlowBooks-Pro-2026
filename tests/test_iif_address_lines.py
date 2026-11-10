"""A QuickBooks Desktop list row's address lines are read by what they say,
not by their position.

QuickBooks keeps up to five free address lines on a vendor (ADDR1-5) and a
customer's bill-to and ship-to (BADDR1-5, SADDR1-5), and companies fill them
in every which way: name first or street first, the city line on line 2 or
line 4, an "Attn:" line after it, a country line, a postal code on a line of
its own. Read by position, a street-first vendor's street became its
company, its city line its street, and a two-word postal code ("K1A 0B1")
was split. Every name and address below is made up."""

from app.services.iif_import import (
    _address,
    _customer_fields,
    _parse_city_state_zip,
)


def test_street_first():
    a = _address(
        {
            "NAME": "Lakeside Golf Club",
            "ADDR1": "1200 Lakeshore Road",
            "ADDR2": '"Springfield, IL  62704"',
        }
    )
    assert a == {
        "street1": "1200 Lakeshore Road",
        "street2": None,
        "city": "Springfield",
        "state": "IL",
        "zip": "62704",
        "country": "US",
    }


def test_name_first_is_left_off():
    a = _address(
        {
            "NAME": "Acme Supply",
            "ADDR1": "Acme Supply",
            "ADDR2": "P.O. Box 2000",
            "ADDR3": "Dayton, OH 45401-2000",
        }
    )
    assert (a["street1"], a["city"], a["state"], a["zip"]) == (
        "P.O. Box 2000",
        "Dayton",
        "OH",
        "45401-2000",
    )


def test_two_street_lines_and_a_country_line():
    a = _address(
        {
            "NAME": "Northwind Traders",
            "ADDR1": "Accounts Payable",
            "ADDR2": "275 Pine Road, Suite 103",
            "ADDR3": "Halifax, NS  B3H 0A1",
            "ADDR4": "Canada",
        }
    )
    assert a["street1"] == "Accounts Payable"
    assert a["street2"] == "275 Pine Road, Suite 103"
    assert (a["city"], a["state"], a["zip"], a["country"]) == (
        "Halifax",
        "NS",
        "B3H 0A1",
        "CA",
    )


def test_a_postal_code_without_its_space():
    ca = _address({"NAME": "Y", "ADDR1": "Ottawa ON k1a0b1"})
    assert (ca["city"], ca["state"], ca["zip"]) == ("Ottawa", "ON", "K1A 0B1")


def test_a_line_that_is_not_an_address_stays_a_street_line():
    a = _address({"NAME": "Corner Gas", "ADDR1": "CornerGas"})
    assert a == {
        "street1": "CornerGas",
        "street2": None,
        "city": None,
        "state": None,
        "zip": None,
        "country": None,
    }


def test_the_city_line_reader_keeps_a_postal_code_whole():
    assert _parse_city_state_zip("Springfield, IL 62704") == (
        "Springfield",
        "IL",
        "62704",
    )
    assert _parse_city_state_zip("Ottawa, ON  K1A 0B1") == ("Ottawa", "ON", "K1A 0B1")


def _b(name, *lines):
    row = {"NAME": name}
    row.update({f"BADDR{i}": ln for i, ln in enumerate(lines, 1)})
    return _address(row, "BADDR")


def test_a_state_or_province_spelled_out():
    a = _b(
        "Pat Morgan",
        "Pat Morgan",
        "9100 Elm St, Bldg L, Suite 77",
        "Albany, New York, 12207",
    )
    assert (a["street1"], a["city"], a["state"], a["zip"], a["country"]) == (
        "9100 Elm St, Bldg L, Suite 77",
        "Albany",
        "NY",
        "12207",
        "US",
    )
    a = _b("Chris Lee", "Chris Lee", "89 Brook Drive", "Richmond Hill Ontario L4S2A3")
    assert (a["city"], a["state"], a["zip"]) == ("Richmond Hill", "ON", "L4S 2A3")
    a = _b("Bay Diner", "Bay Diner", "100 Bay St", "Tampa FL 33602")
    assert (a["city"], a["state"], a["zip"]) == ("Tampa", "FL", "33602")


def test_an_attention_line_after_the_city_line():
    a = _b(
        "Harbor Law Group",
        "Harbor Law Group",
        "350 Main St, 25th Floor",
        "Buffalo, New York 14202",
        "Attn: Dana Fox",
    )
    assert a == {
        "street1": "350 Main St, 25th Floor",
        "street2": "Attn: Dana Fox",
        "city": "Buffalo",
        "state": "NY",
        "zip": "14202",
        "country": "US",
    }


def test_the_name_in_full_or_with_someone_to_attend_is_the_name():
    # the list name cut short ("... Holdings I"), the address line in full
    a = _b(
        "Riverbend Development Holdings I",
        "Riverbend Development Holdings Inc.",
        "500 River Rd, Suite 7",
        "Austin, TX  78701",
    )
    assert (a["street1"], a["street2"]) == ("500 River Rd, Suite 7", None)
    a = _b(
        "Stone Law Firm",
        "Stone Law Firm - Jordan Reyes",
        "7481 Oak Ave, Suite 202",
        "Denver, CO  80202",
    )
    assert (a["street1"], a["street2"]) == (
        "7481 Oak Ave, Suite 202",
        "Attn: Jordan Reyes",
    )
    a = _b(
        "Quill Legal",
        "Quill Legal Attn Sam Patel",
        "500 King St W, Suite 300",
        "Seattle, Washington, 98101",
    )
    assert a["street2"] == "Attn: Sam Patel"
    # only the name, or the name and an attention: no address to speak of
    assert not any(_b("Rentals", "Rentals").values())
    assert _b("Birch Law", "Birch Law", "Attn:  Kim Wu")["street1"] == "Attn:  Kim Wu"


def test_another_country_and_its_postal_code_on_a_line_of_its_own():
    a = _b(
        "Coral Partners Inc",
        "Coral Partners Inc.",
        "Cedar Court, Ground Floor",
        "Harbour Business Park",
        "Wildey, St Michael, Barbados",
        "BB14006",
    )
    assert a == {
        "street1": "Cedar Court, Ground Floor",
        "street2": "Harbour Business Park",
        "city": "Wildey",
        "state": "St Michael",
        "zip": "BB14006",
        "country": "BB",
    }


def test_customers_take_the_bill_to_and_the_ship_to():
    f = _customer_fields(
        {
            "NAME": "Pinecrest Club",
            "BADDR1": "Pinecrest Club",
            "BADDR2": "2324 County Road 4",
            "BADDR3": "Boulder, CO  80301",
            "SADDR1": "Pinecrest Club",
            "SADDR2": "1 Clubhouse Rd",
            "SADDR3": "Boulder, CO  80302",
        }
    )
    assert (f["bill_address1"], f["bill_city"], f["bill_zip"], f["bill_country"]) == (
        "2324 County Road 4",
        "Boulder",
        "80301",
        "US",
    )
    assert (f["ship_address1"], f["ship_zip"], f["ship_country"]) == (
        "1 Clubhouse Rd",
        "80302",
        "US",
    )
    # an older file's ADDR lines are still the bill-to
    f = _customer_fields(
        {"NAME": "X", "ADDR1": "1 Main St", "ADDR2": "Springfield, IL 62704"}
    )
    assert (f["bill_address1"], f["bill_city"]) == ("1 Main St", "Springfield")
    assert "ship_address1" not in f


def test_vendors_import_with_the_street_in_the_street(db_session):
    from app.models.contacts import Vendor
    from app.services.iif_import import import_vendors

    got = import_vendors(
        db_session,
        [
            {
                "NAME": "Lakeside Golf Club",
                "ADDR1": "1200 Lakeshore Road",
                "ADDR2": "Springfield, IL  62704",
            }
        ],
    )
    assert got["imported"] == 1
    v = db_session.query(Vendor).filter_by(name="Lakeside Golf Club").one()
    assert (v.company, v.address1, v.city, v.state, v.zip) == (
        None,
        "1200 Lakeshore Road",
        "Springfield",
        "IL",
        "62704",
    )
