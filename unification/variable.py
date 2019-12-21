from contextlib import contextmanager, suppress

from .dispatch import dispatch

_global_logic_variables = set()
_glv = _global_logic_variables


class Var(object):
    """A logic variable type."""

    _id = 1

    def __new__(cls, *token):
        if len(token) == 0:
            token = "_%s" % Var._id
            Var._id += 1
        elif len(token) == 1:
            token = token[0]

        obj = object.__new__(cls)
        obj.token = token
        return obj

    def __str__(self):
        return "~" + str(self.token)

    __repr__ = __str__

    def __eq__(self, other):
        return type(self) == type(other) and self.token == other.token

    def __hash__(self):
        return hash((type(self), self.token))


var = lambda *args: Var(*args)
vars = lambda n: [var() for i in range(n)]


@dispatch(Var)
def isvar(v):
    return True


@dispatch(object)
def isvar(o):
    with suppress(TypeError):
        return o in _glv


@contextmanager
def variables(*variables):
    """Create a context manager for making arbitrary objects logic variables.

    >>> from __future__ import with_statement
    >>> with variables(1):
    ...     print(isvar(1))
    True

    >>> print(isvar(1))
    False

    Normal approach

    >>> from unification import unify
    >>> x = var('x')
    >>> unify(x, 1)
    {~x: 1}

    Context Manager approach
    >>> with variables('x'):
    ...     print(unify('x', 1))
    {'x': 1}
    """
    old_global_logic_variables = _global_logic_variables.copy()
    _global_logic_variables.update(set(variables))
    try:
        yield
    finally:
        _global_logic_variables.clear()
        _global_logic_variables.update(old_global_logic_variables)
