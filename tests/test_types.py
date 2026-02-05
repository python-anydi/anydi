from anydi._types import NOT_SET, to_list


def test_to_list_none() -> None:
    assert to_list(None) == []


def test_to_list_not_set() -> None:
    assert to_list(NOT_SET) == []


def test_to_list_single_value() -> None:
    assert to_list(42) == [42]
    assert to_list("hello") == ["hello"]


def test_to_list_list() -> None:
    assert to_list([1, 2, 3]) == [1, 2, 3]


def test_to_list_tuple() -> None:
    assert to_list((1, 2, 3)) == [1, 2, 3]
