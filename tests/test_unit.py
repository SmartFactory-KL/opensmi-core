# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

import pytest
from asyncua import ua

from opensmi.core import Unit


def test_known_centimeter():
    assert Unit.CENTIMETRE.ua_unit_id == 4410708
    assert Unit.from_ua_unit_id(4410708) == Unit.CENTIMETRE
    assert Unit.from_symbol("cm") == Unit.CENTIMETRE


def test_ua_eu_information():
    unit = Unit.CENTIMETRE
    ua_eu_information = unit.ua_eu_information

    assert isinstance(ua_eu_information, ua.EUInformation)
    assert ua_eu_information.UnitId == unit.ua_unit_id
    assert ua_eu_information.DisplayName.Text == unit.symbol
    assert ua_eu_information.Description.Text == unit.name


def test_all_from_ua_unit_id():
    for unit in Unit:
        assert Unit.from_ua_unit_id(unit.ua_unit_id) is unit


def test_all_from_symbol():
    for unit in Unit:
        try:
            assert Unit.from_symbol(unit.symbol) is unit
        except ValueError as err:
            if "Ambiguous Unit symbol" in str(err):
                continue
            raise


def test_unit_from_symbol_ambiguous():
    with pytest.raises(ValueError, match="Ambiguous Unit symbol"):
        Unit.from_symbol("cal")


def test_unit_from_symbol_unknown():
    with pytest.raises(ValueError, match=r"Unknown Unit symbol.*NOT_A_UNIT_SYMBOL"):
        Unit.from_symbol("NOT_A_UNIT_SYMBOL")


def test_unit_from_ua_unit_id_unknown():
    with pytest.raises(ValueError, match=r"Unknown OPC UA unit ID.*0"):
        Unit.from_ua_unit_id(0)


def test_unit_repr():
    assert repr(Unit.CENTIMETRE) == "Unit.CENTIMETRE(symbol='cm', ua_unit_id=4410708)"


def test_unit_str():
    assert str(Unit.CENTIMETRE) == "cm"
