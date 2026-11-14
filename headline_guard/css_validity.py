"""Whether Chrome keeps a declaration of a hiding property, decided from its tokens at parse time.

Chrome drops a declaration whose value does not match the property's grammar, so an earlier
declaration of the same property still applies: `.x{opacity:0;opacity:banana}` keeps opacity 0.
The grammars here were built from the CSS specs and checked against Chrome 157: CSS.supports, and
computed styles in standards-mode and quirks-mode style sheets (CSS.supports accepts some values a
style sheet drops, such as `color: rgba(1,2,3,.5) rgba(1,2,3,.5)`). Where this module cannot tell,
it says UNKNOWN; it never guesses.
"""

from .css_values import MAXIMUM_MATH_DEPTH, NAMED_COLORS

VALID = "valid"
INVALID = "invalid"
QUIRKS_ONLY = "quirks-only"   # valid only in a quirks-mode document (unitless non-zero lengths, hashless hex colours)
UNKNOWN = "unknown"           # this module cannot tell

# How sure a verdict is, for combining the verdicts of the parts of a value: the least sure wins.
_SEVERITY = {VALID: 0, QUIRKS_ONLY: 1, UNKNOWN: 2, INVALID: 3}

_CSS_WIDE_KEYWORDS = frozenset({"inherit", "initial", "unset", "revert", "revert-layer", "revert-rule"})
# inherit() is listed because Chrome 157 rejects any value holding it, even next to var().
_SUBSTITUTION_FUNCTIONS = frozenset({"var", "env", "attr", "if", "inherit"})
_BLOCK_TYPES = frozenset({"() block", "[] block", "{} block"})
# tinycss2 reports a string or url() cut off by the end of the input as an error; Chrome accepts both.
_HARMLESS_ERRORS = frozenset({"eof-in-string", "eof-in-url"})
# Chrome 157 accepted var() fallbacks nested 10,000 deep and crashed the page at 30,000 to 100,000;
# a value with substitution functions that would be valid past this depth is UNKNOWN.
_SUBSTITUTION_DEPTH_CAP = 1000
# light-dark() and color-mix() nest without limit in Chrome; past this depth this module gives up.
_COLOR_DEPTH_CAP = 32


def _worst(first, second):
    if _SEVERITY[second] > _SEVERITY[first]:
        return second
    return first


def _significant(tokens):
    """The tokens without whitespace, comments and the harmless end-of-input errors."""
    found = []
    for token in tokens:
        kind = token.type
        if kind == "whitespace" or kind == "comment":
            continue
        if kind == "error" and token.kind in _HARMLESS_ERRORS:
            continue
        found.append(token)
    return found


def _without_comments(tokens):
    found = []
    for token in tokens:
        if token.type == "comment" or token.type == "error" and token.kind in _HARMLESS_ERRORS:
            continue
        found.append(token)
    return found


def _split_commas(tokens):
    """The comma-separated groups of tokens (comments dropped, whitespace kept)."""
    groups = [[]]
    for token in tokens:
        kind = token.type
        if kind == "literal" and token.value == ",":
            groups.append([])
        elif kind != "comment" and not (kind == "error" and token.kind in _HARMLESS_ERRORS):
            groups[-1].append(token)
    return groups


def _is_literal(token, character):
    return token.type == "literal" and token.value == character


def _is_dashed(name):
    """A custom property name, or the name of a custom function."""
    return name.startswith("--") and len(name) > 2


def _contains_substitution_or_bad_token(tokens):
    """(bad, substitution, depth): whether any nested token is a bad string, a bad url() or an
    unmatched closing bracket; whether a substitution function appears anywhere; the deepest nesting."""
    has_substitution = False
    deepest = 0
    pending = [(tokens, 1)]
    while pending:
        nodes, depth = pending.pop()
        if depth > deepest:
            deepest = depth
        for token in nodes:
            kind = token.type
            if kind == "function":
                name = token.lower_name
                if name in _SUBSTITUTION_FUNCTIONS or _is_dashed(name):
                    has_substitution = True
                pending.append((token.arguments, depth + 1))
            elif kind in _BLOCK_TYPES:
                pending.append((token.content, depth + 1))
            elif kind == "error" and token.kind not in _HARMLESS_ERRORS:
                return True, has_substitution, deepest
    return False, has_substitution, deepest


# ---- values with substitution functions ---------------------------------------------------------
# Chrome checks only that such a value is a <declaration-value>, and that each substitution function
# in it is well formed: https://drafts.csswg.org/css-variables-2/#substitution

def _fallback_verdict(tokens):
    """A fallback may hold anything but a top-level "!" or ";"."""
    for token in tokens:
        if _is_literal(token, "!") or _is_literal(token, ";"):
            return INVALID
    return VALID


def _split_first_comma(tokens):
    for index in range(len(tokens)):
        if _is_literal(tokens[index], ","):
            return tokens[:index], tokens[index + 1:]
    return tokens, None


def _var_verdict(arguments):
    head, fallback = _split_first_comma(arguments)
    name = _significant(head)
    if len(name) != 1 or name[0].type != "ident" or not _is_dashed(name[0].value):
        return INVALID
    if fallback is None:
        return VALID
    return _fallback_verdict(fallback)


def _env_verdict(arguments):
    head, fallback = _split_first_comma(arguments)
    parts = _significant(head)
    if not parts or parts[0].type != "ident":
        return INVALID
    for position in parts[1:]:
        if position.type != "number" or not position.is_integer or position.value < 0:
            return INVALID
    if fallback is None:
        return VALID
    return _fallback_verdict(fallback)


# The data types attr(x type(...)) takes (case-sensitive); <transform-list> takes no multiplier.
_SYNTAX_TYPES = frozenset({
    "angle", "color", "custom-ident", "image", "integer", "length", "length-percentage", "number", "percentage",
    "resolution", "string", "time", "transform-function", "transform-list",
})
_RESERVED_SYNTAX_IDENTIFIERS = _CSS_WIDE_KEYWORDS | {"default"}


def _syntax_component_verdict(tokens):
    """One component of a type() syntax: <data-type> or an identifier, with an optional + or #
    multiplier, written without whitespace."""
    multiplied = len(tokens) in (2, 4) and (_is_literal(tokens[-1], "+") or _is_literal(tokens[-1], "#"))
    if multiplied:
        tokens = tokens[:-1]
    if len(tokens) == 1 and tokens[0].type == "ident":
        if tokens[0].lower_value in _RESERVED_SYNTAX_IDENTIFIERS:
            return INVALID
        return VALID
    if len(tokens) == 3 and _is_literal(tokens[0], "<") and tokens[1].type == "ident" and _is_literal(tokens[2], ">"):
        name = tokens[1].value
        if name in _SYNTAX_TYPES and not (multiplied and name == "transform-list"):
            return VALID
    return INVALID


def _syntax_verdict(arguments):
    """type(): "*", or components separated by "|"."""
    tokens = _without_comments(arguments)
    parts = _significant(tokens)
    if len(parts) == 1 and _is_literal(parts[0], "*"):
        return VALID
    component = []
    components = [component]
    for token in tokens:
        if _is_literal(token, "|"):
            component = []
            components.append(component)
        else:
            component.append(token)
    for component in components:
        start = 0
        end = len(component)
        while start < end and component[start].type == "whitespace":
            start += 1
        while end > start and component[end - 1].type == "whitespace":
            end -= 1
        written = component[start:end]
        for token in written:
            if token.type == "whitespace":
                return INVALID
        if not written or _syntax_component_verdict(written) == INVALID:
            return INVALID
    return VALID


def _attr_verdict(arguments):
    """attr(<name> <type>?, <fallback>?): the type an identifier (units, raw-string, number...), "%"
    or type(<syntax>)."""
    head, fallback = _split_first_comma(arguments)
    parts = _significant(head)
    if not parts or parts[0].type != "ident" or len(parts) > 2:
        return INVALID
    if len(parts) == 2:
        kind = parts[1]
        if kind.type == "function" and kind.lower_name == "type":
            if _syntax_verdict(kind.arguments) == INVALID:
                return INVALID
        elif kind.type != "ident" and not _is_literal(kind, "%"):
            return INVALID
    if fallback is None:
        return VALID
    return _fallback_verdict(fallback)


def _split_at_literal(tokens, character):
    groups = [[]]
    for token in tokens:
        if _is_literal(token, character):
            groups.append([])
        else:
            groups[-1].append(token)
    return groups


def _is_keyword(token, keyword):
    return token.type == "ident" and token.lower_value == keyword


def _is_if_test(token):
    """A test of an if() condition: style(), media(), supports() or any other function or
    parenthesized group, whose insides Chrome takes as they are."""
    return token.type == "function" or token.type == "() block"


def _if_condition_verdict(parts):
    """else | not <test> | <test> [and <test>]* | <test> [or <test>]*"""
    if len(parts) == 1 and _is_keyword(parts[0], "else"):
        return VALID
    if parts and _is_keyword(parts[0], "not"):
        return VALID if len(parts) == 2 and _is_if_test(parts[1]) else INVALID
    if not parts or len(parts) % 2 == 0:
        return INVALID
    operator = None
    for index in range(len(parts)):
        part = parts[index]
        if index % 2 == 0:
            if not _is_if_test(part):
                return INVALID
        elif part.type != "ident" or part.lower_value not in ("and", "or"):
            return INVALID
        elif operator is None:
            operator = part.lower_value
        elif part.lower_value != operator:
            return INVALID
    return VALID


def _if_verdict(arguments):
    """if(<condition>: <value>; ...), with one optional ";" at the end."""
    branches = _split_at_literal(_without_comments(arguments), ";")
    if len(branches) > 1 and not _significant(branches[-1]):
        branches = branches[:-1]
    for branch in branches:
        colon = None
        for index in range(len(branch)):
            if _is_literal(branch[index], ":"):
                colon = index
                break
        if colon is None or _if_condition_verdict(_significant(branch[:colon])) == INVALID:
            return INVALID
        for token in branch[colon + 1:]:
            if _is_literal(token, "!"):
                return INVALID
    return VALID


def _custom_function_verdict(arguments):
    """--name(<argument>#?): each argument a <declaration-value> without a top-level {} block, "!"
    or ";", or else one non-empty {} block with nothing after it, not even whitespace (measured in
    Chrome 157)."""
    if not _significant(arguments):
        return VALID
    groups = _split_commas(arguments)
    # Chrome 157 also takes one empty argument before the first comma: --f(,1).
    if len(groups) > 1 and not _significant(groups[0]):
        groups = groups[1:]
    for group in groups:
        parts = _significant(group)
        if not parts:
            return INVALID
        block = None
        for part in parts:
            if part.type == "{} block":
                block = part
            elif _is_literal(part, "!") or _is_literal(part, ";"):
                return INVALID
        if block is not None:
            if len(parts) != 1 or group[-1] is not block or not _significant(block.content):
                return INVALID
            for token in block.content:
                if _is_literal(token, "!") or _is_literal(token, ";"):
                    return INVALID
    return VALID


def _inherit_verdict(arguments):
    return INVALID


_SUBSTITUTION_VERDICTS = {
    "var": _var_verdict, "env": _env_verdict, "attr": _attr_verdict, "if": _if_verdict, "inherit": _inherit_verdict,
}


def _substitution_functions_verdict(tokens):
    """INVALID if any substitution function nested anywhere in tokens is malformed, else VALID."""
    pending = [tokens]
    while pending:
        for token in pending.pop():
            kind = token.type
            if kind == "function":
                check = _SUBSTITUTION_VERDICTS.get(token.lower_name)
                if check is None and _is_dashed(token.lower_name):
                    check = _custom_function_verdict
                if check is not None and check(token.arguments) == INVALID:
                    return INVALID
                pending.append(token.arguments)
            elif kind in _BLOCK_TYPES:
                pending.append(token.content)
    return VALID


def _declaration_value_verdict(tokens, substitution, depth):
    """For a value that is a <declaration-value> with no top-level "!" or ";" (bad tokens were ruled
    out already): its substitution functions decide."""
    for token in _significant(tokens):
        if _is_literal(token, "!") or _is_literal(token, ";"):
            return INVALID
    if not substitution:
        return VALID
    if _substitution_functions_verdict(tokens) == INVALID:
        return INVALID
    if depth > _SUBSTITUTION_DEPTH_CAP:
        return UNKNOWN
    return VALID


def _substitution_validity(tokens, depth):
    """A value of a property other than a custom one, with a substitution function in it."""
    top_level = _significant(tokens)
    for token in top_level:
        # A {} block is allowed only as the whole value.
        if token.type == "{} block" and len(top_level) > 1:
            return INVALID
    return _declaration_value_verdict(tokens, True, depth)


# ---- math functions -----------------------------------------------------------------------------
# A type is a tuple of the exponents of (length, angle, time, frequency, resolution, percentage) and
# a percent hint, the index of the base type the percentages resolve against or -1 (CSS Typed OM:
# https://drafts.css-houdini.org/css-typed-om-1/#cssnumericvalue-type). _ANY_TYPE is a type this
# module cannot work out. Flex (fr) is left out: Chrome rejects it in every property here.

_NUMBER_TYPE = (0, 0, 0, 0, 0, 0, -1)
_LENGTH_TYPE = (1, 0, 0, 0, 0, 0, -1)
_ANGLE_TYPE = (0, 1, 0, 0, 0, 0, -1)
_TIME_TYPE = (0, 0, 1, 0, 0, 0, -1)
_FREQUENCY_TYPE = (0, 0, 0, 1, 0, 0, -1)
_RESOLUTION_TYPE = (0, 0, 0, 0, 1, 0, -1)
_PERCENTAGE_TYPE = (0, 0, 0, 0, 0, 1, -1)
_PERCENT = 5
_HINT = 6
_SUM_HINTS = (0, 1)
_ANY_TYPE = "any type"

# The units Chrome 157 accepts (CSS.supports over the units of the specs, any case).
_UNIT_TYPES = {}
for _unit in ("px", "em", "rem", "ex", "rex", "ch", "rch", "cap", "rcap", "ic", "ric", "lh", "rlh", "vw", "vh", "vi",
              "vb", "vmin", "vmax", "svw", "svh", "svi", "svb", "svmin", "svmax", "lvw", "lvh", "lvi", "lvb", "lvmin",
              "lvmax", "dvw", "dvh", "dvi", "dvb", "dvmin", "dvmax", "cqw", "cqh", "cqi", "cqb", "cqmin", "cqmax", "cm",
              "mm", "q", "in", "pt", "pc"):
    _UNIT_TYPES[_unit] = _LENGTH_TYPE
for _unit in ("deg", "grad", "rad", "turn"):
    _UNIT_TYPES[_unit] = _ANGLE_TYPE
for _unit in ("s", "ms"):
    _UNIT_TYPES[_unit] = _TIME_TYPE
for _unit in ("hz", "khz"):
    _UNIT_TYPES[_unit] = _FREQUENCY_TYPE
for _unit in ("dpi", "dpcm", "dppx", "x"):
    _UNIT_TYPES[_unit] = _RESOLUTION_TYPE

_MATH_CONSTANTS = frozenset({"e", "pi", "infinity", "-infinity", "nan"})
_ROUNDING_STRATEGIES = frozenset({"nearest", "up", "down", "to-zero"})


def _with_hint(value_type, hint):
    """value_type with its percentages resolved against base type hint."""
    exponents = list(value_type[:_HINT])
    exponents[hint] += exponents[_PERCENT]
    exponents[_PERCENT] = 0
    exponents.append(hint)
    return tuple(exponents)


def _hinted_alike(first, second):
    """first and second with the percent hint of either applied to the other, or INVALID."""
    if first[_HINT] != -1 and second[_HINT] != -1 and first[_HINT] != second[_HINT]:
        return INVALID
    if first[_HINT] != -1 and second[_HINT] == -1:
        second = _with_hint(second, first[_HINT])
    elif second[_HINT] != -1 and first[_HINT] == -1:
        first = _with_hint(first, second[_HINT])
    return first, second


def _has_other_than_percent(value_type):
    for index in range(_PERCENT):
        if value_type[index] != 0:
            return True
    return False


def _sum_of_types(first, second):
    if first == _ANY_TYPE or second == _ANY_TYPE:
        return _ANY_TYPE
    alike = _hinted_alike(first, second)
    if alike == INVALID:
        return INVALID
    first, second = alike
    if first[:_HINT] == second[:_HINT]:
        return first[:_HINT] + (max(first[_HINT], second[_HINT]),)
    if (first[_PERCENT] or second[_PERCENT]) and (_has_other_than_percent(first) or _has_other_than_percent(second)):
        # Chrome resolves percentages in a sum against lengths and angles, and in ways this module does
        # not follow against the other base types.
        for hint in range(_PERCENT):
            hinted = _with_hint(first, hint)
            if hinted == _with_hint(second, hint):
                if hint in _SUM_HINTS:
                    return hinted
                return _ANY_TYPE
    return INVALID


def _product_of_types(first, second, dividing):
    if first == _ANY_TYPE or second == _ANY_TYPE:
        return _ANY_TYPE
    alike = _hinted_alike(first, second)
    if alike == INVALID:
        return INVALID
    first, second = alike
    exponents = []
    for index in range(_HINT):
        if dividing:
            exponents.append(first[index] - second[index])
        else:
            exponents.append(first[index] + second[index])
    exponents.append(max(first[_HINT], second[_HINT]))
    return tuple(exponents)


def _is_plain_number(value_type):
    return value_type[:_HINT] == _NUMBER_TYPE[:_HINT]


def _involves_percentage(value_type):
    return value_type[_PERCENT] != 0 or value_type[_HINT] != -1


def _is_simple(value_type):
    """Whether value_type is a number or one base type to the power 1, not a product such as length
    times angle."""
    exponents = 0
    for index in range(_HINT):
        if value_type[index] == 1:
            exponents += 1
        elif value_type[index] != 0:
            return False
    return exponents <= 1


def _skip_whitespace(tokens, index, end):
    while index < end and tokens[index].type == "whitespace":
        index += 1
    return index


def _leaf_type(token, percentages):
    """The type of a number, dimension, percentage or constant, else INVALID."""
    kind = token.type
    if kind == "number":
        return _NUMBER_TYPE
    if kind == "dimension":
        return _UNIT_TYPES.get(token.lower_unit, INVALID)
    if kind == "percentage":
        if percentages:
            return _PERCENTAGE_TYPE
        return INVALID
    if kind == "ident" and token.lower_value in _MATH_CONSTANTS:
        return _NUMBER_TYPE
    return INVALID


def _sum_type(tokens, percentages, depth):
    """The type of a calc sum, or INVALID. "+" and "-" need whitespace on both sides, "*" and "/" do
    not. Nested functions and parentheses recurse through here and _math_function_type only, two
    Python frames a level, so MAXIMUM_MATH_DEPTH levels stay well inside the recursion limit."""
    end = len(tokens)
    while end > 0 and tokens[end - 1].type == "whitespace":
        end -= 1
    index = _skip_whitespace(tokens, 0, end)
    total = None
    product = None
    product_operator = None
    while True:
        if index >= end:
            return INVALID
        token = tokens[index]
        if token.type == "function":
            value = _math_function_type(token, percentages, depth + 1)
        elif token.type == "() block":
            if depth + 1 > MAXIMUM_MATH_DEPTH:
                return INVALID
            value = _sum_type(_without_comments(token.content), percentages, depth + 1)
        else:
            value = _leaf_type(token, percentages)
        if value == INVALID:
            return INVALID
        if product_operator is None:
            product = value
        else:
            product = _product_of_types(product, value, product_operator == "/")
            if product == INVALID:
                return INVALID
        index += 1
        operator_index = _skip_whitespace(tokens, index, end)
        if operator_index >= end:
            break
        operator = tokens[operator_index]
        if _is_literal(operator, "*") or _is_literal(operator, "/"):
            product_operator = operator.value
        elif (_is_literal(operator, "+") or _is_literal(operator, "-")) and operator_index > index and \
                operator_index + 1 < end and tokens[operator_index + 1].type == "whitespace":
            total = product if total is None else _sum_of_types(total, product)
            if total == INVALID:
                return INVALID
            product_operator = None
        else:
            return INVALID
        index = _skip_whitespace(tokens, operator_index + 1, end)
    if total is None:
        return product
    return _sum_of_types(total, product)


def _common_type(types):
    common = types[0]
    for value_type in types[1:]:
        common = _sum_of_types(common, value_type)
        if common == INVALID:
            return INVALID
    return common


def _percentages_unfollowed(types):
    """Whether a percentage, or a type this module cannot work out, went into these types: Chrome
    types percentages in the functions below in ways this module does not follow."""
    for value_type in types:
        if value_type == _ANY_TYPE or _involves_percentage(value_type):
            return True
    return False


def _numbers_only(types, result_type):
    """result_type for arguments that must be plain numbers; _ANY_TYPE when percentages went into
    them and nothing else rules them out."""
    for value_type in types:
        if value_type == _ANY_TYPE or _involves_percentage(value_type):
            result_type = _ANY_TYPE
        elif not _is_plain_number(value_type):
            return INVALID
    return result_type


def _argument_type(types):
    return types[0]


def _sign_result(types):
    if types[0] == _ANY_TYPE:
        return _ANY_TYPE
    return _NUMBER_TYPE


def _round_result(types):
    if len(types) == 2:
        return _common_type(types)
    # Without the rounding interval only a number can be rounded.
    if _percentages_unfollowed(types) or _is_plain_number(types[0]):
        return _numbers_only(types, _NUMBER_TYPE)
    return INVALID


def _trigonometric_result(types):
    if _percentages_unfollowed(types):
        return _ANY_TYPE
    if _is_plain_number(types[0]) or types[0] == _ANGLE_TYPE:
        return _NUMBER_TYPE
    return INVALID


def _inverse_trigonometric_result(types):
    return _numbers_only(types, _ANGLE_TYPE)


def _number_result(types):
    return _numbers_only(types, _NUMBER_TYPE)


def _same_type_without_percentages(types, result_type):
    """result_type (None: the common type) for arguments that must share a type, or _ANY_TYPE when
    percentages went into them."""
    common = _common_type(types)
    if common == INVALID:
        return INVALID
    if _percentages_unfollowed(types):
        return _ANY_TYPE
    if result_type is None:
        return common
    return result_type


def _atan2_result(types):
    return _same_type_without_percentages(types, _ANGLE_TYPE)


def _hypot_result(types):
    return _same_type_without_percentages(types, None)


def _progress_result(types):
    return _same_type_without_percentages(types, _NUMBER_TYPE)


# For each math function: the numbers of comma-separated arguments it takes (None: one or more) and
# the function giving its type from theirs.
_MATH_FUNCTIONS = {
    "calc": ((1,), _argument_type), "-webkit-calc": ((1,), _argument_type),
    "min": (None, _common_type), "max": (None, _common_type), "clamp": ((1, 2, 3), _common_type),
    "round": ((1, 2), _round_result), "mod": ((2,), _common_type), "rem": ((2,), _common_type),
    "abs": ((1,), _argument_type), "sign": ((1,), _sign_result),
    "sin": ((1,), _trigonometric_result), "cos": ((1,), _trigonometric_result), "tan": ((1,), _trigonometric_result),
    "asin": ((1,), _inverse_trigonometric_result), "acos": ((1,), _inverse_trigonometric_result),
    "atan": ((1,), _inverse_trigonometric_result), "atan2": ((2,), _atan2_result),
    "pow": ((2,), _number_result), "sqrt": ((1,), _number_result), "exp": ((1,), _number_result),
    "log": ((1, 2), _number_result), "hypot": (None, _hypot_result), "progress": ((3,), _progress_result),
    "sibling-index": ((0,), _number_result), "sibling-count": ((0,), _number_result),
}
# The math functions whose arguments may have product types, such as length times angle.
_PRODUCT_TYPE_FUNCTIONS = frozenset({"calc", "-webkit-calc", "min", "max"})
# Chrome 157 takes sqrt() and exp() of some dimensions though not of others (sqrt(1em) as a length,
# exp(1em) and exp(1turn / 1deg * 1s) as numbers, but not sqrt(1px) or exp(1deg)); this module does
# not follow those.
_LENIENT_NUMBER_FUNCTIONS = frozenset({"sqrt", "exp"})
# Math functions whose types this module does not follow.
_UNFOLLOWED_MATH_FUNCTIONS = frozenset({
    "random", "random-item", "calc-size", "anchor", "anchor-size", "media-progress", "container-progress",
})


def _math_arguments(name, groups):
    """The argument groups of math function name that carry a calc sum, or INVALID: clamp()
    takes "none" for a bound, round() a rounding strategy first, sibling-index() nothing."""
    if name == "clamp":
        if len(groups) != 3:
            return INVALID
        bounded = [groups[1]]
        for position in (0, 2):
            if not _is_none(groups[position]):
                bounded.append(groups[position])
        return bounded
    if name == "round":
        first = _significant(groups[0])
        if len(first) == 1 and first[0].type == "ident" and first[0].lower_value in _ROUNDING_STRATEGIES:
            return groups[1:]
    if len(groups) == 1 and not _significant(groups[0]):
        return []
    return groups


def _is_none(group):
    parts = _significant(group)
    return len(parts) == 1 and parts[0].type == "ident" and parts[0].lower_value == "none"


def _is_math_function(token):
    return token.lower_name in _MATH_FUNCTIONS or token.lower_name in _UNFOLLOWED_MATH_FUNCTIONS


def _math_function_type(function, percentages, depth):
    # Chrome drops math nested deeper than MAXIMUM_MATH_DEPTH, functions and parentheses together.
    if depth > MAXIMUM_MATH_DEPTH:
        return INVALID
    name = function.lower_name
    if name in _UNFOLLOWED_MATH_FUNCTIONS:
        return _ANY_TYPE
    signature = _MATH_FUNCTIONS.get(name)
    if signature is None:
        return INVALID
    counts, result = signature
    groups = _math_arguments(name, _split_commas(function.arguments))
    if groups == INVALID or counts is None and not groups or counts is not None and len(groups) not in counts:
        return INVALID
    types = []
    for group in groups:
        value_type = _sum_type(group, percentages, depth)
        if value_type == INVALID:
            return INVALID
        if value_type != _ANY_TYPE and name not in _PRODUCT_TYPE_FUNCTIONS and not _is_simple(value_type):
            if _involves_percentage(value_type):
                return _ANY_TYPE
            return INVALID
        if name in _LENIENT_NUMBER_FUNCTIONS and value_type != _ANY_TYPE and not _is_plain_number(value_type):
            return _ANY_TYPE
        types.append(value_type)
    return result(types)


# ---- numbers, lengths, angles ---------------------------------------------------------------------

_LENGTH = frozenset({"length"})
_LENGTH_PERCENTAGE = frozenset({"length", "percentage"})
_NUMBER = frozenset({"number"})
_NUMBER_PERCENTAGE = frozenset({"number", "percentage"})
_PERCENTAGE = frozenset({"percentage"})
_ANGLE = frozenset({"angle"})
_NUMBER_ANGLE = frozenset({"number", "angle"})
_NUMBER_LENGTH_PERCENTAGE = frozenset({"number", "length", "percentage"})

_CATEGORY_OF_TYPE = {
    _NUMBER_TYPE[:_HINT]: "number", _LENGTH_TYPE[:_HINT]: "length", _ANGLE_TYPE[:_HINT]: "angle",
    _TIME_TYPE[:_HINT]: "time", _FREQUENCY_TYPE[:_HINT]: "frequency", _RESOLUTION_TYPE[:_HINT]: "resolution",
    _PERCENTAGE_TYPE[:_HINT]: "percentage",
}


def _type_matches(value_type, accepted):
    """Whether a math result of value_type fits a slot taking the categories in accepted. Like Chrome,
    percentages left over resolve against lengths to make a length, or against any base type to make
    a number, and a percent hint is ignored for numbers."""
    category = _CATEGORY_OF_TYPE.get(value_type[:_HINT])
    if category in accepted:
        return category != "length" or value_type[_HINT] == -1 or "percentage" in accepted
    if value_type[_HINT] == -1 and value_type[_PERCENT] != 0:
        if "length" in accepted and "percentage" in accepted and                 _CATEGORY_OF_TYPE.get(_with_hint(value_type, 0)[:_HINT]) == "length":
            return True
        if "number" in accepted:
            for hint in range(_PERCENT):
                if _is_plain_number(_with_hint(value_type, hint)):
                    return True
    return False


def _numeric(token, accepted, nonnegative=False, unitless_zero=False, quirk=False, integer=False):
    """The verdict for one number, percentage, dimension or math function in a slot taking the
    categories in accepted. unitless_zero: a bare 0 counts as a length or angle; quirk: a bare
    number counts as a length in quirks mode; integer: a literal number must be an integer."""
    kind = token.type
    if kind == "number":
        if nonnegative and token.value < 0:
            return INVALID
        if "number" in accepted:
            if integer and not token.is_integer:
                return INVALID
            return VALID
        if unitless_zero and token.value == 0:
            return VALID
        if quirk:
            return QUIRKS_ONLY
        return INVALID
    if kind == "percentage":
        if "percentage" in accepted and not (nonnegative and token.value < 0):
            return VALID
        return INVALID
    if kind == "dimension":
        value_type = _UNIT_TYPES.get(token.lower_unit)
        if value_type is None or _CATEGORY_OF_TYPE[value_type[:_HINT]] not in accepted:
            return INVALID
        if nonnegative and token.value < 0:
            return INVALID
        return VALID
    if kind == "function" and _is_math_function(token):
        value_type = _math_function_type(token, "percentage" in accepted, 1)
        if value_type == INVALID:
            return INVALID
        if value_type == _ANY_TYPE:
            return UNKNOWN
        if _type_matches(value_type, accepted):
            return VALID
        return INVALID
    return INVALID


# ---- colours --------------------------------------------------------------------------------------

_SYSTEM_COLORS = frozenset({
    "-webkit-activelink", "-webkit-link", "accentcolor", "accentcolortext", "activeborder", "activecaption",
    "activetext", "appworkspace", "background", "buttonborder", "buttonface", "buttonhighlight", "buttonshadow",
    "buttontext", "canvas", "canvastext", "captiontext", "currentcolor", "field", "fieldtext", "graytext",
    "highlight", "highlighttext", "inactiveborder", "inactivecaption", "inactivecaptiontext", "infobackground",
    "infotext", "linktext", "mark", "marktext", "menu", "menutext", "scrollbar", "selecteditem",
    "selecteditemtext", "threeddarkshadow", "threedface", "threedhighlight", "threedlightshadow", "threedshadow",
    "transparent", "visitedtext", "window", "windowframe", "windowtext",
})
_COLOR_KEYWORDS = frozenset(NAMED_COLORS) | _SYSTEM_COLORS
# Chrome allows this one only in quirks mode (and in its own style sheets).
_QUIRKS_ONLY_COLOR = "-webkit-focus-ring-color"
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _is_hex(text):
    for character in text:
        if character not in _HEX_DIGITS:
            return False
    return True


def _is_quirky_hex_color(token):
    """A hex colour written without its "#", accepted in quirks mode: an identifier of 3 or 6 hex
    digits, or an integer number or dimension that reads as hex once padded to 6 characters
    (Chromium's ParseHexColor)."""
    kind = token.type
    if kind == "ident":
        text = token.value
    elif kind == "number" or kind == "dimension":
        if not token.is_integer or token.value < 0 or token.value >= 1000000:
            return False
        text = str(token.int_value)
        if kind == "dimension":
            text += token.unit
        if len(text) < 6:
            text = "0" * (6 - len(text)) + text
    else:
        return False
    return (len(text) == 3 or len(text) == 6) and _is_hex(text)


def _channel(token, accepted):
    if token.type == "ident" and token.lower_value == "none":
        return VALID
    return _numeric(token, accepted)


def _modern_color_arguments(arguments, channel_categories):
    """Space-separated channels with an optional "/ alpha", each allowing "none"."""
    parts = _significant(arguments)
    if parts and parts[0].type == "ident" and parts[0].lower_value == "from":
        return UNKNOWN  # relative colour syntax
    alpha = None
    for index in range(len(parts)):
        if _is_literal(parts[index], "/"):
            if index != len(parts) - 2:
                return INVALID
            alpha = parts[index + 1]
            parts = parts[:index]
            break
    if len(parts) != len(channel_categories):
        return INVALID
    verdict = VALID
    for index in range(len(parts)):
        verdict = _worst(verdict, _channel(parts[index], channel_categories[index]))
    if alpha is not None:
        verdict = _worst(verdict, _channel(alpha, _NUMBER_PERCENTAGE))
    return verdict


def _single_tokens(groups):
    """The one significant token of each group, or None when a group has none or several."""
    tokens = []
    for group in groups:
        parts = _significant(group)
        if len(parts) != 1:
            return None
        tokens.append(parts[0])
    return tokens


def _legacy_kind(token):
    """'number', 'percentage', INVALID or UNKNOWN for a channel of the comma syntax of rgb()."""
    if token.type == "number" or token.type == "percentage":
        return token.type
    if _numeric(token, _NUMBER) == VALID:
        return "number"
    verdict = _numeric(token, _PERCENTAGE)
    if verdict == VALID:
        return "percentage"
    return verdict


def _rgb_color(arguments, depth):
    groups = _split_commas(arguments)
    if len(groups) == 1:
        return _modern_color_arguments(arguments, (_NUMBER_PERCENTAGE, _NUMBER_PERCENTAGE, _NUMBER_PERCENTAGE))
    channels = _single_tokens(groups)
    if channels is None or len(channels) not in (3, 4):
        return INVALID
    kinds = []
    for channel in channels[:3]:
        kind = _legacy_kind(channel)
        if kind == INVALID or kind == UNKNOWN:
            return kind
        kinds.append(kind)
    if kinds[0] != kinds[1] or kinds[1] != kinds[2]:
        return INVALID
    if len(channels) == 4:
        return _numeric(channels[3], _NUMBER_PERCENTAGE)
    return VALID


def _hsl_color(arguments, depth):
    groups = _split_commas(arguments)
    if len(groups) == 1:
        return _modern_color_arguments(arguments, (_NUMBER_ANGLE, _NUMBER_PERCENTAGE, _NUMBER_PERCENTAGE))
    channels = _single_tokens(groups)
    if channels is None or len(channels) not in (3, 4):
        return INVALID
    verdict = _numeric(channels[0], _NUMBER_ANGLE)
    verdict = _worst(verdict, _numeric(channels[1], _PERCENTAGE))
    verdict = _worst(verdict, _numeric(channels[2], _PERCENTAGE))
    if len(channels) == 4:
        verdict = _worst(verdict, _numeric(channels[3], _NUMBER_PERCENTAGE))
    return verdict


def _hwb_color(arguments, depth):
    return _modern_color_arguments(arguments, (_NUMBER_ANGLE, _NUMBER_PERCENTAGE, _NUMBER_PERCENTAGE))


def _lab_color(arguments, depth):
    return _modern_color_arguments(arguments, (_NUMBER_PERCENTAGE, _NUMBER_PERCENTAGE, _NUMBER_PERCENTAGE))


def _lch_color(arguments, depth):
    return _modern_color_arguments(arguments, (_NUMBER_PERCENTAGE, _NUMBER_PERCENTAGE, _NUMBER_ANGLE))


def _light_dark_color(arguments, depth):
    colors = _single_tokens(_split_commas(arguments))
    if colors is None or len(colors) != 2:
        return INVALID
    return _worst(_color(colors[0], depth), _color(colors[1], depth))


_PREDEFINED_COLOR_SPACES = frozenset({
    "srgb", "srgb-linear", "display-p3", "display-p3-linear", "a98-rgb", "prophoto-rgb", "rec2020", "xyz", "xyz-d50",
    "xyz-d65",
})


def _predefined_color(arguments, depth):
    """color(<colour space> <c1> <c2> <c3> [/ <alpha>]?)"""
    parts = _significant(arguments)
    if parts and parts[0].type == "ident" and parts[0].lower_value == "from":
        return UNKNOWN  # relative colour syntax
    if not parts or parts[0].type != "ident" or parts[0].lower_value not in _PREDEFINED_COLOR_SPACES:
        return INVALID
    return _modern_color_arguments(parts[1:], (_NUMBER_PERCENTAGE, _NUMBER_PERCENTAGE, _NUMBER_PERCENTAGE))


def _color_mix(arguments, depth):
    """color-mix([in <colour space> [<hue method> hue]?]?, <colour> <percentage>?, <colour> <percentage>?),
    each percentage before or after its colour and, when written out, from 0% to 100%."""
    groups = _split_commas(arguments)
    verdict = VALID
    method = _significant(groups[0])
    if method and method[0].type == "ident" and method[0].lower_value == "in":
        verdict = _interpolation_method(method[1:])
        groups = groups[1:]
    if len(groups) != 2:
        return INVALID
    for group in groups:
        colors = []
        percentages = []
        for part in _significant(group):
            if _is_numeric_token(part):
                percentages.append(part)
            else:
                colors.append(part)
        if len(colors) != 1 or len(percentages) > 1:
            return INVALID
        if percentages:
            percentage = percentages[0]
            if percentage.type == "percentage" and (percentage.value < 0 or percentage.value > 100):
                return INVALID
            verdict = _worst(verdict, _numeric(percentage, _PERCENTAGE))
        verdict = _worst(verdict, _color(colors[0], depth))
        if verdict == INVALID:
            return INVALID
    return verdict


def _contrast_color(arguments, depth):
    parts = _significant(arguments)
    if len(parts) == 1:
        return _color(parts[0], depth)
    return UNKNOWN


_COLOR_FUNCTIONS = {
    "rgb": _rgb_color, "rgba": _rgb_color, "hsl": _hsl_color, "hsla": _hsl_color, "hwb": _hwb_color,
    "lab": _lab_color, "oklab": _lab_color, "lch": _lch_color, "oklch": _lch_color,
    "light-dark": _light_dark_color, "color": _predefined_color, "color-mix": _color_mix,
    "contrast-color": _contrast_color,
}


def _color(token, depth=0):
    kind = token.type
    if kind == "ident":
        if token.lower_value in _COLOR_KEYWORDS:
            return VALID
        if token.lower_value == _QUIRKS_ONLY_COLOR:
            return QUIRKS_ONLY
        return INVALID
    if kind == "hash":
        if len(token.value) in (3, 4, 6, 8) and _is_hex(token.value):
            return VALID
        return INVALID
    if kind == "function":
        grammar = _COLOR_FUNCTIONS.get(token.lower_name)
        if grammar is None:
            return INVALID
        if depth >= _COLOR_DEPTH_CAP:
            return UNKNOWN
        return grammar(token.arguments, depth + 1)
    return INVALID


# ---- property grammars ----------------------------------------------------------------------------
# Each takes the value's significant tokens (never empty, never a lone CSS-wide keyword).

def _keyword_grammar(keywords):
    def grammar(parts):
        if len(parts) == 1 and parts[0].type == "ident" and parts[0].lower_value in keywords:
            return VALID
        return INVALID
    return grammar


def _identifiers(parts):
    """The lowercase values of parts if all are identifiers, else None."""
    names = []
    for part in parts:
        if part.type != "ident":
            return None
        names.append(part.lower_value)
    return names


_DISPLAY_KEYWORDS = frozenset({
    "-webkit-box", "-webkit-flex", "-webkit-inline-box", "-webkit-inline-flex", "block", "contents", "flex", "flow",
    "flow-root", "grid", "inline", "inline-block", "inline-flex", "inline-grid", "inline-table", "list-item", "math",
    "none", "ruby", "ruby-text", "table", "table-caption", "table-cell", "table-column", "table-column-group",
    "table-footer-group", "table-header-group", "table-row", "table-row-group",
})
# Every multi-keyword display value Chrome 157 accepts (all orderings of 2 and 3 of the keywords above).
_DISPLAY_COMBINATIONS = frozenset({
    "block flex", "block flow", "block flow-root", "block grid", "block list-item", "block math", "block ruby",
    "block table", "flex block", "flex inline", "flow block", "flow inline", "flow list-item", "flow-root block",
    "flow-root inline", "flow-root list-item", "grid block", "grid inline", "inline flex", "inline flow",
    "inline flow-root", "inline grid", "inline list-item", "inline math", "inline ruby", "inline table",
    "list-item block", "list-item flow", "list-item flow-root", "list-item inline", "math block", "math inline",
    "ruby block", "ruby inline", "table block", "table inline", "block flow list-item", "block flow-root list-item",
    "block list-item flow", "block list-item flow-root", "flow block list-item", "flow inline list-item",
    "flow list-item block", "flow list-item inline", "flow-root block list-item", "flow-root inline list-item",
    "flow-root list-item block", "flow-root list-item inline", "inline flow list-item", "inline flow-root list-item",
    "inline list-item flow", "inline list-item flow-root", "list-item block flow", "list-item block flow-root",
    "list-item flow block", "list-item flow inline", "list-item flow-root block", "list-item flow-root inline",
    "list-item inline flow", "list-item inline flow-root",
})


def _display(parts):
    names = _identifiers(parts)
    if names is None:
        return INVALID
    if len(names) == 1:
        if names[0] in _DISPLAY_KEYWORDS:
            return VALID
        return INVALID
    if " ".join(names) in _DISPLAY_COMBINATIONS:
        return VALID
    return INVALID


def _single(parts, slot):
    if len(parts) != 1:
        return INVALID
    return slot(parts[0])


def _number_or_percentage(token):
    return _numeric(token, _NUMBER_PERCENTAGE)


def _z_index(parts):
    if len(parts) != 1:
        return INVALID
    token = parts[0]
    if token.type == "ident":
        return VALID if token.lower_value == "auto" else INVALID
    return _numeric(token, _NUMBER, integer=True)


def _length_slot(keywords, nonnegative, quirk, unknown_functions=frozenset(), accepted=_LENGTH_PERCENTAGE):
    """A slot taking keywords or a length (percentage) and, when quirk, a bare number in quirks mode."""
    def slot(token):
        kind = token.type
        if kind == "ident":
            return VALID if token.lower_value in keywords else INVALID
        if kind == "function" and token.lower_name in unknown_functions:
            return UNKNOWN
        return _numeric(token, accepted, nonnegative=nonnegative, unitless_zero=True, quirk=quirk)
    return slot


_SIZE_KEYWORDS = frozenset({
    "-webkit-fill-available", "-webkit-fit-content", "-webkit-max-content", "-webkit-min-content", "fit-content",
    "max-content", "min-content", "stretch",
})
_SIZE_FUNCTIONS = frozenset({"anchor-size", "calc-size"})
_size_slot = _length_slot(_SIZE_KEYWORDS | {"auto"}, True, True, _SIZE_FUNCTIONS)
_max_size_slot = _length_slot(_SIZE_KEYWORDS | {"none"}, True, True, _SIZE_FUNCTIONS)
_inset_slot = _length_slot(frozenset({"auto"}), False, True, frozenset({"anchor", "anchor-size"}))
# The inset shorthand has no unitless quirk.
_inset_shorthand_slot = _length_slot(frozenset({"auto"}), False, False, frozenset({"anchor", "anchor-size"}))
_margin_slot = _length_slot(frozenset({"auto"}), False, True, frozenset({"anchor-size"}))
_FONT_SIZE_KEYWORDS = frozenset({
    "-webkit-xxx-large", "large", "larger", "math", "medium", "small", "smaller", "x-large", "x-small", "xx-large",
    "xx-small", "xxx-large",
})
_font_size_slot = _length_slot(_FONT_SIZE_KEYWORDS, True, True)
_letter_spacing_slot = _length_slot(frozenset({"normal"}), False, True)
_perspective_slot = _length_slot(frozenset({"none"}), True, False, accepted=_LENGTH)
_line_height_slot = _length_slot(frozenset({"normal"}), True, False, accepted=_NUMBER_LENGTH_PERCENTAGE)
_font_size_shorthand_slot = _length_slot(_FONT_SIZE_KEYWORDS, True, False)


def _slot_grammar(slot):
    def grammar(parts):
        return _single(parts, slot)
    return grammar


def _inset(parts):
    if len(parts) > 4:
        return INVALID
    verdict = VALID
    for part in parts:
        verdict = _worst(verdict, _inset_shorthand_slot(part))
    return verdict


_TEXT_INDENT_KEYWORDS = frozenset({"hanging", "each-line"})


def _text_indent(parts):
    verdict = None
    seen = set()
    for part in parts:
        if part.type == "ident" and part.lower_value in _TEXT_INDENT_KEYWORDS:
            if part.lower_value in seen:
                return INVALID
            seen.add(part.lower_value)
        elif verdict is None:
            verdict = _numeric(part, _LENGTH_PERCENTAGE, unitless_zero=True, quirk=True)
        else:
            return INVALID
    if verdict is None:
        return INVALID
    return verdict


def _color_property(quirk):
    def grammar(parts):
        if len(parts) != 1:
            return INVALID
        verdict = _color(parts[0])
        if verdict == INVALID and quirk and _is_quirky_hex_color(parts[0]):
            return QUIRKS_ONLY
        return verdict
    return grammar


# The generic families that cannot start a family name of several identifiers (Chrome 157).
_GENERIC_FAMILIES = frozenset({
    "serif", "sans-serif", "cursive", "fantasy", "monospace", "system-ui", "math", "-webkit-body",
})


def _font_families(parts):
    """font-family: comma-separated strings or runs of identifiers."""
    family = []
    families = [family]
    for part in parts:
        if _is_literal(part, ","):
            family = []
            families.append(family)
        else:
            family.append(part)
    for family in families:
        if not family:
            return INVALID
        if len(family) == 1 and family[0].type == "string":
            continue
        names = _identifiers(family)
        if names is None:
            return INVALID
        if len(names) == 1:
            if names[0] in _CSS_WIDE_KEYWORDS or names[0] == "default":
                return INVALID
        elif names[0] in _GENERIC_FAMILIES:
            return INVALID
    return VALID


def _clip(parts):
    if len(parts) != 1:
        return INVALID
    token = parts[0]
    if token.type == "ident":
        return VALID if token.lower_value == "auto" else INVALID
    if token.type != "function" or token.lower_name != "rect":
        return INVALID
    groups = _split_commas(token.arguments)
    if len(groups) == 1:
        edges = _significant(groups[0])
    else:
        edges = _single_tokens(groups)
        if edges is None:
            return INVALID
    if len(edges) != 4:
        return INVALID
    verdict = VALID
    for edge in edges:
        if edge.type == "ident" and edge.lower_value == "auto":
            continue
        verdict = _worst(verdict, _numeric(edge, _LENGTH, unitless_zero=True, quirk=True))
    return verdict


def _translate(parts):
    if len(parts) == 1 and parts[0].type == "ident":
        return VALID if parts[0].lower_value == "none" else INVALID
    if len(parts) > 3:
        return INVALID
    verdict = VALID
    for index in range(len(parts)):
        accepted = _LENGTH if index == 2 else _LENGTH_PERCENTAGE
        verdict = _worst(verdict, _numeric(parts[index], accepted, unitless_zero=True))
    return verdict


def _scale(parts):
    if len(parts) == 1 and parts[0].type == "ident":
        return VALID if parts[0].lower_value == "none" else INVALID
    if len(parts) > 3:
        return INVALID
    verdict = VALID
    for part in parts:
        verdict = _worst(verdict, _numeric(part, _NUMBER_PERCENTAGE))
    return verdict


def _comma_arguments(function, slots_by_count):
    """The verdict for a function whose comma-separated arguments are single tokens checked by the
    slots listed for their count in slots_by_count."""
    groups = _split_commas(function.arguments)
    slots = slots_by_count.get(len(groups))
    if slots is None:
        return INVALID
    arguments = _single_tokens(groups)
    if arguments is None:
        return INVALID
    verdict = VALID
    for index in range(len(arguments)):
        verdict = _worst(verdict, slots[index](arguments[index]))
    return verdict


def _length_percentage_argument(token):
    return _numeric(token, _LENGTH_PERCENTAGE, unitless_zero=True)


def _length_argument(token):
    return _numeric(token, _LENGTH, unitless_zero=True)


def _number_argument(token):
    return _numeric(token, _NUMBER)


def _angle_argument(token):
    return _numeric(token, _ANGLE, unitless_zero=True)


def _perspective_argument(token):
    if token.type == "ident" and token.lower_value == "none":
        return VALID
    return _numeric(token, _LENGTH, nonnegative=True, unitless_zero=True)


_SIXTEEN_NUMBERS = []
for _index in range(16):
    _SIXTEEN_NUMBERS.append(_number_argument)
_TRANSFORM_FUNCTIONS = {
    "matrix": {6: (_number_argument,) * 6},
    "matrix3d": {16: tuple(_SIXTEEN_NUMBERS)},
    "translate": {1: (_length_percentage_argument,), 2: (_length_percentage_argument, _length_percentage_argument)},
    "translatex": {1: (_length_percentage_argument,)},
    "translatey": {1: (_length_percentage_argument,)},
    "translatez": {1: (_length_argument,)},
    "translate3d": {3: (_length_percentage_argument, _length_percentage_argument, _length_argument)},
    "scale": {1: (_number_or_percentage,), 2: (_number_or_percentage, _number_or_percentage)},
    "scalex": {1: (_number_or_percentage,)},
    "scaley": {1: (_number_or_percentage,)},
    "scalez": {1: (_number_or_percentage,)},
    "scale3d": {3: (_number_or_percentage, _number_or_percentage, _number_or_percentage)},
    "rotate": {1: (_angle_argument,)},
    "rotatex": {1: (_angle_argument,)},
    "rotatey": {1: (_angle_argument,)},
    "rotatez": {1: (_angle_argument,)},
    "rotate3d": {4: (_number_argument, _number_argument, _number_argument, _angle_argument)},
    "skew": {1: (_angle_argument,), 2: (_angle_argument, _angle_argument)},
    "skewx": {1: (_angle_argument,)},
    "skewy": {1: (_angle_argument,)},
    "perspective": {1: (_perspective_argument,)},
}


def _transform(parts):
    if len(parts) == 1 and parts[0].type == "ident":
        return VALID if parts[0].lower_value == "none" else INVALID
    verdict = VALID
    for part in parts:
        if part.type != "function":
            return INVALID
        slots_by_count = _TRANSFORM_FUNCTIONS.get(part.lower_name)
        if slots_by_count is None:
            return INVALID
        verdict = _worst(verdict, _comma_arguments(part, slots_by_count))
    return verdict


def _is_url(token):
    return token.type == "url" or token.type == "function" and token.lower_name == "url"


def _url_verdict(token):
    """A url token, or url() holding one string."""
    if token.type == "url":
        return VALID
    parts = _significant(token.arguments)
    if len(parts) == 1 and parts[0].type == "string":
        return VALID
    return UNKNOWN


def _shadow(parts):
    """A text shadow: an optional colour before or after 2 or 3 lengths, the blur not negative."""
    lengths = []
    colors = []
    color_positions = []
    for index in range(len(parts)):
        part = parts[index]
        if part.type in ("number", "dimension") or part.type == "function" and _is_math_function(part):
            lengths.append(part)
        else:
            colors.append(part)
            color_positions.append(index)
    if len(lengths) < 2 or len(lengths) > 3 or len(colors) > 1:
        return INVALID
    if colors and color_positions[0] not in (0, len(parts) - 1):
        return INVALID
    verdict = VALID
    for index in range(len(lengths)):
        verdict = _worst(verdict, _numeric(lengths[index], _LENGTH, nonnegative=index == 2, unitless_zero=True))
    if colors:
        verdict = _worst(verdict, _color(colors[0]))
    return verdict


def _split_parts(parts, character):
    groups = [[]]
    for part in parts:
        if _is_literal(part, character):
            groups.append([])
        else:
            groups[-1].append(part)
    return groups


def _text_shadow(parts):
    if len(parts) == 1 and parts[0].type == "ident" and parts[0].lower_value == "none":
        return VALID
    verdict = VALID
    for shadow in _split_parts(parts, ","):
        verdict = _worst(verdict, _shadow(shadow))
    return verdict


def _filter_amount(arguments):
    parts = _significant(arguments)
    if not parts:
        return VALID
    if len(parts) != 1:
        return INVALID
    return _numeric(parts[0], _NUMBER_PERCENTAGE, nonnegative=True)


def _filter_blur(arguments):
    parts = _significant(arguments)
    if not parts:
        return VALID
    if len(parts) != 1:
        return INVALID
    return _numeric(parts[0], _LENGTH, nonnegative=True, unitless_zero=True)


def _filter_hue_rotate(arguments):
    parts = _significant(arguments)
    if not parts:
        return VALID
    if len(parts) != 1:
        return INVALID
    return _numeric(parts[0], _ANGLE, unitless_zero=True)


def _filter_drop_shadow(arguments):
    if len(_split_commas(arguments)) != 1:
        return INVALID
    return _shadow(_significant(arguments))


_FILTER_FUNCTIONS = {
    "blur": _filter_blur, "brightness": _filter_amount, "contrast": _filter_amount, "grayscale": _filter_amount,
    "invert": _filter_amount, "opacity": _filter_amount, "saturate": _filter_amount, "sepia": _filter_amount,
    "hue-rotate": _filter_hue_rotate, "drop-shadow": _filter_drop_shadow,
}


def _filter(parts):
    if len(parts) == 1 and parts[0].type == "ident":
        return VALID if parts[0].lower_value == "none" else INVALID
    verdict = VALID
    for part in parts:
        if _is_url(part):
            verdict = _worst(verdict, _url_verdict(part))
        elif part.type == "function" and part.lower_name in _FILTER_FUNCTIONS:
            verdict = _worst(verdict, _FILTER_FUNCTIONS[part.lower_name](part.arguments))
        else:
            return INVALID
        if verdict == INVALID:
            return INVALID
    return verdict


def _box_list(keywords, pairs):
    """A comma-separated list of layers, each one keyword or one of the pairs."""
    def grammar(parts):
        for layer in _split_parts(parts, ","):
            names = _identifiers(layer)
            if names is None or len(names) == 1 and names[0] not in keywords:
                return INVALID
            if len(names) != 1 and " ".join(names) not in pairs:
                return INVALID
        return VALID
    return grammar


def _overflow(parts):
    if len(parts) > 2:
        return INVALID
    for part in parts:
        if part.type != "ident" or part.lower_value not in _OVERFLOW_KEYWORDS:
            return INVALID
    return VALID


# ---- images ---------------------------------------------------------------------------------------

def _is_numeric_token(token):
    kind = token.type
    return kind in ("number", "percentage", "dimension") or kind == "function" and _is_math_function(token)


_HORIZONTAL = frozenset({"left", "right"})
_VERTICAL = frozenset({"top", "bottom"})
_POSITION_KEYWORDS = frozenset({"left", "right", "top", "bottom", "center"})


def _position_axis(token):
    """'x', 'y', 'center' or 'offset' for a part of a <position>, or None."""
    if token.type == "ident":
        name = token.lower_value
        if name in _HORIZONTAL:
            return "x"
        if name in _VERTICAL:
            return "y"
        if name == "center":
            return "center"
        return None
    if _is_numeric_token(token):
        return "offset"
    return None


# The shapes of a <position> by the axes of its parts: one value, two, and the four-value form;
# a background position also takes the three-value form (https://drafts.csswg.org/css-values-4/#position).
_POSITION_SHAPES = frozenset({
    ("x",), ("y",), ("center",), ("offset",),
    ("x", "y"), ("x", "center"), ("x", "offset"), ("center", "y"), ("center", "center"), ("center", "offset"),
    ("offset", "y"), ("offset", "center"), ("offset", "offset"), ("y", "x"), ("y", "center"), ("center", "x"),
    ("x", "offset", "y", "offset"), ("y", "offset", "x", "offset"),
})
_THREE_VALUE_POSITION_SHAPES = frozenset({
    ("x", "offset", "y"), ("x", "offset", "center"), ("x", "y", "offset"), ("center", "y", "offset"),
    ("y", "offset", "x"), ("y", "offset", "center"), ("y", "x", "offset"), ("center", "x", "offset"),
})


def _position(parts, three_values):
    shape = []
    verdict = VALID
    for part in parts:
        axis = _position_axis(part)
        if axis is None:
            return INVALID
        shape.append(axis)
        if axis == "offset":
            verdict = _worst(verdict, _numeric(part, _LENGTH_PERCENTAGE, unitless_zero=True))
    shape = tuple(shape)
    if shape in _POSITION_SHAPES or three_values and shape in _THREE_VALUE_POSITION_SHAPES:
        return verdict
    return INVALID


def _split_at_keyword(parts, keyword):
    """(before, after) around the first identifier keyword, or (parts, None)."""
    for index in range(len(parts)):
        if parts[index].type == "ident" and parts[index].lower_value == keyword:
            return parts[:index], parts[index + 1:]
    return parts, None


_RECTANGULAR_COLOR_SPACES = frozenset({
    "srgb", "srgb-linear", "display-p3", "display-p3-linear", "a98-rgb", "prophoto-rgb", "rec2020", "lab", "oklab",
    "xyz", "xyz-d50", "xyz-d65",
})
_POLAR_COLOR_SPACES = frozenset({"hsl", "hwb", "lch", "oklch"})
_HUE_METHODS = frozenset({"shorter", "longer", "increasing", "decreasing"})


def _interpolation_method(parts):
    """The verdict for "in <colour space> [<hue method> hue]?" (without the "in")."""
    names = _identifiers(parts)
    if names is None or not names:
        return INVALID
    if len(names) == 1 and (names[0] in _RECTANGULAR_COLOR_SPACES or names[0] in _POLAR_COLOR_SPACES):
        return VALID
    if len(names) == 3 and names[0] in _POLAR_COLOR_SPACES and names[1] in _HUE_METHODS and names[2] == "hue":
        return VALID
    return INVALID


def _without_interpolation(parts):
    """(verdict of an "in ..." part, the parts before it) for the first argument of a gradient; the
    interpolation method may come first or last."""
    before, after = _split_at_keyword(parts, "in")
    if after is None:
        return VALID, parts
    if not before:
        # "in <space> [hue method hue]" first, then the rest.
        length = 1
        if len(after) >= 3 and after[1].type == "ident" and after[1].lower_value in _HUE_METHODS:
            length = 3
        return _interpolation_method(after[:length]), after[length:]
    return _interpolation_method(after), before


def _color_stops(groups, position_categories, hints):
    """A colour-stop list: each group a colour with up to two positions, or (when hints) a lone
    position between two colour stops."""
    verdict = VALID
    previous_was_hint = True
    for index in range(len(groups)):
        group = _significant(groups[index])
        if not group:
            return INVALID
        if len(group) == 1 and _is_numeric_token(group[0]):
            if not hints or previous_was_hint or index == len(groups) - 1:
                return INVALID
            verdict = _worst(verdict, _numeric(group[0], position_categories, unitless_zero=True))
            previous_was_hint = True
            continue
        if len(group) > 3:
            return INVALID
        verdict = _worst(verdict, _color(group[0]))
        for position in group[1:]:
            verdict = _worst(verdict, _numeric(position, position_categories, unitless_zero=True))
        previous_was_hint = False
        if verdict == INVALID:
            return INVALID
    return verdict


def _is_color_stop_group(group):
    """Whether a gradient's first argument is already a colour stop rather than its configuration."""
    parts = _significant(group)
    if not parts:
        return False
    first = parts[0]
    if first.type == "ident":
        name = first.lower_value
        return name not in ("to", "in", "at", "from") and name not in _POSITION_KEYWORDS and \
            name not in _RADIAL_KEYWORDS and name not in _LEGACY_RADIAL_SIZES
    return first.type == "hash" or first.type == "function" and first.lower_name in _COLOR_FUNCTIONS


def _linear_direction(parts):
    """The direction of linear-gradient(): an angle, or "to" one or two sides."""
    if not parts:
        return VALID
    if parts[0].type == "ident" and parts[0].lower_value == "to":
        names = _identifiers(parts[1:])
        if names is None or not names or len(names) > 2:
            return INVALID
        if len(names) == 1:
            return VALID if names[0] in _HORIZONTAL or names[0] in _VERTICAL else INVALID
        if names[0] in _HORIZONTAL and names[1] in _VERTICAL or names[0] in _VERTICAL and names[1] in _HORIZONTAL:
            return VALID
        return INVALID
    if len(parts) != 1:
        return INVALID
    return _numeric(parts[0], _ANGLE, unitless_zero=True)


def _legacy_linear_direction(parts):
    """The direction of -webkit-linear-gradient(): an angle, or one or two sides without "to"."""
    if not parts:
        return VALID
    if len(parts) == 1 and parts[0].type != "ident":
        return _numeric(parts[0], _ANGLE, unitless_zero=True)
    names = _identifiers(parts)
    if names is None or not names or len(names) > 2:
        return INVALID
    if len(names) == 1:
        return VALID if names[0] in _HORIZONTAL or names[0] in _VERTICAL else INVALID
    if names[0] in _HORIZONTAL and names[1] in _VERTICAL or names[0] in _VERTICAL and names[1] in _HORIZONTAL:
        return VALID
    return INVALID


def _gradient(arguments, configuration, stops):
    """A gradient whose first comma group may be its configuration, checked by configuration
    (taking the significant tokens), followed by colour stops checked by stops (taking the groups)."""
    groups = _split_commas(arguments)
    verdict = VALID
    if not _is_color_stop_group(groups[0]):
        if not _significant(groups[0]):
            return INVALID
        verdict = configuration(_significant(groups[0]))
        groups = groups[1:]
        if not groups:
            return INVALID
    return _worst(verdict, stops(groups))


def _linear_configuration(parts):
    verdict, rest = _without_interpolation(parts)
    return _worst(verdict, _linear_direction(rest))


def _legacy_linear_configuration(parts):
    verdict, rest = _without_interpolation(parts)
    return _worst(verdict, _legacy_linear_direction(rest))


def _linear_stops(groups):
    return _color_stops(groups, _LENGTH_PERCENTAGE, True)


def _legacy_linear_stops(groups):
    return _color_stops(groups, _LENGTH_PERCENTAGE, False)


def _angular_stops(groups):
    return _color_stops(groups, frozenset({"angle", "percentage"}), True)


_RADIAL_SHAPES = frozenset({"circle", "ellipse"})
_RADIAL_EXTENTS = frozenset({"closest-side", "closest-corner", "farthest-side", "farthest-corner"})
_RADIAL_KEYWORDS = _RADIAL_SHAPES | _RADIAL_EXTENTS


def _radial_size(parts):
    """The shape and size of radial-gradient(), in any order."""
    shapes = []
    extents = []
    sizes = []
    for part in parts:
        if part.type == "ident" and part.lower_value in _RADIAL_SHAPES:
            shapes.append(part.lower_value)
        elif part.type == "ident" and part.lower_value in _RADIAL_EXTENTS:
            extents.append(part)
        elif _is_numeric_token(part):
            sizes.append(part)
        else:
            return INVALID
    if len(shapes) > 1 or len(extents) > 1 or extents and sizes or len(sizes) > 2:
        return INVALID
    shape = shapes[0] if shapes else None
    if len(sizes) == 1 and shape != "ellipse":
        return _numeric(sizes[0], _LENGTH, nonnegative=True, unitless_zero=True)
    if len(sizes) == 2 and shape != "circle":
        verdict = _numeric(sizes[0], _LENGTH_PERCENTAGE, nonnegative=True, unitless_zero=True)
        return _worst(verdict, _numeric(sizes[1], _LENGTH_PERCENTAGE, nonnegative=True, unitless_zero=True))
    if sizes:
        return INVALID
    return VALID


def _radial_configuration(parts):
    verdict, rest = _without_interpolation(parts)
    before, position = _split_at_keyword(rest, "at")
    verdict = _worst(verdict, _radial_size(before))
    if position is not None:
        if not position:
            return INVALID
        verdict = _worst(verdict, _position(position, False))
    return verdict


_LEGACY_RADIAL_SIZES = frozenset({"closest-side", "closest-corner", "farthest-side", "farthest-corner", "contain", "cover"})


def _legacy_radial_gradient(arguments, depth):
    """-webkit-radial-gradient([<position>,]? [<shape> || <size keyword> | <length-percentage>{2}],]? stops)."""
    groups = _split_commas(arguments)
    verdict = VALID
    first = _significant(groups[0])
    if not first:
        return INVALID
    if not _is_color_stop_group(groups[0]) and _position(first, False) != INVALID:
        verdict = _position(first, False)
        groups = groups[1:]
    if groups and not _is_color_stop_group(groups[0]):
        shape = _significant(groups[0])
        names = _identifiers(shape)
        if names is not None:
            if not names or len(names) > 2:
                return INVALID
            shapes = 0
            sizes = 0
            for name in names:
                if name in _RADIAL_SHAPES:
                    shapes += 1
                elif name in _LEGACY_RADIAL_SIZES:
                    sizes += 1
                else:
                    return INVALID
            if shapes > 1 or sizes > 1:
                return INVALID
        elif len(shape) == 2:
            for size in shape:
                verdict = _worst(verdict, _numeric(size, _LENGTH_PERCENTAGE, nonnegative=True, unitless_zero=True))
        else:
            return INVALID
        groups = groups[1:]
    if not groups:
        return INVALID
    return _worst(verdict, _legacy_linear_stops(groups))


def _conic_configuration(parts):
    verdict, rest = _without_interpolation(parts)
    if rest and rest[0].type == "ident" and rest[0].lower_value == "from":
        if len(rest) < 2:
            return INVALID
        verdict = _worst(verdict, _numeric(rest[1], _ANGLE, unitless_zero=True))
        rest = rest[2:]
    if rest:
        if rest[0].type != "ident" or rest[0].lower_value != "at" or len(rest) < 2:
            return INVALID
        verdict = _worst(verdict, _position(rest[1:], False))
    return verdict


def _linear_gradient(arguments, depth):
    return _gradient(arguments, _linear_configuration, _linear_stops)


def _legacy_linear_gradient(arguments, depth):
    return _gradient(arguments, _legacy_linear_configuration, _legacy_linear_stops)


def _radial_gradient(arguments, depth):
    return _gradient(arguments, _radial_configuration, _linear_stops)


def _conic_gradient(arguments, depth):
    return _gradient(arguments, _conic_configuration, _angular_stops)


_WEBKIT_GRADIENT_AXES = (frozenset({"left", "center", "right"}), frozenset({"top", "center", "bottom"}))


def _webkit_gradient_point(group):
    """A point of -webkit-gradient(): x then y, each a keyword of its axis, a number or a percentage."""
    parts = _significant(group)
    if len(parts) != 2:
        return INVALID
    for index in range(2):
        part = parts[index]
        if part.type == "ident":
            if part.lower_value not in _WEBKIT_GRADIENT_AXES[index]:
                return INVALID
        elif part.type == "function":
            return UNKNOWN
        elif part.type not in ("number", "percentage"):
            return INVALID
    return VALID


def _webkit_gradient_stop(group):
    parts = _significant(group)
    if len(parts) != 1 or parts[0].type != "function":
        return INVALID
    name = parts[0].lower_name
    arguments = _split_commas(parts[0].arguments)
    if name == "from" or name == "to":
        stop = _single_tokens(arguments)
        if stop is None or len(stop) != 1:
            return INVALID
        return _color(stop[0])
    if name == "color-stop":
        stop = _single_tokens(arguments)
        if stop is None or len(stop) != 2:
            return INVALID
        if stop[0].type == "function":
            offset = UNKNOWN
        elif stop[0].type in ("number", "percentage"):
            offset = VALID
        else:
            return INVALID
        return _worst(offset, _color(stop[1]))
    return INVALID


def _webkit_gradient(arguments, depth):
    """-webkit-gradient(linear, point, point, stops...) or (radial, point, radius, point, radius, stops...)."""
    groups = _split_commas(arguments)
    kind = _identifiers(_significant(groups[0]))
    if kind == ["linear"]:
        geometry = (_webkit_gradient_point, _webkit_gradient_point)
    elif kind == ["radial"]:
        geometry = (_webkit_gradient_point, _webkit_gradient_radius, _webkit_gradient_point, _webkit_gradient_radius)
    else:
        return INVALID
    if len(groups) < 1 + len(geometry):
        return INVALID
    verdict = VALID
    for index in range(len(geometry)):
        verdict = _worst(verdict, geometry[index](groups[1 + index]))
    for group in groups[1 + len(geometry):]:
        verdict = _worst(verdict, _webkit_gradient_stop(group))
    return verdict


def _webkit_gradient_radius(group):
    parts = _significant(group)
    if len(parts) != 1:
        return INVALID
    if parts[0].type == "number":
        return VALID
    return UNKNOWN if parts[0].type == "function" else INVALID


_RESOLUTION = frozenset({"resolution"})


def _image_set(arguments, depth):
    """image-set(): options of an image or string, then an optional resolution and type()."""
    verdict = VALID
    for group in _split_commas(arguments):
        parts = _significant(group)
        if not parts:
            return INVALID
        first = parts[0]
        if first.type == "string":
            option = VALID
        elif first.type == "url" or first.type == "function":
            option = _image(first, depth)
        else:
            return INVALID
        resolution_seen = False
        type_seen = False
        for part in parts[1:]:
            if part.type == "function" and part.lower_name == "type":
                mime_type = _significant(part.arguments)
                if type_seen or len(mime_type) != 1 or mime_type[0].type != "string":
                    return INVALID
                type_seen = True
            elif resolution_seen:
                return INVALID
            else:
                resolution_seen = True
                option = _worst(option, _numeric(part, _RESOLUTION))
        verdict = _worst(verdict, option)
    return verdict


def _image_function(arguments, depth):
    """image(): Chrome takes only a colour."""
    parts = _significant(arguments)
    if len(parts) == 1 and _color(parts[0], depth) != INVALID:
        return _color(parts[0], depth)
    return UNKNOWN


def _unfollowed_image(arguments, depth):
    return UNKNOWN


_IMAGE_FUNCTIONS = {
    "linear-gradient": _linear_gradient, "repeating-linear-gradient": _linear_gradient,
    "-webkit-linear-gradient": _legacy_linear_gradient, "-webkit-repeating-linear-gradient": _legacy_linear_gradient,
    "radial-gradient": _radial_gradient, "repeating-radial-gradient": _radial_gradient,
    "-webkit-radial-gradient": _legacy_radial_gradient, "-webkit-repeating-radial-gradient": _legacy_radial_gradient,
    "conic-gradient": _conic_gradient, "repeating-conic-gradient": _conic_gradient,
    "-webkit-gradient": _webkit_gradient,
    "image-set": _image_set, "-webkit-image-set": _image_set,
    "image": _image_function, "-webkit-cross-fade": _unfollowed_image,
}


def _image(token, depth=0):
    if token.type == "url":
        return VALID
    if token.type != "function":
        return INVALID
    if token.lower_name == "url":
        return _url_verdict(token)
    grammar = _IMAGE_FUNCTIONS.get(token.lower_name)
    if grammar is None:
        return INVALID
    if depth >= _COLOR_DEPTH_CAP:
        return UNKNOWN
    return grammar(token.arguments, depth + 1)


def _image_or_none(token):
    if token.type == "ident":
        return VALID if token.lower_value == "none" else INVALID
    return _image(token)


def _background_image(parts):
    verdict = VALID
    for layer in _split_parts(parts, ","):
        if len(layer) != 1:
            return INVALID
        verdict = _worst(verdict, _image_or_none(layer[0]))
        if verdict == INVALID:
            return INVALID
    return verdict


# ---- background and mask layers -------------------------------------------------------------------

_REPEAT_DOUBLE = frozenset({"repeat", "space", "round", "no-repeat"})
_SIZE_KEYWORDS_ALONE = frozenset({"cover", "contain"})


def _background_size(parts):
    if len(parts) == 1 and parts[0].type == "ident" and parts[0].lower_value in _SIZE_KEYWORDS_ALONE:
        return VALID
    if not parts or len(parts) > 2:
        return INVALID
    verdict = VALID
    for part in parts:
        if part.type == "ident" and part.lower_value == "auto":
            continue
        verdict = _worst(verdict, _numeric(part, _LENGTH_PERCENTAGE, nonnegative=True, unitless_zero=True))
    return verdict


def _is_color_token(token):
    kind = token.type
    if kind == "ident":
        return token.lower_value in _COLOR_KEYWORDS or token.lower_value == _QUIRKS_ONLY_COLOR
    return kind == "hash" or kind == "function" and token.lower_name in _COLOR_FUNCTIONS


def _is_position_part(token):
    return _is_numeric_token(token) or token.type == "ident" and token.lower_value in _POSITION_KEYWORDS


def _is_size_part(token):
    return _is_numeric_token(token) or token.type == "ident" and token.lower_value in ("auto", "cover", "contain")


def _position_and_size(layer, index):
    """(verdict, index of its last token) for the position starting at layer[index] and its
    optional "/ size"."""
    end = index
    while end + 1 < len(layer) and _is_position_part(layer[end + 1]):
        end += 1
    verdict = _position(layer[index:end + 1], True)
    if end + 1 < len(layer) and _is_literal(layer[end + 1], "/"):
        size_end = end + 2
        while size_end < len(layer) and _is_size_part(layer[size_end]):
            size_end += 1
        verdict = _worst(verdict, _background_size(layer[end + 2:size_end]))
        end = max(size_end - 1, end + 1)
    return verdict, end


# How many times a component may appear in one layer; the others appear at most once.
_COMPONENT_LIMITS = {"box": 2}


def _layers(parts, keyword_components, clip_only_boxes, color_allowed):
    """A background or mask shorthand: comma-separated layers of components in any order
    (keyword_components maps a keyword to its component); the last layer may also hold a colour
    when color_allowed."""
    layers = _split_parts(parts, ",")
    verdict = VALID
    for layer_index in range(len(layers)):
        layer = layers[layer_index]
        if not layer:
            return INVALID
        seen = {}
        index = 0
        while index < len(layer):
            token = layer[index]
            if token.type == "ident" and token.lower_value in keyword_components:
                component = keyword_components[token.lower_value]
            elif _is_numeric_token(token):
                component = "position"
            elif color_allowed and _is_color_token(token):
                component = "color"
            elif token.type == "url" or token.type == "function":
                component = "image"
            else:
                return INVALID
            if component == "position":
                part_verdict, index = _position_and_size(layer, index)
            elif component == "repeat":
                part_verdict = VALID
                following = index + 1
                if token.lower_value in _REPEAT_DOUBLE and following < len(layer) and \
                        layer[following].type == "ident" and layer[following].lower_value in _REPEAT_DOUBLE:
                    index = following
            elif component == "color":
                if layer_index != len(layers) - 1:
                    return INVALID
                part_verdict = _color(token)
            elif component == "image":
                part_verdict = _image_or_none(token)
            else:
                part_verdict = VALID
            if component == "box" and token.lower_value in clip_only_boxes:
                component = "clip-only box"
                following = index + 1
                if following < len(layer) and layer[following].type == "ident" and \
                        (token.lower_value, layer[following].lower_value) in _CRASHING_CLIP_PAIRS:
                    # Chrome 157 parses "border-area text" here and then crashes the page.
                    part_verdict = UNKNOWN
                    index = following
            count = seen.get(component, 0) + 1
            if count > _COMPONENT_LIMITS.get(component, 1):
                return INVALID
            seen[component] = count
            # Two boxes are the origin and the clip; text, border-area and no-clip can only be the clip.
            if seen.get("box", 0) + seen.get("clip-only box", 0) > 2:
                return INVALID
            verdict = _worst(verdict, part_verdict)
            if verdict == INVALID:
                return INVALID
            index += 1
    return verdict


_POSITION_COMPONENTS = {"left": "position", "right": "position", "top": "position", "bottom": "position",
                        "center": "position"}
_REPEAT_COMPONENTS = {"repeat-x": "repeat", "repeat-y": "repeat", "repeat": "repeat", "space": "repeat",
                      "round": "repeat", "no-repeat": "repeat"}
_BACKGROUND_COMPONENTS = {"none": "image", "scroll": "attachment", "fixed": "attachment", "local": "attachment",
                          "border-box": "box", "padding-box": "box", "content-box": "box", "text": "box",
                          "border-area": "box"}
_BACKGROUND_CLIP_ONLY_BOXES = frozenset({"text", "border-area"})
_CRASHING_CLIP_PAIRS = frozenset({("border-area", "text"), ("text", "border-area")})
_BACKGROUND_COMPONENTS.update(_POSITION_COMPONENTS)
_BACKGROUND_COMPONENTS.update(_REPEAT_COMPONENTS)
_MASK_COMPONENTS = {"none": "image", "border-box": "box", "padding-box": "box", "content-box": "box",
                    "fill-box": "box", "stroke-box": "box", "view-box": "box", "no-clip": "box", "add": "composite",
                    "subtract": "composite", "intersect": "composite", "exclude": "composite", "alpha": "mode",
                    "luminance": "mode", "match-source": "mode"}
_MASK_CLIP_ONLY_BOXES = frozenset({"no-clip"})
_MASK_COMPONENTS.update(_POSITION_COMPONENTS)
_MASK_COMPONENTS.update(_REPEAT_COMPONENTS)


def _background(parts):
    return _layers(parts, _BACKGROUND_COMPONENTS, _BACKGROUND_CLIP_ONLY_BOXES, True)


def _mask(parts):
    return _layers(parts, _MASK_COMPONENTS, _MASK_CLIP_ONLY_BOXES, False)


# ---- content ----------------------------------------------------------------------------------------

_QUOTE_KEYWORDS = frozenset({"open-quote", "close-quote", "no-open-quote", "no-close-quote"})
_RESERVED_COUNTER_NAMES = _CSS_WIDE_KEYWORDS | {"default"}


def _counter(token):
    """counter(<name>, <style>?) or counters(<name>, <string>, <style>?)."""
    groups = _split_commas(token.arguments)
    arguments = _single_tokens(groups)
    if arguments is None:
        return INVALID
    if token.lower_name == "counter":
        expected = ("ident", "style")
    else:
        expected = ("ident", "string", "style")
    if len(arguments) not in (len(expected) - 1, len(expected)):
        return INVALID
    verdict = VALID
    for index in range(len(arguments)):
        argument = arguments[index]
        if expected[index] == "style":
            if argument.type == "function":
                verdict = UNKNOWN  # symbols()
            elif argument.type != "ident" or argument.lower_value in _RESERVED_COUNTER_NAMES:
                return INVALID
        elif argument.type != expected[index]:
            return INVALID
        elif expected[index] == "ident" and argument.lower_value in _RESERVED_COUNTER_NAMES:
            return INVALID
    return verdict


def _content_item(token):
    kind = token.type
    if kind == "string":
        return VALID
    if kind == "ident":
        return VALID if token.lower_value in _QUOTE_KEYWORDS else INVALID
    if kind == "function" and token.lower_name in ("counter", "counters"):
        return _counter(token)
    return _image(token)


def _content(parts):
    """normal | none | [<content-replacement> | <content-list>] [/ [<string> | <counter>]+]?"""
    main, alternative = _split_at_slash(parts)
    if len(main) == 1 and main[0].type == "ident" and main[0].lower_value in ("normal", "none"):
        return VALID if alternative is None else INVALID
    if not main:
        return INVALID
    verdict = VALID
    for item in main:
        verdict = _worst(verdict, _content_item(item))
        if verdict == INVALID:
            return INVALID
    if alternative is None:
        return verdict
    if not alternative:
        return INVALID
    for item in alternative:
        if item.type == "string":
            continue
        if item.type == "function" and item.lower_name in ("counter", "counters"):
            verdict = _worst(verdict, _counter(item))
        else:
            return INVALID
    return verdict


def _split_at_slash(parts):
    """(before, after) the only top-level "/", or (parts, None); more than one "/" gives an
    after that is never valid."""
    groups = _split_parts(parts, "/")
    if len(groups) == 1:
        return parts, None
    if len(groups) > 2:
        return groups[0], []
    return groups[0], groups[1]


# ---- font -------------------------------------------------------------------------------------------

_SYSTEM_FONTS = frozenset({
    "caption", "icon", "menu", "message-box", "small-caption", "status-bar", "-webkit-control",
    "-webkit-mini-control", "-webkit-small-control",
})
_FONT_STYLE_KEYWORDS = frozenset({"italic", "oblique"})
_FONT_VARIANT_KEYWORDS = frozenset({"small-caps"})
_FONT_WEIGHT_KEYWORDS = frozenset({"bold", "bolder", "lighter"})
_FONT_STRETCH_KEYWORDS = frozenset({
    "ultra-condensed", "extra-condensed", "condensed", "semi-condensed", "semi-expanded", "expanded",
    "extra-expanded", "ultra-expanded",
})


def _font_prefix_component(token):
    """Which of style, variant, weight or stretch a token before the font size sets, 'normal',
    or None when it is not one of them."""
    if token.type == "ident":
        name = token.lower_value
        if name == "normal":
            return "normal"
        if name in _FONT_STYLE_KEYWORDS:
            return "style"
        if name in _FONT_VARIANT_KEYWORDS:
            return "variant"
        if name in _FONT_WEIGHT_KEYWORDS:
            return "weight"
        if name in _FONT_STRETCH_KEYWORDS:
            return "stretch"
        return None
    if token.type == "number":
        return "weight"
    if token.type == "function" and _is_math_function(token):
        return "weight or size"
    return None


def _font(parts):
    """[[<style> || <variant> || <weight> || <stretch>]? <size> [/ <line-height>]? <family>] | system font."""
    if len(parts) == 1 and parts[0].type == "ident" and parts[0].lower_value in _SYSTEM_FONTS:
        return VALID
    verdict = VALID
    seen = set()
    index = 0
    while index < len(parts) and index < 4:
        component = _font_prefix_component(parts[index])
        if component is None:
            break
        if component == "weight or size":
            return UNKNOWN
        if component == "weight" and parts[index].type == "number":
            if parts[index].value < 1 or parts[index].value > 1000:
                break
        if component != "normal":
            if component in seen:
                return INVALID
            seen.add(component)
        if component == "style" and parts[index].lower_value == "oblique" and index + 1 < len(parts) and \
                parts[index + 1].type == "dimension" and _UNIT_TYPES.get(parts[index + 1].lower_unit) == _ANGLE_TYPE:
            return UNKNOWN  # oblique with an angle
        index += 1
    if index >= len(parts):
        return INVALID
    verdict = _worst(verdict, _font_size_shorthand_slot(parts[index]))
    index += 1
    if index < len(parts) and _is_literal(parts[index], "/"):
        if index + 1 >= len(parts):
            return INVALID
        verdict = _worst(verdict, _line_height_slot(parts[index + 1]))
        index += 2
    if index >= len(parts):
        return INVALID
    return _worst(verdict, _font_families(parts[index:]))


# ---- clip-path ----------------------------------------------------------------------------------------

_GEOMETRY_BOXES = frozenset({
    "border-box", "padding-box", "content-box", "margin-box", "fill-box", "stroke-box", "view-box",
})
_SHAPE_RADII = frozenset({"closest-side", "farthest-side"})


def _nonnegative_length_percentage(token):
    return _numeric(token, _LENGTH_PERCENTAGE, nonnegative=True, unitless_zero=True)


def _border_radius(parts):
    """<length-percentage [0,inf]>{1,4} [/ <length-percentage [0,inf]>{1,4}]?"""
    groups = _split_parts(parts, "/")
    if len(groups) > 2:
        return INVALID
    verdict = VALID
    for group in groups:
        if not group or len(group) > 4:
            return INVALID
        for part in group:
            verdict = _worst(verdict, _nonnegative_length_percentage(part))
    return verdict


def _inset_shape(arguments):
    parts = _significant(arguments)
    offsets, radius = _split_at_keyword(parts, "round")
    if not offsets or len(offsets) > 4:
        return INVALID
    verdict = VALID
    for offset in offsets:
        verdict = _worst(verdict, _numeric(offset, _LENGTH_PERCENTAGE, unitless_zero=True))
    if radius is not None:
        verdict = _worst(verdict, _border_radius(radius))
    return verdict


def _circle_or_ellipse(arguments, radius_count):
    parts = _significant(arguments)
    radii, position = _split_at_keyword(parts, "at")
    if len(radii) > radius_count:
        return INVALID
    if radii and len(radii) != radius_count:
        return INVALID
    verdict = VALID
    for radius in radii:
        if radius.type == "ident" and radius.lower_value in _SHAPE_RADII:
            continue
        verdict = _worst(verdict, _nonnegative_length_percentage(radius))
    if position is not None:
        if not position:
            return INVALID
        verdict = _worst(verdict, _position(position, False))
    return verdict


def _circle_shape(arguments):
    return _circle_or_ellipse(arguments, 1)


def _ellipse_shape(arguments):
    return _circle_or_ellipse(arguments, 2)


def _polygon_shape(arguments):
    """polygon([<fill-rule>]? [round <length>]?, [<length-percentage> <length-percentage>]#)"""
    groups = _split_commas(arguments)
    first = _significant(groups[0])
    verdict = VALID
    if first and first[0].type == "ident":
        if first[0].lower_value in ("nonzero", "evenodd"):
            first = first[1:]
        if first and first[0].type == "ident" and first[0].lower_value == "round":
            if len(first) != 2:
                return INVALID
            verdict = _numeric(first[1], _LENGTH, nonnegative=True, unitless_zero=True)
            first = []
        if first:
            return INVALID
        groups = groups[1:]
    if not groups:
        return INVALID
    for group in groups:
        point = _significant(group)
        if len(point) != 2:
            return INVALID
        for coordinate in point:
            verdict = _worst(verdict, _numeric(coordinate, _LENGTH_PERCENTAGE, unitless_zero=True))
    return verdict


def _unfollowed_shape(arguments):
    return UNKNOWN


_BASIC_SHAPES = {
    "inset": _inset_shape, "circle": _circle_shape, "ellipse": _ellipse_shape, "polygon": _polygon_shape,
    "path": _unfollowed_shape, "rect": _unfollowed_shape, "xywh": _unfollowed_shape, "shape": _unfollowed_shape,
}


def _clip_path(parts):
    """none | <url> | [<basic-shape> || <geometry-box>]"""
    if len(parts) == 1 and parts[0].type == "ident" and parts[0].lower_value == "none":
        return VALID
    if len(parts) == 1 and _is_url(parts[0]):
        return _url_verdict(parts[0])
    if len(parts) > 2:
        return INVALID
    verdict = VALID
    shapes = 0
    boxes = 0
    for part in parts:
        if part.type == "ident" and part.lower_value in _GEOMETRY_BOXES:
            boxes += 1
        elif part.type == "function" and part.lower_name in _BASIC_SHAPES:
            shapes += 1
            verdict = _worst(verdict, _BASIC_SHAPES[part.lower_name](part.arguments))
        else:
            return INVALID
    if shapes > 1 or boxes > 1:
        return INVALID
    return verdict


_OVERFLOW_KEYWORDS = frozenset({"auto", "clip", "hidden", "overlay", "scroll", "visible"})

_GRAMMARS = {
    "display": _display,
    "visibility": _keyword_grammar(frozenset({"visible", "hidden", "collapse"})),
    "position": _keyword_grammar(frozenset({"static", "relative", "absolute", "fixed", "sticky"})),
    "overflow": _overflow,
    "overflow-x": _keyword_grammar(_OVERFLOW_KEYWORDS),
    "overflow-y": _keyword_grammar(_OVERFLOW_KEYWORDS),
    "content-visibility": _keyword_grammar(frozenset({"visible", "auto", "hidden"})),
    "isolation": _keyword_grammar(frozenset({"auto", "isolate"})),
    "mix-blend-mode": _keyword_grammar(frozenset({
        "normal", "multiply", "screen", "overlay", "darken", "lighten", "color-dodge", "color-burn", "hard-light",
        "soft-light", "difference", "exclusion", "hue", "saturation", "color", "luminosity", "plus-lighter",
    })),
    "unicode-bidi": _keyword_grammar(frozenset({
        "normal", "embed", "isolate", "bidi-override", "isolate-override", "plaintext", "-webkit-isolate",
        "-webkit-isolate-override", "-webkit-plaintext",
    })),
    "direction": _keyword_grammar(frozenset({"ltr", "rtl"})),
    "opacity": _slot_grammar(_number_or_percentage),
    "z-index": _z_index,
    "width": _slot_grammar(_size_slot),
    "height": _slot_grammar(_size_slot),
    "min-height": _slot_grammar(_size_slot),
    "max-width": _slot_grammar(_max_size_slot),
    "max-height": _slot_grammar(_max_size_slot),
    "left": _slot_grammar(_inset_slot),
    "top": _slot_grammar(_inset_slot),
    "right": _slot_grammar(_inset_slot),
    "bottom": _slot_grammar(_inset_slot),
    "inset": _inset,
    "margin-left": _slot_grammar(_margin_slot),
    "margin-top": _slot_grammar(_margin_slot),
    "font-size": _slot_grammar(_font_size_slot),
    "line-height": _slot_grammar(_line_height_slot),
    "letter-spacing": _slot_grammar(_letter_spacing_slot),
    "perspective": _slot_grammar(_perspective_slot),
    "text-indent": _text_indent,
    "color": _color_property(True),
    "background-color": _color_property(True),
    "-webkit-text-fill-color": _color_property(False),
    "font-family": _font_families,
    "clip": _clip,
    "translate": _translate,
    "scale": _scale,
    "transform": _transform,
    "filter": _filter,
    "text-shadow": _text_shadow,
    "background-clip": _box_list(frozenset({"border-box", "padding-box", "content-box", "text", "border-area"}),
                                 frozenset({"border-area text", "text border-area"})),
    "-webkit-background-clip": _box_list(frozenset({"border-box", "padding-box", "content-box", "text"}), frozenset()),
    "background": _background,
    "background-image": _background_image,
    "content": _content,
    "font": _font,
    "clip-path": _clip_path,
    "mask": _mask,
}


def custom_property_validity(value_tokens):
    """value_tokens: a tinycss2 Declaration.value for a --name declaration (`!important` already
    removed). Chrome keeps any <declaration-value> (empty included, {} blocks anywhere) whose
    substitution functions are well formed. Returns VALID, INVALID or UNKNOWN."""
    bad, substitution, depth = _contains_substitution_or_bad_token(value_tokens)
    if bad:
        return INVALID
    return _declaration_value_verdict(value_tokens, substitution, depth)


def declaration_validity(name, value_tokens):
    """name: a lowercased property name from css_cascade.HIDING_PROPERTIES (never a --custom one);
    value_tokens: a tinycss2 Declaration.value (component values, whitespace and comments included;
    `!important` already removed by tinycss2). Returns one of the four constants."""
    bad, substitution, depth = _contains_substitution_or_bad_token(value_tokens)
    if bad:
        return INVALID
    if substitution:
        return _substitution_validity(value_tokens, depth)
    parts = _significant(value_tokens)
    if not parts:
        return INVALID
    if len(parts) == 1 and parts[0].type == "ident" and parts[0].lower_value in _CSS_WIDE_KEYWORDS:
        return VALID
    if name != "font-family" and name != "font":
        for part in parts:
            if part.type == "ident" and part.lower_value in _CSS_WIDE_KEYWORDS:
                return INVALID
    return _GRAMMARS[name](parts)
