# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Mixin for async lifecycle management for mixin-composed classes.

Concepts

Resource mixin: a plain class (does not inherit `LifecycleMixin`) with one or
multiple ``@lifecycle``-decorated async-generator method(s). Code before yield is init;
code after yield is shutdown.

Composed class: the concrete class that inherits its resource mixins and
`LifecycleMixin`. This is the only class that should inherit `LifecycleMixin`.

Ordering: resources init in dependency order and shut down in the exact
reverse order. Order is resolved once, in `LifecycleMixin.__init_subclass__`, from
``after`` / ``before`` arguments of ``@lifecycle``-decorated methods.
"""

import graphlib
import inspect
import time
from collections.abc import AsyncGenerator, Callable
from typing import Final, Self, TypeVar, overload

import structlog

from opensmi.core.enums import LifecycleState
from opensmi.core.errors import CycleError
from opensmi.core.mixin_helpers import get_logger

_LOGGER = structlog.get_logger("open_smi." + __name__)

_ATTR_LIFECYCLE_AFTER: Final[str] = "_lifecycle_after"
_ATTR_LIFECYCLE_BEFORE: Final[str] = "_lifecycle_before"
_ATTR_LIFECYCLE_REQUIRES: Final[str] = "_lifecycle_requires"
_ATTR_LIFECYCLE_RESOURCE: Final[str] = "_is_lifecycle_resource"

_LifecycleFunc = TypeVar("_LifecycleFunc", bound=Callable[..., AsyncGenerator[None, None]])
_Func = Callable[..., AsyncGenerator[None, None]]
_FuncOrFuncs = _Func | tuple[_Func, ...] | list[_Func]


@overload
def lifecycle(_func: _LifecycleFunc) -> _LifecycleFunc: ...
@overload
def lifecycle(
    _func: None = None, *, after: _FuncOrFuncs = (), before: _FuncOrFuncs = ()
) -> Callable[[_LifecycleFunc], _LifecycleFunc]: ...
def lifecycle(
    _func: _LifecycleFunc | None = None,
    *,
    after: _FuncOrFuncs = (),
    before: _FuncOrFuncs = (),
    requires: _FuncOrFuncs = (),
) -> _LifecycleFunc | Callable[[_LifecycleFunc], _LifecycleFunc]:
    """Mark an async generator method as a lifecycle resource.

    Code before ``yield`` runs during initialization; code after ``yield``
    runs during shutdown, in reverse lifecycle order.

    :param after: Ordering constraint. If the referenced resources are present
        in the final composed class, they are started before and stopped after
        this resource. Silently ignored for resources that are absent.
    :param before: Ordering constraint. If the referenced resources are present
        in the final composed class, this resource is started before and stopped
        after them. Silently ignored for resources that are absent.
    :param requires: Presence constraint. All referenced resources must be
        present in the final composed class. This does not impose an ordering
        constraint. Checked by `LifecycleMixin.__init_subclass__`.
    """

    def _normalize(funcs: _FuncOrFuncs) -> tuple[_Func, ...]:
        funcs = (funcs,) if callable(funcs) and not isinstance(funcs, (tuple, list)) else tuple(funcs)

        for func in funcs:
            if not inspect.isasyncgenfunction(func):
                msg = f"@lifecycle '{func!r}' not an async generator function"
                raise TypeError(msg)

        return funcs

    def _decorator(func: _LifecycleFunc) -> _LifecycleFunc:
        if not inspect.isasyncgenfunction(func):
            msg = f"@lifecycle requires an async generator function, got {func!r}"
            raise TypeError(msg)
        setattr(func, _ATTR_LIFECYCLE_RESOURCE, True)
        setattr(func, _ATTR_LIFECYCLE_AFTER, tuple(_normalize(after)))
        setattr(func, _ATTR_LIFECYCLE_BEFORE, tuple(_normalize(before)))
        setattr(func, _ATTR_LIFECYCLE_REQUIRES, tuple(_normalize(requires)))
        return func

    if _func is not None:  # bare @resource, no args
        return _decorator(_func)
    return _decorator  # @resource(after=(...))


class LifecycleMixin:
    """Mixin managing the lifecycle of classes with ``@resource`` decorated methods."""

    __order: list[_Func] | None = None
    __generators: dict[_Func, AsyncGenerator[None, None]] | None = None
    __state: LifecycleState = LifecycleState.NEW

    def __init_subclass__(cls, **kwargs) -> None:
        """Determine the initialization order for a specific subclass.

        :raises CycleError: If there is a cycle in the dependency graph.
        """
        super().__init_subclass__(**kwargs)
        funcs = _collect_funcs(cls)
        edges = _build_edges(funcs)
        sorter = graphlib.TopologicalSorter(graph={node: tuple(edges.get(node, ())) for node in funcs})
        try:
            cls.__order = list(sorter.static_order())
        except graphlib.CycleError as err:
            raise CycleError(err.args[1]) from None

    async def init(self) -> Self:
        """Idempotent. Initialize all resources in dependency order.

        On failure, rollback anything already started, in reverse.

        :raises BaseException: Reraised exception from failed resource initialization.
        :raises ExceptionGroup: If exceptions were caught during rollback.
        """
        if self.__state != LifecycleState.NEW:
            return self
        self.__state = LifecycleState.INITIALIZING
        get_logger(self, _LOGGER).debug("Initialization started", order=self.lifecycle_order)
        self.__generators = {}

        started: list[_Func] = []
        time_start = time.monotonic()
        try:
            assert self.__order is not None
            for func in self.__order:
                get_logger(self, _LOGGER).debug("starting...", func=func.__qualname__)
                agen = func(self)
                await agen.__anext__()  # run resource init (until it yields)
                self.__generators[func] = agen
                started.append(func)
                get_logger(self, _LOGGER).debug("started successfully", func=func.__qualname__)
        except BaseException as init_exception:
            get_logger(self, _LOGGER).exception("Failed to initialize!")
            self.__state = LifecycleState.INITIALIZATION_FAILED
            rollback_exceptions: list[Exception] = await self.__shutdown(started)
            if rollback_exceptions:
                msg = (
                    f"Resource failed to initialize, and rollback {len(rollback_exceptions)} "
                    "resource(s) failed to shut down cleanly."
                )
                raise ExceptionGroup(
                    msg,
                    [init_exception, *rollback_exceptions],  # pyright: ignore[reportArgumentType]
                ) from init_exception
            raise

        self.__state = LifecycleState.INITIALIZED
        get_logger(self, _LOGGER).info("Initialization completed", elapsed=time.monotonic() - time_start)
        return self

    async def __shutdown(self, funcs: list[_Func]) -> list[Exception]:
        """Shut down in reverse order, best-effort. Returns all caught exceptions."""
        exceptions: list[Exception] = []
        for func in reversed(funcs):
            try:
                get_logger(self, _LOGGER).debug("stopping...", func=func.__qualname__)
                await self.__close_one(func)
                get_logger(self, _LOGGER).debug("stopped", func=func.__qualname__)
            except Exception as exception:
                exceptions.append(exception)
        return exceptions

    async def shutdown(self) -> None:
        """Idempotent. Run each resource's post-yield code in reverse dependency order."""
        if not self.is_initialized:
            return

        time_start = time.monotonic()
        self.__state = LifecycleState.SHUTTING_DOWN

        assert self.__order is not None
        exceptions: list[Exception] = await self.__shutdown(self.__order)

        if exceptions:
            self.__state = LifecycleState.SHUTDOWN_FAILED
            msg = f"{len(exceptions)} resource(s) failed to shut down cleanly."
            raise ExceptionGroup(msg, exceptions)

        self.__state = LifecycleState.SHUTDOWN
        get_logger(self, _LOGGER).info("Shutdown completed", elapsed=time.monotonic() - time_start)

    async def __close_one(self, func: _Func) -> None:
        if not self.__generators:
            get_logger(self, _LOGGER).warning("Generators empty! Skipping", func=func.__qualname__)
            return

        agen = self.__generators.pop(func, None)
        if agen is None:
            return
        try:
            await agen.__anext__()
        except StopAsyncIteration:  # we expect exactly one yield
            pass
        else:
            msg = f"resource on {func.__name__} yielded more than once"
            raise RuntimeError(msg)

    @property
    def is_initialized(self) -> bool:
        """Return ``True`` if initialized, ``False`` otherwise."""
        return self.__state == LifecycleState.INITIALIZED

    @property
    def lifecycle_state(self) -> LifecycleState:
        """Return the lifecycle state."""
        return self.__state

    @property
    def lifecycle_order(self) -> list[_Func]:
        """Return resolved init order (shutdown runs in reverse)."""
        assert self.__order is not None
        return list(self.__order)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _collect_funcs(cls: type) -> set[_Func]:
    """Collect all methods from given class decorated with ``@lifecycle``."""
    candidates: set[str] = set()
    for klass in cls.__mro__:
        for attr_name, attr_value in vars(klass).items():
            if getattr(attr_value, _ATTR_LIFECYCLE_RESOURCE, False):
                candidates.add(attr_name)

    funcs: dict[str, _Func] = {}
    for attr_name in candidates:
        resolved: _Func = getattr(cls, attr_name)
        if getattr(resolved, _ATTR_LIFECYCLE_RESOURCE, False):
            funcs[attr_name] = resolved
    return set(funcs.values())


def _build_edges(funcs: set[_Func]) -> dict[_Func, set[_Func]]:
    """Validate required resources and build lifecycle ordering edges."""
    edges: dict[_Func, set[_Func]] = {f: set() for f in funcs}

    for func in funcs:
        # hard requirement: target must be present
        required_funcs: tuple[type, ...] = getattr(func, _ATTR_LIFECYCLE_REQUIRES, ())
        for dep in required_funcs:
            if dep not in funcs:
                msg = (
                    f"{func.__qualname__} requires {dep.__qualname__} to be "
                    f"present as an active lifecycle, but it isn't."
                )
                raise TypeError(msg)

        # soft hint: only wire the edge if the target actually ended up present
        after_funcs: tuple[type, ...] = getattr(func, _ATTR_LIFECYCLE_AFTER, ())
        for after_func in after_funcs:
            if after_func in funcs:
                edges[func].add(after_func)

        before_funcs: tuple[type, ...] = getattr(func, _ATTR_LIFECYCLE_BEFORE, ())
        for before_func in before_funcs:
            if before_func in funcs:
                edges[before_func].add(func)

    return edges
