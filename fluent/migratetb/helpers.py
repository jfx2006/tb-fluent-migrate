"""Fluent AST helpers.

The functions defined in this module offer a shorthand for defining common AST
nodes.

They take a string argument and immediately return a corresponding AST node.
(As opposed to Transforms which are AST nodes on their own and only return the
migrated AST nodes when they are evaluated by a MigrationContext.) """

from __future__ import annotations
from typing import List

from fluent.syntax import FluentParser, ast as FTL
from fluent.syntax.visitor import Transformer
from .transforms import Transform, CONCAT, COPY, COPY_PATTERN, REPLACE
from .errors import NotSupportedError, InvalidTransformError


def VARIABLE_REFERENCE(name):
    """Create an ExternalArgument expression."""

    return FTL.VariableReference(id=FTL.Identifier(name))


def MESSAGE_REFERENCE(name):
    """Create a MessageReference expression.

    If the passed name contains a `.`, we're generating
    a message reference with an attribute.
    """
    if "." in name:
        name, attribute = name.split(".")
        attribute = FTL.Identifier(attribute)
    else:
        attribute = None

    return FTL.MessageReference(
        id=FTL.Identifier(name),
        attribute=attribute,
    )


def TERM_REFERENCE(name):
    """Create a TermReference expression."""

    return FTL.TermReference(id=FTL.Identifier(name))


class IntoTranforms(Transformer):
    IMPLICIT_TRANSFORMS = ("CONCAT",)
    FORBIDDEN_TRANSFORMS = ("PLURALS",)

    def __init__(self, substitutions):
        self.substitutions = substitutions

    def visit_Junk(self, node):
        anno = node.annotations[0]
        raise InvalidTransformError(
            "Transform contains parse error: {}, at {}".format(
                anno.message, anno.span.start
            )
        )

    def visit_FunctionReference(self, node):
        name = node.id.name
        if name in self.IMPLICIT_TRANSFORMS:
            raise NotSupportedError(
                "{} may not be used with transforms_from(). It runs "
                "implicitly on all Patterns anyways.".format(name)
            )
        if name in self.FORBIDDEN_TRANSFORMS:
            raise NotSupportedError(
                "{} may not be used with transforms_from(). It requires "
                "additional logic in Python code.".format(name)
            )
        if name in ("COPY", "COPY_PATTERN", "REPLACE"):
            args = (self.into_argument(arg) for arg in node.arguments.positional)
            kwargs = {
                arg.name.name: self.into_argument(arg.value)
                for arg in node.arguments.named
            }
            if name == "COPY":
                return COPY(*args, **kwargs)
            elif name == "REPLACE":
                return REPLACE(*args, **kwargs)
            return COPY_PATTERN(*args, **kwargs)
        return self.generic_visit(node)

    def visit_Placeable(self, node):
        """If the expression is a Transform, replace this Placeable
        with the Transform it's holding.
        Transforms evaluate to Patterns, which are flattened as
        elements of Patterns in Transform.pattern_of, but only
        one level deep.
        """
        node = self.generic_visit(node)
        if isinstance(node.expression, Transform):
            return node.expression
        return node

    def visit_Pattern(self, node):
        """Replace the Pattern with CONCAT which is more accepting of its
        elements. CONCAT takes PatternElements, Expressions and other
        Patterns (e.g. returned from evaluating transforms).
        """
        node = self.generic_visit(node)
        return CONCAT(*node.elements)

    def into_argument(self, node):
        """Convert AST node into an argument to migration transforms."""
        if isinstance(node, FTL.StringLiteral):
            # Special cases for booleans which don't exist in Fluent.
            if node.value == "True":
                return True
            if node.value == "False":
                return False
            return node.value
        if isinstance(node, FTL.MessageReference):
            try:
                return self.substitutions[node.id.name]
            except KeyError:
                raise InvalidTransformError(
                    "Unknown substitution in COPY: {}".format(node.id.name)
                )
        else:
            raise InvalidTransformError(
                "Invalid argument passed to COPY: {}".format(type(node).__name__)
            )


def transforms_from(ftl, **substitutions) -> List[FTL.Message | FTL.Term]:
    """Parse FTL code into a list of Message nodes with Transforms.

    The FTL may use a fabricated COPY function inside of placeables which
    will be converted into actual COPY migration transform.

        new-key = Hardcoded text { COPY("filepath.dtd", "string.key") }

    For convenience, COPY may also refer to transforms_from's keyword
    arguments via the MessageReference syntax:

        transforms_from(\"""
        new-key = Hardcoded text { COPY(file_dtd, "string.key") }
        \""", file_dtd="very/long/path/to/a/file.dtd")

    REPLACE may also be used. The only tested use case is to do brand string
    replacements from DTD strings.

    <!ENTITY update.noUpdatesFound      "&brandShortName; is up to date">

    First define a dictionary with the replacements outside of the migrate
    function like (must be wrapped in a dict() function call):

        about_replacements = dict({
            "&brandShortName;": TERM_REFERENCE("brand-short-name"),
        })

    Note: In the TERM_REFERENCE replacement, omit the initial "-". It winds up
    in the final result somehow.

    Then, use transforms_from:

        transforms_from(\"""
    update-no-updates-found = { REPLACE(source, "update.noUpdatesFound", about_replacements) }
    \""", source=source, about_replacements=about_replacements)

    If doing multiple string migrations in a single transforms_from template,
    your replacements dictionary can have multiple key, value pairs and be used
    for all REPLACE transforms.
    """

    parser = FluentParser(with_spans=False)
    resource = parser.parse(ftl)
    return IntoTranforms(substitutions).visit(resource).body
