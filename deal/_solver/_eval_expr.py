import operator

import astroid
import z3

from ._context import Context
from ._registry import HandlersRegistry
from ._exceptions import UnsupportedError


eval_expr = HandlersRegistry()

CONSTS = {
    bool: z3.BoolVal,
    int: z3.IntVal,
    float: z3.RealVal,
    str: z3.StringVal,
}
COMAPARISON = {
    '<': operator.lt,
    '<=': operator.le,
    '>': operator.gt,
    '>=': operator.ge,
    '==': operator.eq,
    '!=': operator.ne,
}
UNARY_OPERATIONS = {
    '-': operator.neg,
    '+': operator.pos,
    '~': operator.inv,
}
BIN_OPERATIONS = {
    # math
    '+': operator.add,
    '-': operator.sub,
    '*': operator.mul,
    '/': operator.truediv,
    '**': operator.pow,
    '//': operator.floordiv,
    '%': operator.mod,
    '@': operator.matmul,

    # bitwise
    '&': operator.and_,
    '|': operator.or_,
    '^': operator.xor,
    '<<': operator.lshift,
    '>>': operator.rshift,
}
BOOL_OPERATIONS = {
    'and': z3.And,
    'or': z3.Or,
}


@eval_expr.register(astroid.Const)
def eval_const(node: astroid.Const, ctx: Context):
    t = type(node.value)
    converter = CONSTS.get(t)
    if not converter:
        raise UnsupportedError(repr(node.value))
    yield converter(node.value)


@eval_expr.register(astroid.BinOp)
def eval_bin_op(node: astroid.BinOp, ctx: Context):
    if not node.op:
        raise UnsupportedError('unsupported operator', node.op)
    operation = BIN_OPERATIONS.get(node.op)
    if not operation:
        raise UnsupportedError(repr(node.value))
    lefts = list(eval_expr(node=node.left, ctx=ctx))
    yield from lefts[:-1]
    rights = list(eval_expr(node=node.right, ctx=ctx))
    yield from rights[:-1]
    yield operation(lefts[-1], rights[-1])


@eval_expr.register(astroid.Compare)
def eval_compare(node: astroid.Compare, ctx: Context):
    lefts = list(eval_expr(node=node.left, ctx=ctx))
    yield from lefts[:-1]
    for op, right_node in node.ops:
        if not op:
            raise UnsupportedError(repr(node))
        operation = COMAPARISON.get(op)
        if not operation:
            raise UnsupportedError('unsupported operation', op, repr(node))

        rights = list(eval_expr(node=right_node, ctx=ctx))
        yield from rights[:-1]
        yield operation(lefts[-1], rights[-1])


@eval_expr.register(astroid.BoolOp)
def eval_bool_op(node: astroid.BoolOp, ctx: Context):
    if not node.op:
        raise UnsupportedError('unsupported operator', node.op)
    operation = BOOL_OPERATIONS.get(node.op)
    if not operation:
        raise UnsupportedError(repr(node.op))
    if not node.values:
        raise UnsupportedError('empty bool operator')

    subnodes = []
    for subnode in node.values:
        rights = list(eval_expr(node=subnode, ctx=ctx))
        yield from rights[:-1]
        subnodes.append(rights[-1])
    yield operation(*subnodes)


@eval_expr.register(astroid.Name)
def eval_name(node: astroid.Name, ctx: Context):
    if not isinstance(node, astroid.Name):
        raise UnsupportedError(type(node))
    var = ctx.scope.get(node.name)
    if var is None:
        raise UnsupportedError('cannot resolve name', node.name)
    yield var


@eval_expr.register(astroid.UnaryOp)
def eval_unary_op(node: astroid.UnaryOp, ctx: Context):
    operation = UNARY_OPERATIONS.get(node.op)
    if operation is None:
        raise UnsupportedError('unary operation', node.op)
    values = list(eval_expr(node=node.operand, ctx=ctx))
    yield from values[:-1]
    yield operation(values[-1])


@eval_expr.register(astroid.IfExp)
def eval_ternary_op(node: astroid.IfExp, ctx: Context):
    if node.test is None:
        raise UnsupportedError(type(node))
    if node.body is None:
        raise UnsupportedError(type(node))
    if node.orelse is None:
        raise UnsupportedError(type(node))

    # execute child nodes
    tests = list(eval_expr(node=node.test, ctx=ctx))
    yield tests[:-1]
    bodies = list(eval_expr(node=node.body, ctx=ctx))
    yield bodies[:-1]
    elses = list(eval_expr(node=node.orelse, ctx=ctx))
    yield elses[:-1]

    yield z3.If(tests[-1], bodies[-1], elses[-1])


@eval_expr.register(astroid.Call)
def eval_call(node: astroid.Call, ctx: Context):
    if not isinstance(node.func, astroid.Name):
        raise UnsupportedError('non-name call target', node.func)

    call_args = []
    for arg_node in node.args:
        arg_nodes = list(eval_expr(node=arg_node, ctx=ctx))
        yield from arg_nodes[:-1]
        call_args.append(arg_nodes[-1])

    target = node.func.name

    if len(call_args) == 1:
        a = call_args[0]
        if target == 'abs':
            yield z3.If(a >= z3.IntVal(0), a, -a)
            return

    if len(call_args) == 2:
        a, b = call_args
        if target == 'min':
            yield z3.If(a < b, a, b)
            return
        if target == 'max':
            yield z3.If(a > b, a, b)
            return

    raise UnsupportedError('unknown func', target)
