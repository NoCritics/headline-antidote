"""Text inside <svg> is drawn only inside <text> (through <tspan>, <textPath> and <a>) or inside
<foreignObject>. Text anywhere else in an SVG reaches a scraper that reads the markup but is never
shown, so it must not reach the model as visible text. The expected texts are Chrome 157's
innerText (whitespace collapsed); tests/test_browser_check.ParserChromeTests checks them against
Chrome. Where innerText counts text that is not painted (definitions such as <defs>, checked with
screenshots), the cases are in NotDrawnTests instead.

innerText also counts text Chrome does not paint because of the drawing's sizes and paint: a
<foreignObject> without a size, an <svg> of zero size. SVG_PAINT_CASES holds those, each checked
against Chrome with screenshots (tests/test_browser_check.SvgPaintChromeTests). innerText also
counts text placed outside the drawing: a <text> with no y (its baseline at the top edge, so its
letters sit above it), or one thousands of pixels off. The reader hides the plain cases and keeps
text whenever something else may move it (a transform, a baseline, a <tspan> position, a <use>),
which the browser check settles (tests/test_browser_check.SVG_POSITION_CASES)."""

import unittest

from headline_guard.html_visibility import extract_visible_text

XHTML = "http://www.w3.org/1999/xhtml"
MATHML = "http://www.w3.org/1998/Math/MathML"


def page(svg_markup):
    return f"<html><body>{svg_markup}<p>x</p></body></html>"


# (page, the text Chrome shows)
SVG_CHROME_PAGES = (
    (page("<svg>PAYLOAD<g>PAYLOAD</g><text>drawn<tspan>span</tspan></text>"
          '<foreignObject width="99" height="99"><p>fo</p></foreignObject></svg>'), "drawnspan fo x"),
    (page("<svg><![CDATA[PAYLOAD]]></svg>"), "x"),
    # Inside <text>: <tspan>, <a> (not inside another <a>), and <textPath> directly under <text>
    # or its <a>. Nothing else draws, and the text after such a child still does.
    (page("<svg><text>A<g>PAYLOAD</g>B<a>C</a>D</text></svg>"), "ABCD x"),
    (page("<svg><text>A<foreignObject>PAYLOAD</foreignObject><text>PAYLOAD</text>"
          "<unknown>PAYLOAD</unknown><switch><tspan>PAYLOAD</tspan></switch>B</text></svg>"), "AB x"),
    (page("<svg><text><tspan><textPath>PAYLOAD</textPath></tspan>"
          "<textPath>T<tspan>S</tspan><textPath>PAYLOAD</textPath></textPath></text></svg>"), "TS x"),
    (page("<svg><text><a><textPath>T</textPath></a><tspan><a>A<a>PAYLOAD</a></a></tspan></text></svg>"),
     "TA x"),
    (page("<svg><text>A<title>PAYLOAD</title><desc>PAYLOAD</desc>B</text></svg>"), "AB x"),
    # Outside <text>: <svg>, <g>, <a> (not inside another <a>) and <switch> hold drawn children;
    # their own text, and every other element, draws nothing.
    (page("<svg><a><text>A</text>PAYLOAD</a><a><g><text>B</text></g></a>"
          "<a><a><text>PAYLOAD</text></a></a></svg>"), "A B x"),
    (page("<svg><textPath>PAYLOAD</textPath><tspan>PAYLOAD</tspan><rect><text>PAYLOAD</text></rect>"
          "<unknown><text>PAYLOAD</text></unknown><svg><text>N</text></svg></svg>"), "N x"),
    (page('<svg><foreignObject width="99" height="99">F<svg>PAYLOAD<text>T</text></svg>'
          "</foreignObject></svg>"), "F T x"),
    (page("<svg><g><text>G1</text><text>G2</text></g></svg>"), "G1 G2 x"),
    # Inside <foreignObject> the content is HTML, where <desc> is an ordinary element.
    (page('<svg><foreignObject width="99" height="99"><desc>D</desc><title>PAYLOAD</title><p>p</p>'
          "</foreignObject></svg>"), "D p x"),
    # A <switch> draws its first element child whose conditions hold, and nothing else.
    (page("<svg><switch>PAYLOAD<!--c--><g><text>G</text></g><text>PAYLOAD</text></switch></svg>"), "G x"),
    (page("<svg><switch><desc>d</desc><text>PAYLOAD</text></switch></svg>"), "x"),
    (page('<svg><switch><text requiredExtensions="x">PAYLOAD</text><text>S</text></switch></svg>'), "S x"),
    (page(f'<svg><switch><foreignObject requiredExtensions="{XHTML}" width="99" height="99">'
          "<p>FO</p></foreignObject><text>PAYLOAD</text></switch></svg>"), "FO x"),
    # requiredExtensions holds only when it lists XHTML or MathML and nothing else.
    (page(f'<svg><text requiredExtensions="x">PAYLOAD</text><text requiredExtensions="">PAYLOAD</text>'
          f'<text requiredExtensions="{XHTML} http://x">PAYLOAD</text>'
          f'<text requiredExtensions="{MATHML}">M</text></svg>'), "M x"),
    # The names are separated by ASCII whitespace only.
    (page(f'<svg><text requiredExtensions=" {XHTML}\t{XHTML} ">T</text>'
          f'<text requiredExtensions="{XHTML} {XHTML}">PAYLOAD</text>'
          f'<text requiredExtensions="{XHTML} {XHTML}">PAYLOAD</text></svg>'), "T x"),
    (page('<svg><text>A<tspan systemLanguage="xx">PAYLOAD</tspan></text>'
          '<g systemLanguage="xx"><text>PAYLOAD</text></g></svg>'), "A x"),
)


# A drawing of 300x100 with PAYLOAD where it is painted unless something below stops it.
SVG = '<svg width="300" height="100">'
AT = 'x="10" y="50" font-size="40"'
FO_PARAGRAPH = '<p style="margin:0;font-size:40px">PAYLOAD</p>'

# (markup, whether Chrome paints PAYLOAD): a screenshot of the page with PAYLOAD differs from one
# without it. Each unpainted case has a painted one beside it that differs only in what stops it.
SVG_PAINT_CASES = (
    # A <foreignObject> is painted only when its width and height are both positive (CSS wins over
    # the attributes; missing, auto, zero, negative and invalid sizes are none), or when its
    # overflow is visible.
    (f"{SVG}<foreignObject>{FO_PARAGRAPH}</foreignObject></svg>", False),
    (f'{SVG}<foreignObject width="300" height="100">{FO_PARAGRAPH}</foreignObject></svg>', True),
    (f'{SVG}<foreignObject width="300">{FO_PARAGRAPH}</foreignObject></svg>', False),
    (f'{SVG}<foreignObject height="100">{FO_PARAGRAPH}</foreignObject></svg>', False),
    (f'{SVG}<foreignObject width="0" height="100">{FO_PARAGRAPH}</foreignObject></svg>', False),
    (f'{SVG}<foreignObject width="300" height="0">{FO_PARAGRAPH}</foreignObject></svg>', False),
    (f'{SVG}<foreignObject width="-5" height="100">{FO_PARAGRAPH}</foreignObject></svg>', False),
    (f'{SVG}<foreignObject width="auto" height="auto">{FO_PARAGRAPH}</foreignObject></svg>', False),
    (f'{SVG}<foreignObject width="banana" height="100">{FO_PARAGRAPH}</foreignObject></svg>', False),
    (f'{SVG}<foreignObject width="50%" height="50%">{FO_PARAGRAPH}</foreignObject></svg>', True),
    (f'{SVG}<foreignObject width=" 1e2 " height="100PX">{FO_PARAGRAPH}</foreignObject></svg>', True),
    (f'{SVG}<foreignObject width="300em" height="100">{FO_PARAGRAPH}</foreignObject></svg>', True),
    (f'{SVG}<foreignObject width="300." height="100">{FO_PARAGRAPH}</foreignObject></svg>', False),
    (f'{SVG}<foreignObject style="width:300px;height:100px">{FO_PARAGRAPH}</foreignObject></svg>', True),
    (f'{SVG}<foreignObject style="width:300px;height:100px" width="0">{FO_PARAGRAPH}</foreignObject></svg>',
     True),
    (f"<style>.f{{width:300px;height:100px}}</style>{SVG}<foreignObject class=\"f\">{FO_PARAGRAPH}"
     "</foreignObject></svg>", True),
    (f'{SVG}<foreignObject width="300" height="100" style="width:0">{FO_PARAGRAPH}</foreignObject></svg>',
     False),
    (f'{SVG}<foreignObject width="300" height="100" style="height:auto">{FO_PARAGRAPH}</foreignObject></svg>',
     False),
    (f'{SVG}<foreignObject width="300" height="100" style="width:50px">{FO_PARAGRAPH}</foreignObject></svg>',
     True),
    (f'{SVG}<foreignObject style="overflow:visible">{FO_PARAGRAPH}</foreignObject></svg>', True),
    (f'{SVG}<foreignObject overflow="visible">{FO_PARAGRAPH}</foreignObject></svg>', True),
    (f'{SVG}<foreignObject width="0" height="0" style="overflow:visible">{FO_PARAGRAPH}</foreignObject></svg>',
     True),
    (f"<style>foreignObject{{overflow:visible}}</style>{SVG}<foreignObject>{FO_PARAGRAPH}</foreignObject></svg>",
     True),
    (f'{SVG}<foreignObject width="300" height="100" overflow="hidden">{FO_PARAGRAPH}</foreignObject></svg>',
     True),
    # A size from CSS this reader cannot decide (@supports) counts both ways.
    ("<style>@supports (not (display:grid)) {foreignObject{width:300px;height:100px}}</style>"
     f"{SVG}<foreignObject>{FO_PARAGRAPH}</foreignObject></svg>", False),
    # An <svg> of zero width or height paints nothing, whatever its overflow.
    (f'<svg width="0" height="100"><text {AT}>PAYLOAD</text></svg>', False),
    (f'<svg width="300" height="0"><text {AT}>PAYLOAD</text></svg>', False),
    (f'<svg width="0" height="0" style="overflow:visible"><text {AT}>PAYLOAD</text></svg>', False),
    (f'<svg width="300" height="100" style="width:0"><text {AT}>PAYLOAD</text></svg>', False),
    (f'<svg width="300" height="100" style="height:0;overflow:visible"><text {AT}>PAYLOAD</text></svg>', False),
    (f'<svg style="width:0;height:0;position:absolute"><text {AT}>PAYLOAD</text></svg>', False),
    (f'<svg width="0" height="100" style="width:300px"><text {AT}>PAYLOAD</text></svg>', True),
    (f'<svg width="300" height="100" style="width:0%"><text {AT}>PAYLOAD</text></svg>', False),
    (f'<svg width="300" height="100" style="height:0em"><text {AT}>PAYLOAD</text></svg>', False),
    (f'<style>.s{{height:0%}}</style><svg width="300" height="100" class="s"><text {AT}>PAYLOAD</text></svg>',
     False),
    (f'<svg width="300" height="100" style="width:1%"><text {AT}>PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT}>PAYLOAD</text></svg>', True),
    (f'<svg><text y="20">PAYLOAD</text></svg>', True),
    # SVG presentation attributes are CSS of the lowest priority: any stylesheet rule wins over
    # them. Values are read as CSS (case and surrounding spaces ignored), and one the property
    # cannot take is ignored. They apply to SVG elements only, not to HTML in a <foreignObject>.
    (f'{SVG}<text {AT} display="none">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} display="inline">PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} DISPLAY=" NONE ">PAYLOAD</text></svg>', False),
    (f'<style>text{{display:block}}</style>{SVG}<text {AT} display="none">PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} display="none" style="display:inline">PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} visibility="hidden">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} visibility="collapse">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} visibility="visible">PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} opacity="0">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} opacity="0%">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} opacity="calc(0)">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} opacity="0 0">PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} opacity="1">PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} opacity="0" style="opacity:1">PAYLOAD</text></svg>', True),
    (f'{SVG}<text x="10" y="50" font-size="0">PAYLOAD</text></svg>', False),
    (f'{SVG}<text x="10" y="50" font-size="0px">PAYLOAD</text></svg>', False),
    (f'{SVG}<text x="10" y="50" font-size="40">PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} transform="scale(0)">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} transform="scale(1)">PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} clip-path="inset(50%)">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} clip-path="inset(0)">PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} filter="opacity(0)">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} filter="opacity(1)">PAYLOAD</text></svg>', True),
    # On an enclosing element they hide what is inside it.
    (f'{SVG}<g display="none"><text {AT}>PAYLOAD</text></g></svg>', False),
    (f'{SVG}<g opacity="0"><text {AT}>PAYLOAD</text></g></svg>', False),
    (f'{SVG}<g opacity="0"><text {AT} opacity="1">PAYLOAD</text></g></svg>', False),
    (f'{SVG}<g visibility="hidden"><text {AT}>PAYLOAD</text></g></svg>', False),
    (f'{SVG}<text {AT}>A<tspan display="none">PAYLOAD</tspan></text></svg>', False),
    (f'{SVG}<text {AT}>A<tspan opacity="0">PAYLOAD</tspan></text></svg>', False),
    (f'{SVG}<text {AT}>A<tspan font-size="0">PAYLOAD</tspan></text></svg>', False),
    (f'{SVG}<text {AT}>A<tspan font-size="20">PAYLOAD</tspan></text></svg>', True),
    # Sizes are in the drawing's user units: a viewBox or a transform can make a small one large.
    ('<svg width="300" height="100" viewBox="0 0 30 10"><text x="1" y="5" font-size="1">PAYLOAD</text></svg>',
     True),
    (f'{SVG}<g transform="scale(10)"><text x="1" y="5" font-size="1">PAYLOAD</text></g></svg>', True),
    (f'{SVG}<text x="1" y="5" font-size="1" transform="scale(10)">PAYLOAD</text></svg>', True),
    (f'<svg width="300" height="100" display="none"><text {AT}>PAYLOAD</text></svg>', False),
    (f'<svg width="300" height="100" opacity="0"><text {AT}>PAYLOAD</text></svg>', False),
    (f'{SVG}<foreignObject width="300" height="100" opacity="0">{FO_PARAGRAPH}</foreignObject></svg>', False),
    (f'{SVG}<foreignObject width="300" height="100" display="none">{FO_PARAGRAPH}</foreignObject></svg>', False),
    (f'{SVG}<foreignObject width="300" height="100" visibility="hidden">{FO_PARAGRAPH}</foreignObject></svg>',
     False),
    (f'{SVG}<foreignObject width="300" height="100"><p style="margin:0;font-size:40px" opacity="0">PAYLOAD</p>'
     "</foreignObject></svg>", True),
    ('<p display="none" opacity="0">PAYLOAD</p>', True),
    # SVG text is painted with fill (black when not set) and stroke (none when not set), both
    # inherited from any ancestor, HTML ones included; color matters only through currentColor.
    (f'{SVG}<text {AT} fill="none">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill="black">PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} FILL=" NONE ">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill="transparent">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill="rgba(0,0,0,0)">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill="#0000">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill="banana">PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} fill-opacity="0">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill-opacity="0%">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill-opacity="banana">PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} fill="context-fill">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill="context-stroke">PAYLOAD</text></svg>', False),
    # url() paints with a gradient or pattern of this page, else with its fallback, else not at all.
    (f'{SVG}<defs><linearGradient id="g"><stop offset="0" stop-color="black"/></linearGradient></defs>'
     f'<text {AT} fill="url(#g)">PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} fill="url(#missing)">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill="url(#missing) red">PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} fill="url(#missing) none">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill="url(other.svg#a)">PAYLOAD</text></svg>', False),
    (f'{SVG}<rect id="r" width="1" height="1"/><text {AT} fill="url(#r)">PAYLOAD</text></svg>', False),
    (f'{SVG}<rect id="r" width="1" height="1"/><text {AT} fill="url(#r) red">PAYLOAD</text></svg>', True),
    # CSS wins over the attribute.
    (f'{SVG}<text {AT} style="fill:none">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} style="fill:none" fill="black">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill="none" style="fill:black">PAYLOAD</text></svg>', True),
    (f'<style>text{{fill:none}}</style>{SVG}<text {AT}>PAYLOAD</text></svg>', False),
    (f'<style>text{{fill:none}}</style>{SVG}<text {AT} fill="black">PAYLOAD</text></svg>', False),
    (f'<style>text{{fill:black}}</style>{SVG}<text {AT} fill="none">PAYLOAD</text></svg>', True),
    (f'<style>.t{{fill-opacity:0}}</style>{SVG}<text {AT} class="t">PAYLOAD</text></svg>', False),
    # Inherited fill, and a descendant's own fill painting again.
    (f'{SVG}<g fill="none"><text {AT}>PAYLOAD</text></g></svg>', False),
    (f'{SVG}<g fill="none"><text {AT} fill="black">PAYLOAD</text></g></svg>', True),
    (f'{SVG}<g fill="none"><text {AT} fill="currentColor">PAYLOAD</text></g></svg>', True),
    (f'{SVG}<g fill="none"><text {AT} fill="inherit">PAYLOAD</text></g></svg>', False),
    (f'<svg width="300" height="100" fill="none"><text {AT}>PAYLOAD</text></svg>', False),
    (f'<svg width="300" height="100" style="fill:none"><text {AT}>PAYLOAD</text></svg>', False),
    (f'<div style="fill:none">{SVG}<text {AT}>PAYLOAD</text></svg></div>', False),
    (f'<style>g{{fill:none}}</style>{SVG}<g><text {AT}>PAYLOAD</text></g></svg>', False),
    (f'{SVG}<text {AT} fill="none"><tspan fill="black">PAYLOAD</tspan></text></svg>', True),
    (f'{SVG}<text {AT}>A<tspan fill="none">PAYLOAD</tspan></text></svg>', False),
    (f'{SVG}<text {AT}>A<a fill="none">PAYLOAD</a></text></svg>', False),
    (f'{SVG}<text {AT} fill="none"><textPath>PAYLOAD</textPath></text></svg>', False),
    (f'{SVG}<text {AT} fill="none">A<tspan fill="black">B</tspan>PAYLOAD</text></svg>', False),
    # currentColor is the color property, which paints nothing by itself.
    (f'{SVG}<text {AT} color="transparent" fill="currentColor">PAYLOAD</text></svg>', False),
    (f'{SVG}<g color="transparent"><text {AT} fill="currentColor">PAYLOAD</text></g></svg>', False),
    (f'<div style="color:transparent">{SVG}<text {AT} fill="currentColor">PAYLOAD</text></svg></div>', False),
    (f'{SVG}<text {AT} color="transparent">PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} style="color:white">PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} style="-webkit-text-fill-color:transparent">PAYLOAD</text></svg>', True),
    # A stroke paints the text when its paint shows and its width is not zero.
    (f'{SVG}<text {AT} fill="none" stroke="black">PAYLOAD</text></svg>', True),
    (f'<svg width="300" height="100" fill="none" stroke="currentColor"><text {AT}>PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} fill-opacity="0" stroke="black">PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} fill="none" stroke="black" stroke-width="0">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill="none" stroke="black" stroke-width="0px">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill="none" stroke="black" stroke-width="-1">PAYLOAD</text></svg>', True),
    (f'{SVG}<text {AT} fill="none" stroke="black" stroke-opacity="0">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill="none" stroke="black" stroke-opacity="0" style="stroke-opacity:1">PAYLOAD</text>'
     "</svg>", True),
    (f'{SVG}<text {AT} fill="none" stroke="none">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill="none" stroke="transparent">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill="none" stroke="url(#missing)">PAYLOAD</text></svg>', False),
    # A fill (or stroke) no different from the page background shows nothing.
    (f'{SVG}<text {AT} fill="white">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill="#fff8">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill="none" stroke="white">PAYLOAD</text></svg>', False),
    (f'{SVG}<text {AT} fill="white" stroke="black">PAYLOAD</text></svg>', True),
    (f'<div style="background:black">{SVG}<text {AT} fill="white">PAYLOAD</text></svg></div>', True),
    # HTML in a <foreignObject> is colored by the color it inherits, from SVG ancestors too.
    (f'{SVG}<g style="color:white"><foreignObject width="300" height="100">{FO_PARAGRAPH}</foreignObject></g></svg>',
     False),
    (f'{SVG}<g color="white"><foreignObject width="300" height="100">{FO_PARAGRAPH}</foreignObject></g></svg>',
     False),
    (f'<svg width="300" height="100" color="white"><foreignObject width="300" height="100">{FO_PARAGRAPH}'
     "</foreignObject></svg>", False),
    (f'{SVG}<g style="color:black"><foreignObject width="300" height="100">{FO_PARAGRAPH}</foreignObject></g></svg>',
     True),
    # Paint from CSS this reader cannot decide (@supports) counts both ways, inherited too.
    ("<style>@supports (not (display:grid)) {text{fill:black}}</style>"
     f'{SVG}<text {AT} fill="none">PAYLOAD</text></svg>', False),
    ("<style>@supports (not (display:grid)) {g{fill:black}}</style>"
     f'<svg width="300" height="100" fill="none"><g><text {AT}>PAYLOAD</text></g></svg>', False),
    # A gradient paints with its stops (its own, or those of the gradient it links to by href); one
    # whose stops are all transparent, or that has none, paints nothing.
    (f'{SVG}<defs><linearGradient id="g"><stop offset="0" stop-color="black" stop-opacity="0"/>'
     f'<stop offset="1" stop-color="red" stop-opacity="0"/></linearGradient></defs>'
     f'<text {AT} fill="url(#g)">PAYLOAD</text></svg>', False),
    (f'{SVG}<defs><linearGradient id="g"><stop offset="0" stop-color="black" stop-opacity="0"/>'
     f'<stop offset="1" stop-color="red"/></linearGradient></defs>'
     f'<text {AT} fill="url(#g)">PAYLOAD</text></svg>', True),
    (f'{SVG}<defs><linearGradient id="g"><stop offset="0" stop-color="transparent"/></linearGradient></defs>'
     f'<text {AT} fill="url(#g)">PAYLOAD</text></svg>', False),
    (f'{SVG}<defs><radialGradient id="g"></radialGradient></defs><text {AT} fill="url(#g)">PAYLOAD</text></svg>',
     False),
    (f'<style>stop{{stop-opacity:0}}</style>{SVG}<defs><linearGradient id="g"><stop offset="0" stop-color="black"/>'
     f'</linearGradient></defs><text {AT} fill="url(#g)">PAYLOAD</text></svg>', False),
    (f'{SVG}<defs><linearGradient id="g"><stop offset="0" style="stop-color:transparent"/></linearGradient></defs>'
     f'<text {AT} fill="url(#g)">PAYLOAD</text></svg>', False),
    (f'{SVG}<defs><linearGradient id="a"><stop offset="0" stop-color="black" stop-opacity="0"/></linearGradient>'
     f'<linearGradient id="g" href="#a"></linearGradient></defs><text {AT} fill="url(#g)">PAYLOAD</text></svg>',
     False),
    (f'{SVG}<defs><linearGradient id="a"><stop offset="0" stop-color="black"/></linearGradient>'
     f'<linearGradient id="g" href="#a"></linearGradient></defs><text {AT} fill="url(#g)">PAYLOAD</text></svg>',
     True),
    (f'{SVG}<defs><pattern id="p" width="10" height="10" patternUnits="userSpaceOnUse"></pattern></defs>'
     f'<text {AT} fill="url(#p)">PAYLOAD</text></svg>', False),
    (f'{SVG}<defs><pattern id="p" width="10" height="10" patternUnits="userSpaceOnUse">'
     f'<rect width="10" height="10"/></pattern></defs><text {AT} fill="url(#p)">PAYLOAD</text></svg>', True),
    # Text outside the drawing: with no y (or y <= 0) its letters sit above the top edge; far right
    # of it or far below it. (A <svg> with no size is 300 x 150.)
    (f'{SVG}<text x="10">PAYLOAD</text></svg>', False),
    (f'{SVG}<text>PAYLOAD</text></svg>', False),
    (f'{SVG}<text x="10" y="0">PAYLOAD</text></svg>', False),
    (f'{SVG}<text x="10" y="-5px">PAYLOAD</text></svg>', False),
    (f'{SVG}<g fill="black"><text x="10">PAYLOAD</text></g></svg>', False),
    (f'{SVG}<text x="1400" y="20">PAYLOAD</text></svg>', False),
    (f'{SVG}<text x="10" y="1200">PAYLOAD</text></svg>', False),
    ('<svg><text x="10" y="1200">PAYLOAD</text></svg>', False),
    ('<svg width="300" height="100" style="overflow-y:visible"><text x="10" y="1200">PAYLOAD</text></svg>', False),
    # ... but drawn where something else places it.
    (f'{SVG}<text x="10" y="20">PAYLOAD</text></svg>', True),
    (f'{SVG}<text x="10" dy="20">PAYLOAD</text></svg>', True),
    (f'{SVG}<text x="10"><tspan dy="20">PAYLOAD</tspan></text></svg>', True),
    (f'{SVG}<text x="10"><tspan y="20">PAYLOAD</tspan></text></svg>', True),
    (f'{SVG}<text x="10"><tspan dy="20">A</tspan><tspan>PAYLOAD</tspan></text></svg>', True),
    (f'{SVG}<defs><path id="p" d="M10 50 H290"/></defs><text><textPath href="#p">PAYLOAD</textPath></text></svg>',
     True),
    (f'{SVG}<g transform="translate(0,20)"><text x="10">PAYLOAD</text></g></svg>', True),
    (f'{SVG}<text x="10" style="transform:translateY(20px)">PAYLOAD</text></svg>', True),
    (f'{SVG}<text x="10" style="translate:0 20px">PAYLOAD</text></svg>', True),
    (f'<style>g{{transform:translateY(20px)}}</style>{SVG}<g><text x="10">PAYLOAD</text></g></svg>', True),
    ('<svg width="300" height="100" viewBox="0 -50 300 100"><text x="10">PAYLOAD</text></svg>', True),
    (f'{SVG}<text x="10" dominant-baseline="hanging">PAYLOAD</text></svg>', True),
    (f'{SVG}<g dominant-baseline="central"><text x="10">PAYLOAD</text></g></svg>', True),
    (f'{SVG}<text x="10" style="dominant-baseline:text-before-edge">PAYLOAD</text></svg>', True),
    (f'{SVG}<text x="10" alignment-baseline="hanging">PAYLOAD</text></svg>', True),
    (f'{SVG}<text x="10" baseline-shift="-20">PAYLOAD</text></svg>', True),
    (f'{SVG}<text x="10" writing-mode="vertical-rl">PAYLOAD</text></svg>', True),
    (f'{SVG}<text x="10" rotate="90">PAYLOAD</text></svg>', True),
    (f'{SVG}<text x="10">PAYLOAD<set attributeName="y" to="20"/></text></svg>', True),
    (f'{SVG}<text x="10" y="0 20 20 20 20 20 20">PAYLOAD</text></svg>', True),
    (f'{SVG}<text x="10" y="2em">PAYLOAD</text></svg>', True),
    (f'{SVG}<text x="10" id="t">PAYLOAD</text><use href="#t" y="20"/></svg>', True),
    # (Overflowing text makes the page no taller: the spacer lets a screenshot reach it.)
    ('<svg width="300" height="100" overflow="visible"><text x="10" y="1200">PAYLOAD</text></svg>'
     '<div style="height:1400px"></div>', True),
    ('<style>svg{overflow:visible}</style><svg width="300" height="100"><text x="10" y="1200">PAYLOAD</text></svg>'
     '<div style="height:1400px"></div>', True),
    (f'{SVG}<text x="10" y="1200" font-size="2000">PAYLOAD</text></svg>', True),
    (f'{SVG}<text x="1400" y="20" text-anchor="end">{"PAYLOAD" * 40}</text></svg>', True),
    ('<svg width="300" height="100" style="height:1300px"><text x="10" y="1200">PAYLOAD</text></svg>', True),
)


def hidden_text(fragments):
    texts = []
    for fragment in fragments:
        texts.append(fragment.text)
    return " ".join(texts)


class SvgTextTests(unittest.TestCase):
    def test_visible_text_is_what_chrome_shows(self):
        for svg_page, chrome_text in SVG_CHROME_PAGES:
            with self.subTest(page=svg_page):
                self.assertEqual(extract_visible_text(svg_page)[0], chrome_text)

    def test_svg_text_that_is_not_drawn_is_reported_hidden(self):
        # A scraper that reads the markup passes this text on, so it is reported.
        for markup in ("<svg>PAYLOAD<text>a</text></svg>", "<svg><g><text>a</text>PAYLOAD</g></svg>",
                       "<svg><rect>PAYLOAD</rect></svg>", "<svg><text><g>PAYLOAD</g></text></svg>"):
            with self.subTest(markup=markup):
                self.assertIn("PAYLOAD", hidden_text(extract_visible_text(page(markup))[1]))

    def test_code_in_svg_that_is_not_drawn_is_not_reported(self):
        # <style> and <script> are code, never text, wherever they are; icon sprites keep their CSS
        # in <defs>.
        markup = "<svg><defs><style>.a{fill:red}</style><script>go()</script></defs><text>a</text></svg>"
        visible_text, fragments = extract_visible_text(page(markup))
        self.assertEqual(visible_text, "a x")
        self.assertEqual(hidden_text(fragments), "")

    def test_an_element_read_alone_keeps_its_place_in_the_svg(self):
        drawn = page("<svg><text><tspan>T</tspan></text><g><tspan>PAYLOAD</tspan></g></svg>")
        self.assertEqual(extract_visible_text(drawn, "//text/tspan")[0], "T")
        self.assertEqual(extract_visible_text(drawn, "//g/tspan")[0], "")


class LongValueTests(unittest.TestCase):
    """Sizes of thousands of digits are read in linear time, and never crash the reader; deep and
    large drawings are read in time proportional to their size."""

    def test_deep_and_large_drawings_are_read_quickly(self):
        import time

        gradients = "".join(f'<linearGradient id="g{index}"><stop stop-color="black"/></linearGradient>'
                            for index in range(300))
        labels = "".join(f'<text fill="url(#g{index})">a</text><text fill="#fff">b</text>' for index in range(300))
        spans = "<tspan>s</tspan>" * 3000
        markup = (f"<svg><defs>{gradients}</defs>{'<rect/>' * 300}{labels}"
                  + '<g fill="red">' * 450 + f"<text>{spans}</text>" + "</g>" * 450 + "</svg>")
        started = time.perf_counter()
        extract_visible_text(page(markup))
        self.assertLess(time.perf_counter() - started, 3)

    def test_long_sizes_are_read_quickly(self):
        import time

        zeros = "0" * 4000  # tinycss2 cannot read a number of more than 4300 digits
        rules = "".join(f".s{index}{{width:{zeros}1px}}" for index in range(50))
        classes = " ".join(f"s{index}" for index in range(50))
        digits = "0" * 30000
        for markup in (f'<style>{rules}</style><svg class="{classes}"><text>a</text></svg>',
                       f'<svg><foreignObject width="{digits}x" height="1{digits}!"><p>a</p></foreignObject></svg>',
                       f'<svg><text font-size="{digits}x">a</text><text opacity="{digits}1">b</text></svg>',
                       f'<svg><text font-size="{digits}!">a</text></svg>'):
            with self.subTest(markup=markup[:60]):
                started = time.perf_counter()
                extract_visible_text(page(markup))
                self.assertLess(time.perf_counter() - started, 1)


class NotDrawnTests(unittest.TestCase):
    """Cases where the reader hides what Chrome's innerText counts."""

    def test_text_is_shown_where_chrome_paints_it(self):
        for markup, painted in SVG_PAINT_CASES:
            with self.subTest(markup=markup):
                visible_text, fragments = extract_visible_text(page(markup))
                if painted:
                    self.assertIn("PAYLOAD", visible_text)
                else:
                    self.assertNotIn("PAYLOAD", visible_text)
                    self.assertIn("PAYLOAD", hidden_text(fragments))

    def test_text_outside_the_drawing_goes_to_review(self):
        # Text with no y is a common authoring slip as well as a hiding place: hidden, at MEDIUM.
        for markup in (f'{SVG}<text x="10">PAYLOAD</text></svg>', f'{SVG}<text x="1400" y="20">PAYLOAD</text></svg>'):
            with self.subTest(markup=markup):
                fragments = extract_visible_text(page(markup))[1]
                self.assertEqual([fragment.severity for fragment in fragments], ["medium"])

    def test_definitions_are_not_drawn(self):
        # Chrome's innerText includes this text, but it is not painted (a screenshot with and
        # without it is identical): definitions are drawn only where something references them,
        # which this reader does not follow, so the text counts as hidden.
        for tag in ("defs", "symbol", "mask", "clipPath", "pattern", "marker"):
            with self.subTest(tag=tag):
                visible_text, fragments = extract_visible_text(page(f"<svg><{tag}><text>PAYLOAD</text></{tag}></svg>"))
                self.assertEqual(visible_text, "x")
                self.assertIn("PAYLOAD", hidden_text(fragments))

    def test_a_font_size_chrome_ignores_leaves_the_text_shown(self):
        # Measured in Chrome 157: "1." is not a number, so the font-size stays 16px.
        markup = f'{SVG}<text x="10" y="50" font-size="1.">PAYLOAD</text></svg>'
        self.assertIn("PAYLOAD", extract_visible_text(page(markup))[0])

    def test_an_unreadable_font_size_in_an_unscaled_drawing_is_hidden(self):
        # Without a viewBox or a transform a user unit is a CSS pixel, so the attribute is read
        # as CSS font-size is: text this small is practically invisible (Chrome still paints it).
        for size in ("1", "1px", "1.5", "1e0", "+1", "10e-1px", "1E0PX"):
            with self.subTest(size=size):
                markup = f'{SVG}<text x="10" y="50" font-size="{size}">PAYLOAD</text></svg>'
                visible_text, fragments = extract_visible_text(page(markup))
                self.assertNotIn("PAYLOAD", visible_text)
                self.assertIn("PAYLOAD", hidden_text(fragments))

    def test_a_light_fill_over_svg_shapes_is_only_suspected(self):
        # A shape in the drawing may be what the text is painted on, which this reader does not
        # work out, so text that would vanish on the page background is a medium finding.
        markup = (f'<div style="background:white">{SVG}<rect width="300" height="100" fill="black"/>'
                  f'<text {AT} fill="white">PAYLOAD</text></svg></div>')
        visible_text, fragments = extract_visible_text(page(markup))
        self.assertNotIn("PAYLOAD", visible_text)
        severities = [fragment.severity for fragment in fragments if "PAYLOAD" in fragment.text]
        self.assertEqual(severities, ["medium"])

    def test_text_that_depends_on_the_browser_language_counts_as_hidden(self):
        # systemLanguage holds when it names the browser's language, which differs between
        # readers; neither the text nor a <switch> choice after it can be decided.
        for markup in ('<svg><text systemLanguage="en">PAYLOAD</text></svg>',
                       '<svg><switch><text systemLanguage="en">PAYLOAD</text><text>PAYLOAD</text></switch></svg>'):
            with self.subTest(markup=markup):
                self.assertEqual(extract_visible_text(page(markup))[0], "x")


if __name__ == "__main__":
    unittest.main()
