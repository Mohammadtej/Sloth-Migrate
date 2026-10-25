import pytest
from app import UserProfile


def test_user_profile():
    user = UserProfile(username="Alice", age=25)
    assert user.username == "alice"
    data = user.serialize()
    assert data["username"] == "alice"
    assert data["age"] == 25


def test_invalid_username():
    with pytest.raises(ValueError):
        UserProfile(username="al", age=20)