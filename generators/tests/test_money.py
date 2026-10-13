from decimal import Decimal

from generators.money import a_usd, desde_usd, redondear


def test_redondear_respeta_los_decimales_de_cada_moneda():
    assert redondear(Decimal("636114.00"), "JPY") == Decimal("636114")
    assert str(redondear(Decimal("636114.00"), "JPY")) == "636114"
    assert str(redondear(Decimal("10.005"), "USD")) == "10.01"


def test_desde_usd_y_a_usd_son_inversas(tasas):
    cop = desde_usd(100, "COP", tasas)
    assert cop == redondear(Decimal(100) * tasas["COP"], "COP")
    assert abs(a_usd(cop, "COP", tasas) - 100) < Decimal("0.01")


def test_tasas_guardadas_tienen_las_cuatro_monedas(tasas):
    assert set(tasas) == {"USD", "COP", "EUR", "JPY"}
    assert tasas["USD"] == 1
