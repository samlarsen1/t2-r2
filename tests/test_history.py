from conftest import item
from t2r2.history import parse_item


def test_order_and_fill_shape() -> None:
    row = parse_item(item(7))
    assert row is not None
    assert (row.order_id, row.ticker, row.side, row.origin) == (7, "RIOl_EQ", "BUY", "API")
    assert (row.fill_price, row.filled_quantity, row.fill_value) == (48.0, 2.5, 120.6)
    assert row.taxes == 0.6 and row.currency == "GBP"
    assert row.filled_at == "2026-11-19T09:01:00Z"
    assert row.is_final and row.is_api
    assert '"id":7' in row.raw


def test_flat_shape_with_signed_sell_quantity() -> None:
    row = parse_item({"id": 9, "ticker": "NVDA_US_EQ", "type": "MARKET", "status": "FILLED",
                      "executor": "IOS", "orderedQuantity": -1.5, "filledQuantity": -1.5,
                      "fillPrice": 180.0, "fillCost": -200.5, "dateCreated": "2026-01-02",
                      "dateExecuted": "2026-01-02T15:00:00Z",
                      "taxes": [{"quantity": -0.1}]})
    assert row is not None
    assert (row.side, row.origin, row.quantity, row.fill_value) == ("SELL", "IOS", 1.5, 200.5)
    assert row.taxes == 0.1
    assert not row.is_api


def test_items_without_an_id_are_skipped() -> None:
    assert parse_item({"order": {"ticker": "X"}}) is None
    assert parse_item({"order": {"id": "12", "ticker": "X"}}) is None
