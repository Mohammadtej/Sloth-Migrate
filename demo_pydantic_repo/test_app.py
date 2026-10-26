"""Tests verifying models and services with Pydantic."""

import pytest
from models import User, Order, ProductItem
from service import UserService, OrderService


def test_user_creation_and_validation():
    user = User(
        id=1,
        username="  JohnDoe  ",
        email="JohnDoe@Example.COM",
        bio="Python developer",
    )
    assert user.username == "johndoe"
    assert user.email == "johndoe@example.com"
    data = user.to_dict()
    assert isinstance(data, dict)
    assert data["username"] == "johndoe"
    json_str = user.to_json()
    assert isinstance(json_str, str)


def test_user_validation_error():
    with pytest.raises(ValueError):
        User(id=2, username="jd", email="valid@example.com")

    with pytest.raises(ValueError):
        User(id=3, username="johndoe", email="invalid-email")


def test_order_root_validator():
    items = [
        {"item_id": "ITEM-1", "quantity": 2, "unit_price": 10.50},
        {"item_id": "ITEM-2", "quantity": 1, "unit_price": 5.00},
    ]
    order = Order.from_dict({
        "order_id": "ORD-1001",
        "customer_email": "customer@example.com",
        "items": items,
    })
    assert order.total_amount == 26.00
    serialized = order.serialize()
    assert serialized["total_amount"] == 26.00
    assert len(serialized["items"]) == 2


def test_in_memory_services():
    user_svc = UserService()
    user = user_svc.register_user({
        "id": 10,
        "username": "Alice",
        "email": "alice@example.com",
    })
    assert user.id == 10
    exported = user_svc.export_user(10)
    assert exported is not None
    assert exported["username"] == "alice"

    order_svc = OrderService()
    order = order_svc.place_order({
        "order_id": "ORD-2002",
        "customer_email": "alice@example.com",
        "items": [
            {"item_id": "PROD-A", "quantity": 3, "unit_price": 15.00}
        ],
    })
    summary = order_svc.get_order_summary("ORD-2002")
    assert summary is not None
    assert summary["total_amount"] == 45.00
