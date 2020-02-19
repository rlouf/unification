from toolz import assoc
from operator import length_hint
from functools import partial
from collections import OrderedDict, deque
from collections.abc import Generator, Iterator, Mapping, Set

from .utils import transitive_get as walk
from .variable import isvar, Var
from .dispatch import dispatch


# An object used to tell the reifier that the next yield constructs the reified
# object from its constituent refications (if any).
construction_sentinel = object()


def stream_eval(z, res_filter=None):
    """Evaluate a stream of `_reify`/`_unify` results.

    This implementation consists of a deque that simulates an evaluation stack
    of `_reify`/`_unify`-produced generators.  We're able to overcome
    `RecursionError`s this way.
    """

    if not isinstance(z, Generator):
        return z

    stack = deque()
    z_args, z_out = None, None
    stack.append(z)

    while stack:
        z = stack[-1]
        try:
            z_out = z.send(z_args)

            if res_filter:
                _ = res_filter(z, z_out)

            if isinstance(z_out, Generator):
                stack.append(z_out)
                z_args = None
            else:
                z_args = z_out

        except StopIteration:
            _ = stack.pop()

    return z_out


class UngroundLVarException(Exception):
    """An exception signaling that an unground variable was found."""


@dispatch(object, Mapping)
def _reify(o, s):
    yield o


@_reify.register(Var, Mapping)
def _reify_Var(o, s):
    o_w = walk(o, s)

    if o_w is o:
        yield o_w
    else:
        yield _reify(o_w, s)


def _reify_Iterable_ctor(ctor, t, s):
    """Create a generator that yields _reify generators.

    The yielded generators need to be evaluated by the caller and the fully
    reified results "sent" back to this generator so that it can finish
    constructing reified iterable.

    This approach allows us "collapse" nested `_reify` calls by pushing nested
    calls up the stack.
    """
    res = []

    if isinstance(t, Mapping):
        t = t.items()

    for y in t:
        r = _reify(y, s)
        if isinstance(r, Generator):
            r = yield r
        res.append(r)

    yield construction_sentinel

    yield ctor(res)


for seq, ctor in (
    (tuple, tuple),
    (list, list),
    (Iterator, iter),
    (set, set),
    (frozenset, frozenset),
):
    _reify.add((seq, Mapping), partial(_reify_Iterable_ctor, ctor))


for seq in (dict, OrderedDict):
    _reify.add((seq, Mapping), partial(_reify_Iterable_ctor, seq))


@_reify.register(slice, Mapping)
def _reify_slice(o, s):
    start = yield _reify(o.start, s)
    stop = yield _reify(o.stop, s)
    step = yield _reify(o.step, s)

    yield construction_sentinel

    yield slice(start, stop, step)


@dispatch(object, Mapping)
def reify(e, s):
    """Replace logic variables in a term, `e`, with their substitutions in `s`.

    >>> x, y = var(), var()
    >>> e = (1, x, (3, y))
    >>> s = {x: 2, y: 4}
    >>> reify(e, s)
    (1, 2, (3, 4))

    >>> e = {1: x, 3: (y, 5)}
    >>> reify(e, s)
    {1: 2, 3: (4, 5)}
    """

    z = _reify(e, s)
    return stream_eval(z)


@dispatch(object, object, Mapping)
def _unify(u, v, s):
    return s if u == v else False


@_unify.register(Var, (Var, object), Mapping)
def _unify_Var_object(u, v, s):
    u_w = walk(u, s)

    if isvar(v):
        v = walk(v, s)

    if u_w is u:
        if u != v:
            yield assoc(s, u, v)
        else:
            yield s
        return

    yield _unify(u_w, v, s)


@_unify.register(object, Var, Mapping)
def _unify_object_Var(u, v, s):
    return _unify_Var_object(v, u, s)


def _unify_Iterable(u, v, s):
    len_u = length_hint(u, -1)
    len_v = length_hint(v, -1)

    if len_u != len_v:
        yield False
        return

    for uu, vv in zip(u, v):
        s = yield _unify(uu, vv, s)
        if s is False:
            return
    else:
        yield s


for seq in (tuple, list, Iterator):
    _unify.add((seq, seq, Mapping), _unify_Iterable)


@_unify.register(Set, Set, Mapping)
def _unify_Set(u, v, s):
    i = u & v
    u = u - i
    v = v - i
    yield _unify(iter(u), iter(v), s)


@_unify.register(Mapping, Mapping, Mapping)
def _unify_Mapping(u, v, s):
    if len(u) != len(v):
        yield False
        return

    for key, uval in u.items():
        if key not in v:
            yield False
            return

        s = yield _unify(uval, v[key], s)

        if s is False:
            return
    else:
        yield s


@_unify.register(slice, slice, Mapping)
def _unify_slice(u, v, s):
    s = yield _unify(u.start, v.start, s)
    if s is False:
        return
    s = yield _unify(u.stop, v.stop, s)
    if s is False:
        return
    s = yield _unify(u.step, v.step, s)


@dispatch(object, object, Mapping)
def unify(u, v, s):
    """Find substitution so that u == v while satisfying s.

    >>> x = var('x')
    >>> unify((1, x), (1, 2), {})
    {~x: 2}
    """
    if u is v:
        return s

    z = _unify(u, v, s)
    return stream_eval(z)


@unify.register(object, object)
def unify_NoMap(u, v):
    return unify(u, v, {})


def unground_lvars(u, s):
    """Return the unground logic variables from a term and state."""

    lvars = set()

    def lvar_filter(z, r):
        nonlocal lvars

        if isvar(r):
            lvars.add(r)

        if r is construction_sentinel:
            z.close()

            # Remove this generator from the stack.
            raise StopIteration()

    z = _reify(u, s)
    stream_eval(z, lvar_filter)

    return lvars


def isground(u, s):
    """Determine whether or not `u` contains an unground logic variable under mappings `s`."""

    def lvar_filter(z, r):

        if isvar(r):
            raise UngroundLVarException()
        elif r is construction_sentinel:
            z.close()

            # Remove this generator from the stack.
            raise StopIteration()

    try:
        z = _reify(u, s)
        stream_eval(z, lvar_filter)
    except UngroundLVarException:
        return False

    return True
