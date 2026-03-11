from collections.abc import Sequence
from functools import total_ordering
from typing import Optional, TypeVar, overload

T = TypeVar("T", covariant=True)
U = TypeVar("U", covariant=True)


@total_ordering
class IList(Sequence[T]):
    __slots__ = ("_frozen", "_items")

    def __init__(self, items: Optional[Sequence[T]] = None):
        if items is not None:
            items = list(items)
        else:
            items = []
        self._items = items

    @overload
    def __getitem__(self, i: int) -> T: ...

    @overload
    def __getitem__(self, i: slice) -> "IList[T]": ...

    def __getitem__(self, i: slice | int) -> "IList[T]" | T:
        match i:
            case int(i):
                return self._items[i]
            case slice():
                return IList(self._items[i])

    def __len__(self) -> int:
        return self._items.__len__()

    def __eq__(self, other: object) -> bool:
        if type(other) is type(self):
            return self._items == other._items  # type: ignore
        raise Exception(f"cannot compare IList with {type(other)}")

    def __le__(self, other: "IList[T]") -> bool:
        return self._items <= other._items

    def __repr__(self) -> str:
        s = "ilist("
        for i, x in enumerate(self):
            if i != 0:
                s += ", "
            s += repr(x)
        s += ")"
        return s

    def __hash__(self) -> int:
        return hash(tuple(self))

    def __add__(self, other: "IList[U]") -> "IList[T | U]":
        return IList(self._items + other._items)  # type: ignore


def ilist(*args: T) -> IList[T]:
    return IList(args)
