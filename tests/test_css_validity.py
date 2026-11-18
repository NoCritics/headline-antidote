"""headline_guard.css_validity: whether Chrome keeps a declaration of a hiding property or of a
custom property.

The expected constants in CHROME_CASES were read from Chrome 157: VALID when a standards-mode
style sheet applies the value after another one, QUIRKS_ONLY when only a quirks-mode (no doctype)
style sheet does, INVALID otherwise. CUSTOM_PROPERTY_CASES were read the same way for --o, in a
style attribute and in standards and quirks style sheets, which agreed on every row. ChromeAgreementTests
checks both tables against the installed Chrome.
"""

import importlib.util
import unittest

import tinycss2

from headline_guard.css_validity import (INVALID, QUIRKS_ONLY, UNKNOWN, VALID, custom_property_validity,
                                         declaration_validity)


def nested(opening, middle, closing, depth):
    return opening * depth + middle + closing * depth


CHROME_CASES = [
    # CSS-wide keywords alone, in any case, and mixed with other values; empty values
    ("opacity", "inherit", VALID),
    ("display", "INITIAL", VALID),
    ("color", "unset", VALID),
    ("width", "revert", VALID),
    ("visibility", "revert-layer", VALID),
    ("font-size", "revert-rule", VALID),
    ("opacity", "inherit 1", INVALID),
    ("display", "none inherit", INVALID),
    ("color", "initial, red", INVALID),
    ("font-family", "inherit a", VALID),
    ("font-family", "a, inherit", INVALID),
    ("font", "16px inherit a", VALID),
    ("font", "16px inherit", INVALID),
    ("opacity", "", INVALID),
    ("display", " ", INVALID),
    ("color", "/**/", INVALID),
    ("opacity", "default", INVALID),
    # substitution functions: only a well-formed <declaration-value> is checked
    ("display", "var(--x)", VALID),
    ("display", "var(--x, block)", VALID),
    ("display", "-webkit-var(--x, block)", INVALID),
    ("display", "VAR(--x)", VALID),
    ("opacity", "var(x)", INVALID),
    ("background-color", "var(#00ff00)", INVALID),
    ("opacity", "var(--x) !", INVALID),
    ("opacity", "var(--x, !)", INVALID),
    ("opacity", "var(--x, (!))", VALID),
    ("opacity", "{var(--x)}", VALID),
    ("opacity", "var(--x) url(a b)", INVALID),
    ("opacity", "var(--x) )", INVALID),
    ("opacity", "var(--x) (]", INVALID),
    ("opacity", "var(--)", INVALID),
    ("opacity", "var(--x 1)", INVALID),
    ("opacity", "calc(var(x))", INVALID),
    ("opacity", "inherit var(--x)", VALID),
    ("opacity", "var(--x) banana", VALID),
    ("opacity", "env(safe-area-inset-top)", VALID),
    ("opacity", "env(x -1)", INVALID),
    ("opacity", "env(1)", INVALID),
    ("opacity", "attr(data-x)", VALID),
    ("opacity", "attr('x')", INVALID),
    ("opacity", "attr(x, !)", INVALID),
    ("opacity", "if()", INVALID),
    ("opacity", "var(--y) inherit(--x)", INVALID),
    ("opacity", nested("calc(", "var(--x)", ")", 150), VALID),
    ("opacity", "if(style(--x: 1): 1; else: 0)", VALID),
    ("opacity", "attr(x type(<number>))", VALID),
    ("display", "--choose(block)", VALID),
    ("display", "--choose({a} )", INVALID),
    # math: nesting depth (functions and parentheses together), whitespace around + and -, types
    ("opacity", nested("calc(", "0", ")", 100), VALID),
    ("opacity", nested("calc(", "0", ")", 101), INVALID),
    ("opacity", "calc(" + nested("(", "0", ")", 99) + ")", VALID),
    ("opacity", "calc(" + nested("(", "0", ")", 100) + ")", INVALID),
    ("transform", "translatex(" + nested("calc(", "1px", ")", 100) + ")", VALID),
    ("transform", "translatex(" + nested("calc(", "1px", ")", 101) + ")", INVALID),
    ("width", "calc(1px+2px)", INVALID),
    ("width", "calc(1px + 2px)", VALID),
    ("width", "calc(1px -2px)", INVALID),
    ("width", "calc(1px*2)", VALID),
    ("width", "calc(1px/**/+/**/2px)", INVALID),
    ("width", "calc(1px /**/+/**/ 2px)", VALID),
    ("opacity", "calc(1px)", INVALID),
    ("opacity", "calc(1px / 1px)", VALID),
    ("opacity", "calc(50% / 1px)", VALID),
    ("opacity", "calc(50% + 0.5)", INVALID),
    ("width", "calc(1px * 1px)", INVALID),
    ("width", "calc(1px * 1px / 1px)", VALID),
    ("width", "calc(50% * 2)", VALID),
    ("width", "calc(50% / 50%)", INVALID),
    ("font-size", "calc(1em + 1)", INVALID),
    ("font-size", "min(1px, 2)", INVALID),
    ("font-size", "clamp(1px, 2vw, 3rem)", VALID),
    ("z-index", "calc(1.5)", VALID),
    ("z-index", "1.5", INVALID),
    ("z-index", "1e3", INVALID),
    ("z-index", "calc(1px)", INVALID),
    ("z-index", "sign(50%)", INVALID),
    ("opacity", "sign(1px)", VALID),
    ("opacity", "calc(sign(1s / 1hz))", INVALID),
    ("opacity", "calc(abs(1px * 1px) / 1px / 1px)", INVALID),
    ("opacity", "calc(min(1px * 1px) / 1px / 1px)", VALID),
    ("width", "round(1px)", INVALID),
    ("width", "round(up, 1px, 1px)", VALID),
    ("width", "calc(-infinity * 1px)", VALID),
    ("width", "calc(1px * -pi)", INVALID),
    ("opacity", "calc(foo)", INVALID),
    ("width", "calc(1fr)", INVALID),
    ("width", "-webkit-calc(1px + 2px)", VALID),
    ("width", "-moz-calc(1px)", INVALID),
    ("width", "1em2", INVALID),
    ("width", "1q", VALID),
    ("width", "1banana", INVALID),
    # quirks mode: unitless lengths and hashless hex colours, only where Chrome applies them
    ("width", "7", QUIRKS_ONLY),
    ("height", "7.5", QUIRKS_ONLY),
    ("left", "-7", QUIRKS_ONLY),
    ("margin-top", "7", QUIRKS_ONLY),
    ("font-size", "16", QUIRKS_ONLY),
    ("text-indent", "7", QUIRKS_ONLY),
    ("letter-spacing", "7", QUIRKS_ONLY),
    ("clip", "rect(1 2 3 4)", QUIRKS_ONLY),
    ("color", "ff0000", QUIRKS_ONLY),
    ("color", "123456", QUIRKS_ONLY),
    ("background-color", "00ff00", QUIRKS_ONLY),
    ("color", "f00", QUIRKS_ONLY),
    ("color", "-webkit-focus-ring-color", QUIRKS_ONLY),
    ("background", "-webkit-focus-ring-color", QUIRKS_ONLY),
    ("width", "-7", INVALID),
    ("inset", "7", INVALID),
    ("line-height", "7", VALID),
    ("perspective", "7", INVALID),
    ("-webkit-text-fill-color", "ff0000", INVALID),
    ("background", "fff", INVALID),
    ("color", "ff00", INVALID),
    # keyword properties
    ("display", "block", VALID),
    ("display", "-ms-flexbox", INVALID),
    ("display", "-webkit-box", VALID),
    ("display", "inline list-item", VALID),
    ("display", "block flow-root list-item", VALID),
    ("display", "block block", INVALID),
    ("display", "blok", INVALID),
    ("display", "run-in", INVALID),
    ("display", "grid-lanes", INVALID),
    ("display", "hide", INVALID),
    ("visibility", "visible", VALID),
    ("visibility", "visibl", INVALID),
    ("position", "sticky", VALID),
    ("position", "-webkit-sticky", INVALID),
    ("overflow", "hidden scroll", VALID),
    ("overflow", "0", INVALID),
    ("overflow", "-moz-scrollbars-none", INVALID),
    ("overflow-x", "clip", VALID),
    ("overflow-y", "hidden hidden", INVALID),
    ("content-visibility", "hidden", VALID),
    ("content-visibility", "banana", INVALID),
    ("isolation", "isolate", VALID),
    ("mix-blend-mode", "plus-lighter", VALID),
    ("mix-blend-mode", "plus-darker", INVALID),
    ("unicode-bidi", "-webkit-isolate", VALID),
    ("unicode-bidi", "isolate isolate", INVALID),
    ("direction", "rtl", VALID),
    ("direction", "auto", INVALID),
    # numbers, sizes, insets, margins, text-indent, line-height, letter-spacing, perspective, font-size
    ("opacity", "0.5", VALID),
    ("opacity", "50%", VALID),
    ("opacity", "-1", VALID),
    ("opacity", "1.", INVALID),
    ("opacity", "1e", INVALID),
    ("opacity", "banana", INVALID),
    ("opacity", "1 1", INVALID),
    ("width", "-moz-fit-content", INVALID),
    ("width", "-webkit-fill-available", VALID),
    ("width", "-1px", INVALID),
    ("width", "none", INVALID),
    ("width", "fit-content(1px)", INVALID),
    ("height", "stretch", VALID),
    ("height", "auto", VALID),
    ("max-width", "none", VALID),
    ("max-width", "auto", INVALID),
    ("max-height", "min-content", VALID),
    ("min-height", "4.5 rem", INVALID),
    ("left", "auto", VALID),
    ("left", "50%px", INVALID),
    ("left", "nanpx", INVALID),
    ("top", "-9999px", VALID),
    ("right", "calc(50% - 1px)", VALID),
    ("bottom", "0 0", INVALID),
    ("inset", "auto 0 0 auto", VALID),
    ("inset", "inherit 0 inherit 0", INVALID),
    ("inset", "1px 2px 3px 4px 5px", INVALID),
    ("margin-left", "auto", VALID),
    ("margin-left", "px", INVALID),
    ("margin-top", "-1em", VALID),
    ("text-indent", "-9999px hanging", VALID),
    ("text-indent", "hanging", INVALID),
    ("text-indent", "underline", INVALID),
    ("line-height", "1.5", VALID),
    ("line-height", "-1", INVALID),
    ("line-height", "auto", INVALID),
    ("line-height", "calc(1px / 50%)", VALID),
    ("letter-spacing", "normal", VALID),
    ("letter-spacing", "-0.5em", VALID),
    ("perspective", "1000px", VALID),
    ("perspective", "-1px", INVALID),
    ("perspective", "50%", INVALID),
    ("font-size", "x-large", VALID),
    ("font-size", "xxxx-large", INVALID),
    ("font-size", "-16px", INVALID),
    ("font-size", "italic", INVALID),
    ("font-size", "16px 2px", INVALID),
    ("font-size", "0", VALID),
    # colours
    ("color", "red", VALID),
    ("color", "redd", INVALID),
    ("color", "#fff", VALID),
    ("color", "#12345", INVALID),
    ("color", "#77777", INVALID),
    ("color", "rgb(0 0 0 / 50%)", VALID),
    ("color", "rgb(0, 0, 0, 0.5)", VALID),
    ("color", "rgb(0, 0%, 0)", INVALID),
    ("color", "rgb(0,0,0,)", INVALID),
    ("color", "rgb(0 0 0 0)", INVALID),
    ("color", "hsl(0, 0%, 0%)", VALID),
    ("color", "hsla(0,0,100%,0.1)", INVALID),
    ("color", "hwb(0 0% 0%)", VALID),
    ("color", "lab(50% 0 0)", VALID),
    ("color", "oklch(0.5 0.1 30deg)", VALID),
    ("color", "color(srgb 0 0 0)", VALID),
    ("color", "color(banana 0 0 0)", INVALID),
    ("color", "color-mix(in srgb, red 50%, blue)", VALID),
    ("color", "color-mix(in srgb, red 150%, blue)", INVALID),
    ("color", "light-dark(red, blue)", VALID),
    ("color", "light-dark(red)", INVALID),
    ("color", "canvastext", VALID),
    ("color", "-webkit-link", VALID),
    ("color", "ihnerit", INVALID),
    # CSS.supports accepts this one; a style sheet drops it.
    ("color", "rgba(1,2,3,.5) rgba(1,2,3,.5)", INVALID),
    ("color", "red blue", INVALID),
    ("background-color", "transparent", VALID),
    ("background-color", "none", INVALID),
    ("-webkit-text-fill-color", "transparent", VALID),
    ("-webkit-text-fill-color", "currentcolor", VALID),
    # font-family and font
    ("font-family", "a b, 'c', serif", VALID),
    ("font-family", "serif a", INVALID),
    ("font-family", "default", INVALID),
    ("font-family", "a, default", INVALID),
    ("font-family", "a,", INVALID),
    ("font-family", "proxima nova,450,normal,sans-serif", INVALID),
    ("font-family", "'a' b", INVALID),
    ("font", "16px a", VALID),
    ("font", "bold 16px/1.5 a, serif", VALID),
    ("font", "normal normal normal normal 16px a", VALID),
    ("font", "italic italic 16px a", INVALID),
    ("font", "bold 11px", INVALID),
    ("font", "16px", INVALID),
    ("font", "caption", VALID),
    ("font", "-apple-system-body", INVALID),
    ("font", "1001 16px a", INVALID),
    ("font", "16px/1em/1 a", INVALID),
    ("font", "0/0 a", VALID),
    # transform, translate, scale, filter, clip, clip-path, text-shadow
    ("transform", "translate(-50%, -50%) rotate(45deg)", VALID),
    ("transform", "translate3d(0)", INVALID),
    ("transform", "rotate(0)", VALID),
    ("transform", "rotate(0px)", INVALID),
    ("transform", "translateX(0) , rotate(0)", INVALID),
    ("transform", "matrix(1,0,0,1,0)", INVALID),
    ("transform", "scale(1, 1, 1)", INVALID),
    ("transform", "perspective(none)", VALID),
    ("transform", "banana(0)", INVALID),
    ("translate", "1px 50% 2px", VALID),
    ("translate", "1px 2px 50%", INVALID),
    ("scale", "1 2 3", VALID),
    ("scale", "1px", INVALID),
    ("filter", "blur(1px) opacity(0)", VALID),
    ("filter", "blur(-1px)", INVALID),
    ("filter", "alpha(opacity=50)", INVALID),
    ("filter", "drop-shadow(1px 1px red)", VALID),
    ("filter", "hue-rotate(1px)", INVALID),
    ("filter", "url(#a)", VALID),
    ("filter", "progid:dximagetransform.microsoft.gradient(enabled = false)", INVALID),
    ("clip", "rect(0, 0, 0, 0)", VALID),
    ("clip", "rect(0 0 0)", INVALID),
    ("clip", "rect(0, 0 0, 0)", INVALID),
    ("clip", "auto", VALID),
    ("clip-path", "inset(50%)", VALID),
    ("clip-path", "inset(0 round 1px)", VALID),
    ("clip-path", "inset()", INVALID),
    ("clip-path", "circle(1px at 0 0)", VALID),
    ("clip-path", "circle(1)", INVALID),
    ("clip-path", "polygon(0 0, 1px 1px)", VALID),
    ("clip-path", "polygon(0)", INVALID),
    ("clip-path", "inset(0) border-box", VALID),
    ("clip-path", "banana", INVALID),
    ("text-shadow", "1px 1px 2px red", VALID),
    ("text-shadow", "1px", INVALID),
    ("text-shadow", "red 1px 1px, 0 0 blue", VALID),
    ("text-shadow", "1px red 1px", INVALID),
    ("text-shadow", "1px 1px -1px", INVALID),
    # backgrounds, images and masks
    ("background", "url(a) no-repeat center / cover #fff", VALID),
    ("background", "0 0 / cover contain", INVALID),
    ("background", "#fff, url(a)", INVALID),
    ("background", "-moz-linear-gradient(top, red, blue)", INVALID),
    ("background", "linear-gradient(, red, blue)", INVALID),
    ("background", "--gray-900-70", INVALID),
    ("background", "text border-box", VALID),
    ("background", "text text", INVALID),
    ("background", "#fff00", INVALID),
    ("background-image", "linear-gradient(to left top, red 0 50%, blue)", VALID),
    ("background-image", "linear-gradient(red, hsla(0,0,100%,0.1))", INVALID),
    ("background-image", "radial-gradient(100% 100% at 100%, at 0, red, blue)", INVALID),
    ("background-image", "radial-gradient(circle 10%, red, blue)", INVALID),
    ("background-image", "conic-gradient(from 45deg at 10px 20px, red, blue 50%)", VALID),
    ("background-image", "-webkit-linear-gradient(top, red, blue)", VALID),
    ("background-image", "-webkit-gradient(linear, left top, left bottom, from(red), to(blue))", VALID),
    ("background-image", "-webkit-gradient(linear, top left, bottom right, from(red))", INVALID),
    ("background-image", "image-set('a' 1x, 'b' 2x)", VALID),
    ("background-image", 'svg-load("a.svg")', INVALID),
    ("background-image", "url([bad url])", INVALID),
    ("background-image", "url(a), none", VALID),
    ("background-clip", "text", VALID),
    ("background-clip", "border-box, padding-box", VALID),
    ("background-clip", "none", INVALID),
    ("-webkit-background-clip", "text", VALID),
    ("-webkit-background-clip", "border-area", INVALID),
    ("mask", "url(a) no-clip", VALID),
    ("mask", "url(a) center / contain no-repeat", VALID),
    ("mask", "url(a) red", INVALID),
    # content: strings, attr(), counters, quotes, images and the "/ alt" part
    ("content", "''", VALID),
    ("content", "'a' attr(x)", VALID),
    ("content", "counter(a) '.'", VALID),
    ("content", "counters(a, '.')", VALID),
    ("content", "counters(a)", INVALID),
    ("content", "counter(default)", INVALID),
    ("content", "open-quote", VALID),
    ("content", "url(a) / 'alt'", VALID),
    ("content", "'a' / url(a)", INVALID),
    ("content", "none / 'a'", INVALID),
    ("content", "normal", VALID),
    ("content", "contents", INVALID),
    ("content", "'a' 1", INVALID),
    ("content", "linear-gradient(red, blue)", VALID),
    # SVG paint
    ("fill", "none", VALID),
    ("fill", "red", VALID),
    ("fill", "#f008", VALID),
    ("fill", "f00", INVALID),
    ("fill", "currentcolor", VALID),
    ("fill", "transparent", VALID),
    ("fill", "color-mix(in srgb, red, blue)", VALID),
    ("fill", "context-fill", VALID),
    ("fill", "context-stroke", VALID),
    ("fill", "banana", INVALID),
    ("fill", "0", INVALID),
    ("fill", "auto", INVALID),
    ("fill", "url(#a)", VALID),
    ("fill", "url(\"#a\")", VALID),
    ("fill", "url(a.svg#b)", VALID),
    ("fill", "url()", VALID),
    ("fill", "url(#a) none", VALID),
    ("fill", "url(#a) red", VALID),
    ("fill", "url(#a) currentcolor", VALID),
    ("fill", "url(\"#a\") #f00", VALID),
    ("fill", "red url(#a)", INVALID),
    ("fill", "none none", INVALID),
    ("fill", "none red", INVALID),
    ("fill", "url(#a) url(#b)", INVALID),
    ("fill", "url(#a) context-fill", INVALID),
    ("fill", "url(#a) banana", INVALID),
    ("fill", "url(#a), red", INVALID),
    ("fill", "context-fill red", INVALID),
    ("fill", "url(#a) none none", INVALID),
    ("fill", "-webkit-text", INVALID),
    ("stroke", "none", VALID),
    ("stroke", "red", VALID),
    ("stroke", "#f008", VALID),
    ("stroke", "f00", INVALID),
    ("stroke", "currentcolor", VALID),
    ("stroke", "transparent", VALID),
    ("stroke", "color-mix(in srgb, red, blue)", VALID),
    ("stroke", "context-fill", VALID),
    ("stroke", "context-stroke", VALID),
    ("stroke", "banana", INVALID),
    ("stroke", "0", INVALID),
    ("stroke", "auto", INVALID),
    ("stroke", "url(#a)", VALID),
    ("stroke", "url(\"#a\")", VALID),
    ("stroke", "url(a.svg#b)", VALID),
    ("stroke", "url()", VALID),
    ("stroke", "url(#a) none", VALID),
    ("stroke", "url(#a) red", VALID),
    ("stroke", "url(#a) currentcolor", VALID),
    ("stroke", "url(\"#a\") #f00", VALID),
    ("stroke", "red url(#a)", INVALID),
    ("stroke", "none none", INVALID),
    ("stroke", "none red", INVALID),
    ("stroke", "url(#a) url(#b)", INVALID),
    ("stroke", "url(#a) context-fill", INVALID),
    ("stroke", "url(#a) banana", INVALID),
    ("stroke", "url(#a), red", INVALID),
    ("stroke", "context-fill red", INVALID),
    ("stroke", "url(#a) none none", INVALID),
    ("stroke", "-webkit-text", INVALID),
    ("fill-opacity", "0", VALID),
    ("fill-opacity", "0%", VALID),
    ("fill-opacity", "-1", VALID),
    ("fill-opacity", "2", VALID),
    ("fill-opacity", "200%", VALID),
    ("fill-opacity", "calc(0)", VALID),
    ("fill-opacity", "0px", INVALID),
    ("fill-opacity", "none", INVALID),
    ("fill-opacity", "0 0", INVALID),
    ("fill-opacity", "banana", INVALID),
    ("stroke-opacity", "0", VALID),
    ("stroke-opacity", "0%", VALID),
    ("stroke-opacity", "-1", VALID),
    ("stroke-opacity", "2", VALID),
    ("stroke-opacity", "200%", VALID),
    ("stroke-opacity", "calc(0)", VALID),
    ("stroke-opacity", "0px", INVALID),
    ("stroke-opacity", "none", INVALID),
    ("stroke-opacity", "0 0", INVALID),
    ("stroke-opacity", "banana", INVALID),
    ("stroke-width", "0", VALID),
    ("stroke-width", "1", VALID),
    ("stroke-width", "0.5", VALID),
    ("stroke-width", "1e2", VALID),
    ("stroke-width", "1px", VALID),
    ("stroke-width", "1%", VALID),
    ("stroke-width", "1em", VALID),
    ("stroke-width", "-0", VALID),
    ("stroke-width", "calc(1)", VALID),
    ("stroke-width", "calc(1% + 1px)", VALID),
    ("stroke-width", "-1", INVALID),
    ("stroke-width", "-1px", INVALID),
    ("stroke-width", "auto", INVALID),
    ("stroke-width", "none", INVALID),
    ("stroke-width", "thin", INVALID),
    ("stroke-width", "1 2", INVALID),
    ("stop-color", "red", VALID),
    ("stop-color", "transparent", VALID),
    ("stop-color", "currentcolor", VALID),
    ("stop-color", "#f008", VALID),
    ("stop-color", "f00", INVALID),
    ("stop-color", "none", INVALID),
    ("stop-color", "url(#a)", INVALID),
    ("stop-color", "red blue", INVALID),
    ("stop-opacity", "0", VALID),
    ("stop-opacity", "50%", VALID),
    ("stop-opacity", "-1", VALID),
    ("stop-opacity", "calc(0)", VALID),
    ("stop-opacity", "0px", INVALID),
    ("stop-opacity", "none", INVALID),
    ("stop-opacity", "0 0", INVALID),
]

# Values this module does not decide, with why.
UNKNOWN_CASES = [
    # Chrome 157 parses this and then crashes the page.
    ("background", "border-area text"),
    # Relative colours, random() and anchor() are not followed.
    ("color", "rgb(from red r g b)"),
    ("width", "random(1px, 2px)"),
    ("left", "anchor(left)"),
    # Chrome types percentages and some lengths in these functions in ways this module does not follow
    # (it takes exp(1em) but not exp(1px)).
    ("opacity", "calc(exp(1em))"),
    ("opacity", "calc(sign(50% / 1px))"),
    # Deeper than the nesting this module follows.
    ("opacity", nested("var(--x,", "1", ")", 1200)),
    ("color", nested("light-dark(", "red", ", red)", 100)),
]

CUSTOM_PROPERTY_CASES = [
    # any <declaration-value>: empty, whitespace, comments, keywords, {} blocks anywhere
    ('1', VALID),
    ('', VALID),
    (' ', VALID),
    ('/**/', VALID),
    ('banana banana', VALID),
    ('inherit 1', VALID),
    ('default', VALID),
    ('@a', VALID),
    ('<!--', VALID),
    ('u+1', VALID),
    ('\'a\' "b"', VALID),
    ('\\', VALID),
    ('{}', VALID),
    ('{a}', VALID),
    ('{1} 2', VALID),
    ('1 {2}', VALID),
    ('({})', VALID),
    ('{!}', VALID),
    ('{;}', VALID),
    ('f({;})', VALID),
    ('(!)', VALID),
    ('[!]', VALID),
    ('f(!)', VALID),
    ('(;)', VALID),
    ('f(;)', VALID),
    ('url(a)', VALID),
    ('url(', VALID),
    ("'a", VALID),
    ('calc(1px +)', VALID),
    ('--(1)', VALID),
    ('-webkit-var(x)', VALID),
    # top-level "!", unmatched closing brackets, bad strings and bad url()s
    ('!', INVALID),
    ('1 !', INVALID),
    ('a!b', INVALID),
    ('#!', INVALID),
    ('1 ]', INVALID),
    ('1 )', INVALID),
    (']', INVALID),
    (')', INVALID),
    ('1 }', INVALID),
    ('}', INVALID),
    ('(]', INVALID),
    ('[)', INVALID),
    ('f(])', INVALID),
    ('url(a b)', INVALID),
    ('"a" url(a b)', INVALID),
    ('f(url(a b))', INVALID),
    ("'a\nb'", INVALID),
    ("1 'a\nb'", INVALID),
    ("{'a\nb'}", INVALID),
    ('url(a\nb)', INVALID),
    # var()
    ('var(--x)', VALID),
    ('var(---)', VALID),
    ('var(--a,)', VALID),
    ('var(--a, (!))', VALID),
    ('var(--a, {})', VALID),
    ('var(--a, {!})', VALID),
    ('var(x)', INVALID),
    ('var(--)', INVALID),
    ('var(--a 1)', INVALID),
    ('var(#0f0)', INVALID),
    ('var(--a, !)', INVALID),
    ('var(', INVALID),
    ('VAR(x)', INVALID),
    ('f(var(x))', INVALID),
    ('(var(x))', INVALID),
    ('{var(x)}', INVALID),
    ('calc(var(x))', INVALID),
    ('var(--a, var(x))', INVALID),
    # env(): a name, then non-negative integers
    ('env(x)', VALID),
    ('env(--x 0)', VALID),
    ('env(x 0 0 0)', VALID),
    ('env(x +1)', VALID),
    ('env(x -0)', VALID),
    ('env(x 1, 2)', VALID),
    ('env(x, {})', VALID),
    ('env(1)', INVALID),
    ('env(x -1)', INVALID),
    ('env(x 1.5)', INVALID),
    ('env(x 1e0)', INVALID),
    ('env(x y)', INVALID),
    ('env(x, !)', INVALID),
    ('env()', INVALID),
    # attr(): a name, then one identifier, "%" or type(<syntax>)
    ('attr(x)', VALID),
    ('attr(-x)', VALID),
    ('attr(x px)', VALID),
    ('attr(x %)', VALID),
    ('attr(x banana)', VALID),
    ('attr(x inherit)', VALID),
    ('attr(x raw-string, 1)', VALID),
    ('attr(x type(<length>))', VALID),
    ('attr(x type(<length>+))', VALID),
    ('attr(x type(<transform-list>))', VALID),
    ('attr(x type(*))', VALID),
    ('attr(x type(auto | <length>))', VALID),
    ('attr(x type(<custom-ident>#))', VALID),
    ('attr(x, attr(y))', VALID),
    ("attr('x')", INVALID),
    ('attr(x, !)', INVALID),
    ('attr()', INVALID),
    ('attr(x|y)', INVALID),
    ('attr(x 1px)', INVALID),
    ('attr(x px px)', INVALID),
    ("attr(x 'a')", INVALID),
    ('attr(x type())', INVALID),
    ('attr(x type(<url>))', INVALID),
    ('attr(x type(<transform-list>+))', INVALID),
    ('attr(x type(<LENGTH>))', INVALID),
    ('attr(x type(< length>))', INVALID),
    ('attr(x type(<length> +))', INVALID),
    ('attr(x type(inherit))', INVALID),
    ('attr(x type(* | <length>))', INVALID),
    ('attr(x type(auto auto))', INVALID),
    # if(): condition: value branches, with not, and, or and else
    ('if(style(--x): 1)', VALID),
    ('IF(style(--x):1)', VALID),
    ('if(style(--x):)', VALID),
    ('if(style(--x): 1;)', VALID),
    ('if(else: 1)', VALID),
    ('if(style(--x): 1; else: 2)', VALID),
    ('if(not style(--x): 1)', VALID),
    ('if(NOT (style(--x)): 1)', VALID),
    ('if(style(--x) and style(--y): 1)', VALID),
    ('if(style(--x) or media(print): 1)', VALID),
    ('if(banana(x): 1)', VALID),
    ('if((1): 1)', VALID),
    ('if(style(--x): {} 1)', VALID),
    ('if(style(--x): a : b)', VALID),
    ('if()', INVALID),
    ('if(x)', INVALID),
    ('if(banana: 1)', INVALID),
    ('if(style(--x): 1;;)', INVALID),
    ('if(;style(--x): 1)', INVALID),
    ('if(not not style(--x): 1)', INVALID),
    ('if(style(--x) and style(--y) or style(--z): 1)', INVALID),
    ('if(not style(--x) and style(--y): 1)', INVALID),
    ('if(style(--x) style(--y): 1)', INVALID),
    ('if(else and style(--x): 1)', INVALID),
    ('if(style(--x): !)', INVALID),
    ('if(style(--x): var(x))', INVALID),
    ('if([a]: 1)', INVALID),
    ('if(style(--x))', INVALID),
    ('if(style(--x): 1; 2)', INVALID),
    # custom functions: one {} block alone as an argument, with nothing after it
    ('--foo(1)', VALID),
    ('--foo( )', VALID),
    ('--foo(1, 2, 3)', VALID),
    ('--foo({a})', VALID),
    ('--foo({a, b})', VALID),
    ('--foo({a}, {b})', VALID),
    ('--foo( {a})', VALID),
    ('--foo(,1)', VALID),
    ('--foo((!))', VALID),
    ('--foo(--bar(1))', VALID),
    ('--foo(!)', INVALID),
    ('--foo({})', INVALID),
    ('--foo({ })', INVALID),
    ('--foo({!})', INVALID),
    ('--foo({a} )', INVALID),
    ('--foo({a} b)', INVALID),
    ('--foo(a {b})', INVALID),
    ('--foo(,)', INVALID),
    ('--foo(a,)', INVALID),
    ('--foo(,,1)', INVALID),
    ('--foo(var(x))', INVALID),
    ('--foo(--bar(!))', INVALID),
    # inherit() is rejected anywhere
    ('inherit(--x)', INVALID),
    ('1 inherit(--x)', INVALID),
    ('var(--a, inherit(--x))', INVALID),
]

# Chrome's quirks-mode and standards-mode checks set each value after one of these and compare.
BASES = {
    "display": ("table", "inline-table"), "visibility": ("hidden", "collapse"), "opacity": ("0.25", "0.75"),
    "color": ("rgb(1, 2, 3)", "rgb(4, 5, 6)"), "background-color": ("rgb(1, 2, 3)", "rgb(4, 5, 6)"),
    "-webkit-text-fill-color": ("rgb(1, 2, 3)", "rgb(4, 5, 6)"), "background": ("rgb(1, 2, 3)", "rgb(4, 5, 6)"),
    "clip": ("rect(1px, 2px, 3px, 4px)", "rect(5px, 6px, 7px, 8px)"), "clip-path": ("inset(1px)", "inset(2px)"),
    "transform": ("translatex(3px)", "translatex(5px)"), "overflow": ("hidden", "scroll"),
    "overflow-x": ("hidden", "scroll"), "overflow-y": ("hidden", "scroll"), "position": ("relative", "absolute"),
    "text-indent": ("33px", "37px"), "filter": ("blur(3px)", "blur(5px)"), "content-visibility": ("hidden", "auto"),
    "font": ("33px a", "37px b"), "line-height": ("33px", "37px"), "letter-spacing": ("3px", "5px"),
    "translate": ("33px", "37px"), "scale": ("3", "5"), "background-clip": ("content-box", "padding-box"),
    "-webkit-background-clip": ("content-box", "padding-box"), "background-image": ("url(a)", "url(b)"),
    "text-shadow": ("red 1px 1px", "blue 2px 2px"), "z-index": ("3", "5"), "content": ("'a'", "'b'"),
    "isolation": ("isolate", "auto"), "mix-blend-mode": ("multiply", "screen"), "mask": ("url(a)", "url(b)"),
    "perspective": ("33px", "37px"), "unicode-bidi": ("embed", "isolate"), "direction": ("rtl", "ltr"),
    "font-family": ("a", "b"), "inset": ("33px", "37px"), "font-size": ("33px", "37px"), "width": ("33px", "37px"),
    "height": ("33px", "37px"), "max-width": ("33px", "37px"), "max-height": ("33px", "37px"),
    "min-height": ("33px", "37px"), "left": ("33px", "37px"), "top": ("33px", "37px"), "right": ("33px", "37px"),
    "bottom": ("33px", "37px"), "margin-left": ("33px", "37px"), "margin-top": ("33px", "37px"),
    "fill": ("rgb(1, 2, 3)", "rgb(4, 5, 6)"), "stroke": ("rgb(1, 2, 3)", "rgb(4, 5, 6)"),
    "fill-opacity": ("0.25", "0.75"), "stroke-opacity": ("0.25", "0.75"), "stroke-width": ("33px", "37px"),
    "stop-color": ("rgb(1, 2, 3)", "rgb(4, 5, 6)"), "stop-opacity": ("0.25", "0.75"),
}
POSITIONED = ("left", "top", "right", "bottom", "inset")


def tokens_of(name, value):
    declaration = tinycss2.parse_one_declaration(name + ":" + value)
    if declaration.type == "error":
        # tinycss2 takes "--o: 1 {2}" for a nested rule; Chrome for a custom property.
        return tinycss2.parse_component_value_list(value)
    return declaration.value


def fits_in_rule(value):
    """Whether value can stand inside .x{...} unchanged: no ";", "{" or "}", brackets balanced,
    strings closed."""
    depth = 0
    quote = None
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\":
            index += 2
            continue
        if quote:
            if character == quote:
                quote = None
        elif character in "'\"":
            quote = character
        elif character in ";{}":
            return False
        elif character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
            if depth < 0:
                return False
        index += 1
    return depth == 0 and quote is None


def call_from_deep_stack(frames, function):
    if frames == 0:
        return function()
    return call_from_deep_stack(frames - 1, function)


class DeclarationValidityTests(unittest.TestCase):
    def test_answers_match_chrome(self):
        for name, value, expected in CHROME_CASES:
            with self.subTest(name=name, value=value[:80]):
                self.assertEqual(declaration_validity(name, tokens_of(name, value)), expected)

    def test_custom_property_answers_match_chrome(self):
        for value, expected in CUSTOM_PROPERTY_CASES:
            with self.subTest(value=value):
                self.assertEqual(custom_property_validity(tokens_of("--o", value)), expected)

    def test_custom_property_too_deep_to_follow_is_unknown(self):
        valid_but_deep = nested("var(--a,", "1", ")", 1200)
        invalid_and_deep = nested("(", "var(x)", ")", 1200)
        self.assertEqual(custom_property_validity(tokens_of("--o", valid_but_deep)), UNKNOWN)
        self.assertEqual(custom_property_validity(tokens_of("--o", invalid_and_deep)), INVALID)
        self.assertEqual(custom_property_validity(tokens_of("--o", nested("(", "1", ")", 100000))), VALID)

    def test_undecided_values_are_unknown(self):
        for name, value in UNKNOWN_CASES:
            with self.subTest(name=name, value=value[:80]):
                self.assertEqual(declaration_validity(name, tokens_of(name, value)), UNKNOWN)

    def test_comments_dropped_by_the_tokenizer_give_the_same_answer(self):
        for name, value, expected in (("width", "calc(1px/**/+/**/2px)", INVALID),
                                      ("width", "calc(1px /**/+/**/ 2px)", VALID),
                                      ("color", "/**/red/**/", VALID), ("color", "rgb(1/**/2/**/3)", VALID)):
            with self.subTest(value=value):
                tokens = tinycss2.parse_component_value_list(value, skip_comments=True)
                self.assertEqual(declaration_validity(name, tokens), expected)

    def test_very_deep_values_neither_recurse_nor_hang(self):
        cases = (
            ("opacity", nested("calc(", "1", ")", 100000), INVALID),
            ("opacity", "calc(" + nested("(", "1", ")", 100000) + ")", INVALID),
            ("display", nested("(", "1", ")", 100000), INVALID),
            ("opacity", nested("var(--x,", "1", ")", 100000), UNKNOWN),
            ("color", nested("light-dark(", "red", ", red)", 100000), UNKNOWN),
            ("background-image", nested("image-set(", "'a'", ")", 100000), UNKNOWN),
        )
        for name, value, expected in cases:
            with self.subTest(name=name, value=value[:30]):
                self.assertEqual(declaration_validity(name, tokens_of(name, value)), expected)

    def test_math_at_the_depth_limit_fits_on_a_deep_call_stack(self):
        value = "rotate(" + nested("atan2(1deg, ", "1deg", ")", 100) + ")"
        tokens = tokens_of("transform", value)
        self.assertEqual(call_from_deep_stack(700, lambda: declaration_validity("transform", tokens)), VALID)


@unittest.skipUnless(importlib.util.find_spec("playwright") is not None, "playwright not installed")
class ChromeAgreementTests(unittest.TestCase):
    """CHROME_CASES checked against the installed Chrome: in style sheets for values a rule can hold
    (CSS.supports accepts some values a style sheet drops), with CSS.supports for the others."""

    APPLIED = """([property, prefix, base, value, doctype]) => {
      const computed = css => {
        document.open();
        document.write(doctype + '<html><head><style>.x{' + prefix + css + '}</style></head>'
                       + '<body><div class="x" id="x">t</div></body></html>');
        document.close();
        return getComputedStyle(document.getElementById('x')).getPropertyValue(property);
      };
      return computed(property + ':' + base) !== computed(property + ':' + base + ';' + property + ':' + value);
    }"""

    CUSTOM_APPLIED = """([value, doctype, inline]) => {
      const computed = css => {
        document.open();
        if (inline) {
          document.write(doctype + '<html><body><div id="x">t</div></body></html>');
          document.close();
          document.getElementById('x').setAttribute('style', css);
        } else {
          document.write(doctype + '<html><head><style>.x{' + css + '}</style></head>'
                         + '<body><div class="x" id="x">t</div></body></html>');
          document.close();
        }
        return getComputedStyle(document.getElementById('x')).getPropertyValue('--o');
      };
      for (const base of ['b1', 'b2']) {
        if (computed('--o:' + base) !== computed('--o:' + base + ';--o:' + value)) return true;
      }
      return false;
    }"""

    def applied(self, tab, name, value, doctype):
        prefix = "position:absolute;" if name in POSITIONED else ""
        for base in BASES[name]:
            if tab.evaluate(self.APPLIED, [name, prefix, base, value, doctype]):
                return True
        return False

    def test_answers_match_chrome(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(channel="chrome")
            except Exception as error:  # Chrome missing or not launchable here
                self.skipTest(f"Chrome not available: {error}")
            tab = browser.new_page()
            tab.set_content("<!doctype html><p>x")
            for name, value, expected in CHROME_CASES:
                with self.subTest(name=name, value=value[:80]):
                    if fits_in_rule(value) and value.strip():
                        standards = self.applied(tab, name, value, "<!doctype html>")
                        quirks = self.applied(tab, name, value, "")
                        self.assertEqual(standards, expected == VALID)
                        self.assertEqual(quirks, expected != INVALID)
                    else:
                        tab.set_content("<!doctype html><p>x")
                        supported = tab.evaluate("([p, v]) => CSS.supports(p, v)", [name, value])
                        self.assertEqual(supported, expected == VALID)
            browser.close()

    def test_custom_property_answers_match_chrome(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(channel="chrome")
            except Exception as error:  # Chrome missing or not launchable here
                self.skipTest(f"Chrome not available: {error}")
            tab = browser.new_page()
            tab.set_content("<p>x")
            for value, expected in CUSTOM_PROPERTY_CASES:
                with self.subTest(value=value):
                    # In a style attribute the value comes last, so an unclosed bracket ends where
                    # tinycss2 ends it; a style sheet takes only values a rule can hold.
                    self.assertEqual(tab.evaluate(self.CUSTOM_APPLIED, [value, "<!doctype html>", True]),
                                     expected == VALID)
                    if fits_in_rule(value):
                        for doctype in ("<!doctype html>", ""):
                            self.assertEqual(tab.evaluate(self.CUSTOM_APPLIED, [value, doctype, False]),
                                             expected == VALID)
            browser.close()


if __name__ == "__main__":
    unittest.main()
