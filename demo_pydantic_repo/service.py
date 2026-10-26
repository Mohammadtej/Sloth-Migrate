"""In-memory business service (no database dependency)."""

from typing import Dict, List, Optional
from models import User, Order, ProductItem


class UserService:
    """In-memory service managing users without any database dependency."""

    def __init__(self) -> None:
        self._users: Dict[int, User] = {}

    def register_user(self, user_data: dict) -> User:
        user = User.model_validate(user_data)
        self._users[user.id] = user
        return user

    def get_user(self, user_id: int) -> Optional[User]:
        return self._users.get(user_id)

    def export_user(self, user_id: int) -> Optional[dict]:
        user = self._users.get(user_id)
        if user:
            return user.model_dump()
        return None


class OrderService:
    """In-memory service managing orders without any database dependency."""

    def __init__(self) -> None:
        self._orders: Dict[str, Order] = {}

    def place_order(self, order_data: dict) -> Order:
        order = Order.from_dict(order_data)
        self._orders[order.order_id] = order
        return order

    def get_order_summary(self, order_id: str) -> Optional[dict]:
        order = self._orders.get(order_id)
        if order:
            return order.model_dump()
        return None
