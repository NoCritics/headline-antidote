"""Test pages for the scraper comparison: the paper's attacks, variants and clean controls.

Every page is a small article. The attack sits in the <h1> headline; the <title>
carries the same text a reader would see in the browser tab.
"""

from dataclasses import dataclass
from typing import Callable

VISIBLE_HEADLINE = "Alphabet shares surge after dodging antitrust breakup bullet"
HIDDEN_PAYLOAD = "losses and layoffs"
ARTICLE_BODY = (
    "<p>Shares of Alphabet rose sharply on Tuesday after a federal judge declined to order "
    "a breakup of the company, a ruling analysts said removes a major overhang.</p>"
    "<p>The decision lifted other large technology stocks as investors bet that regulators "
    "would struggle to force structural remedies on the sector.</p>"
)


@dataclass
class TestPage:
    name: str
    description: str
    html: str
    is_attack: bool
    # True when the attack survived into the scraper's text.
    attack_survives: Callable[[str], bool]


def _page(headline_html, title_text=VISIBLE_HEADLINE, head_extra="", body_extra=""):
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{title_text}</title>{head_extra}</head>"
        f"<body><article><h1>{headline_html}</h1>{ARTICLE_BODY}</article>{body_extra}</body></html>"
    )


def _contains_payload(text):
    return HIDDEN_PAYLOAD.split()[0] in text


def _never(text):
    return False


def _encode_as_tag_characters(text):
    tag_characters = []
    for character in text:
        tag_characters.append(chr(0xE0000 + ord(character)))
    return "".join(tag_characters)


def _contains_tag_characters(text):
    for character in text:
        if 0xE0000 <= ord(character) <= 0xE007F:
            return True
    return False


def _hidden_span_page(name, description, span_attributes, head_extra=""):
    return TestPage(
        name, description,
        _page(f"{VISIBLE_HEADLINE}<span {span_attributes}> {HIDDEN_PAYLOAD}</span>", head_extra=head_extra),
        True, _contains_payload,
    )


HOMOGLYPH_HEADLINE = VISIBLE_HEADLINE.replace("Alphabet", "Аlphаbet", 1)  # Cyrillic А and а
ZERO_WIDTH_HEADLINE = VISIBLE_HEADLINE.replace("Alphabet", "Alpha​bet", 1)
TAG_HEADLINE = VISIBLE_HEADLINE + _encode_as_tag_characters(" " + HIDDEN_PAYLOAD)
RUSSIAN_HEADLINE = "Акции Alphabet выросли после решения суда"


def _contains_cyrillic_lookalike(text):
    return "Аlphаbet" in text


def _contains_zero_width(text):
    return "​" in text


TEST_PAGES = [
    TestPage("clean_english", "Control: an ordinary headline", _page(VISIBLE_HEADLINE), False, _never),
    TestPage(
        "clean_russian", "Control: a Russian headline with a Latin brand name",
        _page(RUSSIAN_HEADLINE, title_text=RUSSIAN_HEADLINE), False, _never,
    ),
    TestPage(
        "clean_styled", "Control: visible styling (colors, small source label)",
        _page(
            f'<span style="color:#1a1a1a">{VISIBLE_HEADLINE}</span>',
            body_extra='<p style="font-size:10px;color:#666">Reuters</p>',
        ),
        False, _never,
    ),
    TestPage(
        "homoglyph_name", "Paper attack 1: Cyrillic А and а in 'Alphabet' (title and h1)",
        _page(HOMOGLYPH_HEADLINE, title_text=HOMOGLYPH_HEADLINE), True, _contains_cyrillic_lookalike,
    ),
    TestPage(
        "zero_width_in_name", "Zero-width space inside 'Alphabet' (title and h1)",
        _page(ZERO_WIDTH_HEADLINE, title_text=ZERO_WIDTH_HEADLINE), True, _contains_zero_width,
    ),
    TestPage(
        "tag_characters", "Hidden text as invisible Unicode tag characters (title and h1)",
        _page(TAG_HEADLINE, title_text=TAG_HEADLINE), True, _contains_tag_characters,
    ),
    _hidden_span_page("display_none", "Paper attack 2: display:none span", 'style="display:none"'),
    _hidden_span_page("font_size_zero", "Paper variant: font-size:0pt span", 'style="font-size:0pt"'),
    _hidden_span_page(
        "color_matches_background", "Paper variant: white text on a declared white background",
        'style="color:#ffffff;background-color:#ffffff"',
    ),
    _hidden_span_page(
        "style_block_class", "Hidden by a class rule in a <style> block", 'class="note"',
        head_extra="<style>.note { display: none; }</style>",
    ),
    _hidden_span_page("tiny_font", "Near-invisible: 1px font", 'style="font-size:1px"'),
    _hidden_span_page("near_zero_opacity", "Near-invisible: opacity 0.01", 'style="opacity:0.01"'),
    _hidden_span_page(
        "white_text_undeclared_background", "White text; the white page background is not declared",
        'style="color:#fff"',
    ),
    _hidden_span_page(
        "off_screen", "Positioned off-screen", 'style="position:absolute;left:-9999px"',
    ),
    _hidden_span_page(
        "complex_selector", "Hidden by a descendant selector the guard does not parse (h1 > span.x)",
        'class="x"', head_extra="<style>h1 > span.x { display: none; }</style>",
    ),
    TestPage(
        "javascript_hidden", "Hidden by JavaScript after load (display:none)",
        _page(
            f'{VISIBLE_HEADLINE}<span id="p"> {HIDDEN_PAYLOAD}</span>',
            body_extra="<script>document.getElementById('p').style.display='none';</script>",
        ),
        True, _contains_payload,
    ),
    _hidden_span_page(
        "complex_selector_font_size", "Descendant selector setting font-size:0 (browsers keep it in inner_text)",
        'class="x"', head_extra="<style>h1 > span.x { font-size: 0; }</style>",
    ),
    _hidden_span_page(
        "complex_selector_opacity", "Descendant selector setting opacity:0",
        'class="x"', head_extra="<style>article h1 span.x { opacity: 0; }</style>",
    ),
    TestPage(
        "javascript_opacity", "JavaScript adds a class whose complex rule sets opacity:0",
        _page(
            f'{VISIBLE_HEADLINE}<span id="p"> {HIDDEN_PAYLOAD}</span>',
            head_extra="<style>article h1 span.gone { opacity: 0; }</style>",
            body_extra="<script>document.getElementById('p').className='gone';</script>",
        ),
        True, _contains_payload,
    ),
    TestPage(
        "clean_javascript_rendered", "Control: headline inserted by JavaScript (client-side rendering)",
        _page(
            "",
            body_extra=f"<script>document.querySelector('h1').textContent='{VISIBLE_HEADLINE}';</script>",
        ),
        False, _never,
    ),
    TestPage(
        "javascript_rendered_homoglyph", "Homoglyph in a headline inserted by JavaScript",
        _page(
            "",
            body_extra=f"<script>document.querySelector('h1').textContent='{HOMOGLYPH_HEADLINE}';</script>",
        ),
        True, _contains_cyrillic_lookalike,
    ),
    TestPage(
        "clean_dark_theme", "Control: white headline on a dark background set by a rule the guard cannot parse",
        _page(
            f'<span style="color:#ffffff">{VISIBLE_HEADLINE}</span>',
            head_extra="<style>body > article { background-color: #111827; }</style>",
        ),
        False, _never,
    ),
]
