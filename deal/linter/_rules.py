# built-in
import ast
import enum
from itertools import chain
from types import MappingProxyType
from typing import Iterator

# app
from ._contract import Category, Contract
from ._error import Error
from ._extractors import (
    get_asserts, get_exceptions, get_exceptions_stubs,
    get_imports, get_pre, get_markers, get_returns, has_returns,
)
from ._func import Func
from ._stub import StubsManager
from .._decorators import Has


rules = []


class Required(enum.Enum):
    FUNC = 'func'
    MODULE = 'module'


def register(rule):
    rules.append(rule())
    return rule


@register
class CheckImports:
    __slots__ = ()
    code = 1
    message = 'do not use `from deal import ...`, use `import deal` instead'
    required = Required.MODULE

    def __call__(self, tree: ast.Module) -> Iterator[Error]:
        for token in get_imports(tree.body):
            if token.value != 'deal':
                continue
            yield Error(
                code=self.code,
                text=self.message,
                row=token.line,
                col=token.col,
            )


@register
class CheckPre:
    __slots__ = ()
    code = 11
    message = 'pre contract error'
    required = Required.FUNC

    def __call__(self, func: Func, stubs: StubsManager = None) -> Iterator[Error]:
        # We test only contracted functions because of poor performance.
        # Inferring every called function in the whole project
        # is a really expensive operation.
        if not func.contracts:
            return
        for token in get_pre(body=func.body):
            yield Error(
                code=self.code,
                text=self.message,
                value=token.value,  # type: ignore
                row=token.line,
                col=token.col,
            )


@register
class CheckReturns:
    __slots__ = ()
    code = 12
    message = 'post contract error'
    required = Required.FUNC

    def __call__(self, func: Func, stubs: StubsManager = None) -> Iterator[Error]:
        for contract in func.contracts:
            if contract.category != Category.POST:
                continue
            yield from self._check(func=func, contract=contract)

    def _check(self, func: Func, contract: Contract) -> Iterator[Error]:
        for token in get_returns(body=func.body):
            try:
                result = contract.run(token.value)
            except NameError:
                # cannot resolve contract dependencies
                return

            error_info = dict(
                row=token.line,
                col=token.col,
                code=self.code,
                value=str(token.value),
            )
            if isinstance(result, str):
                yield Error(text=result, **error_info)  # type: ignore
                continue
            if not result:
                yield Error(text=self.message, **error_info)  # type: ignore


@register
class CheckRaises:
    __slots__ = ()
    code = 21
    message = 'raises contract error'
    required = Required.FUNC

    def __call__(self, func: Func, stubs: StubsManager = None) -> Iterator[Error]:
        for contract in func.contracts:
            if contract.category != Category.RAISES:
                continue
            yield from self._check(func=func, contract=contract, stubs=stubs)

    def _check(self, func: Func, contract: Contract, stubs: StubsManager = None) -> Iterator[Error]:
        allowed = contract.exceptions
        allowed_types = tuple(exc for exc in allowed if type(exc) is not str)
        tokens = [get_exceptions(body=func.body)]
        if stubs is not None:
            tokens.append(get_exceptions_stubs(body=func.body, stubs=stubs))
        for token in chain(*tokens):
            if token.value in allowed:
                continue
            exc = token.value
            if isinstance(exc, type):
                if issubclass(exc, allowed_types):
                    continue
                exc = exc.__name__
            yield Error(
                code=self.code,
                text=self.message,
                value=str(exc),
                row=token.line,
                col=token.col,
            )


@register
class CheckAsserts:
    __slots__ = ()
    code = 31
    message = 'assert error'
    required = Required.FUNC

    def __call__(self, func: Func, stubs: StubsManager = None) -> Iterator[Error]:
        # do not validate asserts in tests
        if func.name.startswith('test_'):
            return
        for token in get_asserts(body=func.body):
            yield Error(
                code=self.code,
                text=self.message,
                value=str(token.value),
                row=token.line,
                col=token.col,
            )


@register
class CheckMarkers:
    __slots__ = ()
    code = 40
    message = 'missed marker'
    required = Required.FUNC

    codes = MappingProxyType({
        'global': 41,
        'import': 42,
        'io': 43,
        'read': 44,
        'write': 45,
        'stdout': 46,
        'stderr': 47,
        'network': 48,
    })

    def __call__(self, func: Func, stubs: StubsManager = None) -> Iterator[Error]:
        for contract in func.contracts:
            if contract.category == Category.HAS:
                markers = [ast.literal_eval(arg) for arg in contract.args]
            elif contract.category in (Category.PURE, Category.SILENT):
                markers = []
            else:
                continue
            yield from self._check(func=func, has=Has(*markers))
            return

    @classmethod
    def _check(cls, func: Func, has: Has) -> Iterator[Error]:
        # function without IO must return something
        if not has.has_io and not has_returns(body=func.body):
            yield Error(
                code=cls.codes['io'],
                text=cls.message,
                value='io',
                row=func.line,
                col=func.col,
            )

        for token in get_markers(body=func.body):
            if getattr(has, 'has_{}'.format(token.marker)):
                continue
            yield Error(
                code=cls.codes[token.marker],
                text=cls.message,
                value=token.marker,
                row=token.line,
                col=token.col,
            )
