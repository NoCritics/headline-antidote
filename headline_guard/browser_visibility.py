"""What a reader actually sees, computed by a real browser.

Chrome's `inner_text()` drops `display:none` and `visibility:hidden`, but keeps text
hidden by a zero or tiny font, near-zero opacity, a color matching the background,
off-screen positioning, clipping, or an element drawn over it. This script asks the
browser for the computed style, geometry and hit-testing of every text node instead,
using the same thresholds as the guard's own HTML check. Because the browser runs the
page, it also covers external stylesheets, complex selectors and JavaScript.

Two ways to use it:

1. With your own Playwright page or locator (Playwright itself is not imported here):

    visible = rendered_visible_text(page.locator("h1").first)

2. With BrowserVerifier, a warm Chrome that renders the HTML your scraper already
   fetched (no second download of the page), for the pages extract_article() marks
   with needs_browser_check:

    with BrowserVerifier() as verifier:
        article = guard.extract_article(html, feed_title=title)
        if article.needs_browser_check:
            article = guard.verify_article_in_browser(article, html, url, verifier)

Limits: a page can still change after the settling time, and hit-testing does not
see elements with pointer-events:none or ::before/::after boxes as separate layers
(the static check covers those pseudo-elements).
"""

import re
import time
from dataclasses import dataclass

from .css_hiding import (
    MINIMUM_READABLE_FONT_SIZES,
    MINIMUM_VISIBLE_CONTRAST,
    MINIMUM_VISIBLE_OPACITY,
    OPAQUE_ALPHA,
)

# A fixed box at least this share of the viewport is a page overlay (paywall, consent
# dialog), not a cover over a few words; so is one stuck to the bottom edge (cookie bar).
PAGE_OVERLAY_VIEWPORT_SHARE = 0.3
# Text cut off by a clipping box at least this tall and wide is behind a preview window
# (a metered paywall, a carousel, a collapsed section): the publisher's own text, reported
# separately from text hidden from readers.
PREVIEW_WINDOW_MINIMUM_PIXELS = 48
VIEWPORT = {"width": 1366, "height": 900}
# The rendered heading must share at least this share of words with the static one.
MINIMUM_HEADING_OVERLAP = 0.5
DEFAULT_SETTLE_MILLISECONDS = 400
# Some pages show their article only after a fade-in or a paywall script decides (seen on ABC
# and CNBC): when the first read shows less than RETRY_VISIBLE_SHARE of the words expected,
# the page is read once more after this much longer.
RETRY_SETTLE_MILLISECONDS = 3500
RETRY_VISIBLE_SHARE = 0.05
# How often the page is served when its scripts navigate (redirect loops are cut off).
MAXIMUM_DOCUMENT_SERVES = 3
DEFAULT_TIMEOUT_MILLISECONDS = 8000
BLOCKED_RESOURCE_TYPES = ("image", "media", "font")

# Finds the rendered heading whose full text (hidden parts included) best matches the
# heading the static reading found: scripts often rebuild the page, so a path from the
# static HTML can point elsewhere. It runs in the same call as the visibility walk, so a
# script cannot replace the heading in between.
MARK_HEADLINE_SCRIPT = """
([expected, xpath, minimumOverlap]) => {
  const words = (text) => new Set((text.toLowerCase().match(/[\\p{L}\\p{N}]+/gu) || []));
  const wanted = words(expected);
  if (wanted.size === 0) return false;
  const candidates = Array.from(document.querySelectorAll('h1, h2, [role="heading"]'));
  try {
    const byPath = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
    if (byPath && byPath.nodeType === 1) candidates.unshift(byPath);
  } catch (error) {}
  let best = null;
  let bestScore = 0;
  for (const element of candidates) {
    const found = words(element.textContent);
    let shared = 0;
    for (const word of found) if (wanted.has(word)) shared += 1;
    const score = shared / Math.max(wanted.size, found.size, 1);
    if (score > bestScore) { best = element; bestScore = score; }
  }
  if (!best || bestScore < minimumOverlap) return null;
  return best;
}
"""

VISIBLE_TEXT_SCRIPT = """
(root, limits) => {
  const parseColor = (text) => {
    const match = text.match(/rgba?\\(([^)]+)\\)/);
    if (!match) return null;
    const parts = match[1].split(/[ ,\\/]+/).filter((part) => part.length > 0).map(Number);
    return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
  };
  const luminance = (color) => {
    const channel = (value) => {
      const fraction = value / 255;
      return fraction <= 0.03928 ? fraction / 12.92 : Math.pow((fraction + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
  };
  const contrast = (first, second) => {
    const lighter = Math.max(luminance(first), luminance(second));
    const darker = Math.min(luminance(first), luminance(second));
    return (lighter + 0.05) / (darker + 0.05);
  };
  // The page's extent. A scroll lock (a consent dialog opening on scroll fixes <body> in
  // place) shrinks the document to one screen, so the body's own extent counts too.
  const bodyElement = document.body || document.documentElement;
  const pageWidth = Math.max(document.documentElement.scrollWidth, bodyElement.scrollWidth, window.innerWidth);
  const pageHeight = Math.max(document.documentElement.scrollHeight, bodyElement.scrollHeight, window.innerHeight);
  const replacedTags = new Set(['IMG', 'VIDEO', 'CANVAS', 'IFRAME', 'OBJECT', 'EMBED', 'svg', 'SVG', 'PICTURE']);

  const isOpaque = (element) => {
    if (replacedTags.has(element.tagName)) return true;
    const style = getComputedStyle(element);
    const background = parseColor(style.backgroundColor);
    return background !== null && background.a >= limits.opaqueAlpha && parseFloat(style.opacity) >= limits.opaqueAlpha;
  };
  // Part of a fixed or sticky layer over the page (a consent dialog, paywall, cookie bar),
  // judged by the fixed box itself, which may be an ancestor of the element hit.
  const pageOverlayCache = new Map();
  const isPageOverlay = (element) => {
    if (pageOverlayCache.has(element)) return pageOverlayCache.get(element);
    let result = false;
    for (let node = element; node && node !== document.body && node !== document.documentElement; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.position !== 'fixed' && style.position !== 'sticky' && style.position !== 'absolute') continue;
      const box = node.getBoundingClientRect();
      const large = box.width * box.height >= limits.pageOverlayShare * window.innerWidth * window.innerHeight;
      // A layer this large would hide the whole page, so it is a dialog, not a cover over a few words.
      if (large || (style.position !== 'absolute' && box.bottom >= window.innerHeight - 2)) {
        result = true;
        break;
      }
    }
    pageOverlayCache.set(element, result);
    return result;
  };
  // Is the text drawn over a picture (an image or video behind it)? Then its real
  // background is unknown (images are not downloaded), so contrast cannot be judged.
  const overPicture = (textNode, owner) => {
    const range = document.createRange();
    range.selectNodeContents(textNode);
    let box = range.getClientRects()[0];
    if (!box) return false;
    if (box.top < 0 || box.bottom > window.innerHeight) {
      window.scrollTo(0, window.scrollY + box.top - window.innerHeight / 2);
      box = range.getClientRects()[0];
      if (!box) return false;
    }
    const stack = document.elementsFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    let belowOwner = false;
    for (const element of stack) {
      if (element === owner || element.contains(owner)) belowOwner = true;
      if (replacedTags.has(element.tagName)) return true;
      if (belowOwner && getComputedStyle(element).backgroundImage !== 'none') return true;
    }
    return false;
  };
  // Is the point covered by something drawn over the text's own element?
  const coveredAt = (x, y, owner) => {
    const stack = document.elementsFromPoint(x, y);
    for (const element of stack) {
      if (element === owner) return false;
      if (owner.contains(element)) continue;
      if (element.contains(owner)) {
        // An enclosing box drawn above its own content: the text has a negative z-index.
        if (element.tagName !== 'HTML' && element.tagName !== 'BODY' && isOpaque(element)) return true;
        continue;
      }
      if (isPageOverlay(element)) continue;
      if (isOpaque(element)) return true;
    }
    return false;
  };
  const isCovered = (textNode, owner) => {
    const range = document.createRange();
    range.selectNodeContents(textNode);
    let boxes = Array.from(range.getClientRects()).filter((box) => box.width >= 1 && box.height >= 1).slice(0, 3);
    if (boxes.length === 0) return false;
    if (boxes[0].top < 0 || boxes[0].bottom > window.innerHeight) {
      window.scrollTo(0, window.scrollY + boxes[0].top - window.innerHeight / 2);
      boxes = Array.from(range.getClientRects()).filter((box) => box.width >= 1 && box.height >= 1).slice(0, 3);
    }
    let covered = 0;
    let sampled = 0;
    for (const box of boxes) {
      const x = box.left + box.width / 2;
      const y = box.top + box.height / 2;
      if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) continue;
      sampled += 1;
      if (coveredAt(x, y, owner)) covered += 1;
    }
    return sampled > 0 && covered * 2 >= sampled;
  };

  // 0: hidden, 1: visible, 2: cut off by a large clipping box (a preview window).
  const HIDDEN = 0, VISIBLE = 1, CLIPPED = 2;
  const visibility = (textNode) => {
    const element = textNode.parentElement;
    if (!element) return HIDDEN;
    const style = getComputedStyle(element);
    if (style.visibility === 'hidden' || style.visibility === 'collapse') return HIDDEN;
    if (parseFloat(style.fontSize) < limits.minimumFontPixels) return HIDDEN;

    let opacity = 1;
    let background = null;
    let backgroundIsImage = false;
    for (let ancestor = element; ancestor; ancestor = ancestor.parentElement) {
      const ancestorStyle = getComputedStyle(ancestor);
      if (ancestorStyle.display === 'none') return HIDDEN;
      if (ancestorStyle.contentVisibility === 'hidden') return HIDDEN;
      opacity *= parseFloat(ancestorStyle.opacity);
      if (background === null && !backgroundIsImage) {
        if (ancestorStyle.backgroundImage && ancestorStyle.backgroundImage !== 'none') backgroundIsImage = true;
        const ancestorBackground = parseColor(ancestorStyle.backgroundColor);
        if (ancestorBackground && ancestorBackground.a >= limits.minimumOpacity) background = ancestorBackground;
      }
    }
    if (opacity < limits.minimumOpacity) return HIDDEN;

    const fill = style.webkitTextFillColor ? parseColor(style.webkitTextFillColor) : null;
    const textColor = fill || parseColor(style.color);
    const paintedByBackground = (style.webkitBackgroundClip === 'text' || style.backgroundClip === 'text');
    const hasShadow = style.textShadow && style.textShadow !== 'none';
    if (textColor && !paintedByBackground && !hasShadow) {
      if (textColor.a < limits.minimumOpacity) return HIDDEN;
      const pageBackground = background || { r: 255, g: 255, b: 255, a: 1 };
      if (contrast(textColor, pageBackground) < limits.minimumContrast
          && !backgroundIsImage && !overPicture(textNode, element)) return HIDDEN;
    }

    const range = document.createRange();
    range.selectNodeContents(textNode);
    const box = range.getBoundingClientRect();
    if (box.width < 1 || box.height < 1) return HIDDEN;
    const left = box.left + window.scrollX;
    const top = box.top + window.scrollY;
    if (left + box.width <= 0 || top + box.height <= 0 || left >= pageWidth || top >= pageHeight) return HIDDEN;

    // Clipping by an ancestor (overflow hidden, clip, clip-path): keep only text mostly inside it.
    // <body> and <html> don't count: a consent dialog's scroll lock fixes <body> with overflow
    // hidden, which cuts the page off at one screen without hiding anything from readers.
    for (let ancestor = element; ancestor && ancestor !== document.body && ancestor !== document.documentElement;
         ancestor = ancestor.parentElement) {
      const ancestorStyle = getComputedStyle(ancestor);
      const clips = ancestorStyle.overflow !== 'visible' || ancestorStyle.clip !== 'auto' || ancestorStyle.clipPath !== 'none';
      if (!clips) continue;
      const clipBox = ancestor.getBoundingClientRect();
      const overlapWidth = Math.max(0, Math.min(box.right, clipBox.right) - Math.max(box.left, clipBox.left));
      const overlapHeight = Math.max(0, Math.min(box.bottom, clipBox.bottom) - Math.max(box.top, clipBox.top));
      if (ancestorStyle.clip.startsWith('rect(0px, 0px, 0px, 0px') || ancestorStyle.clipPath.startsWith('inset(50%')) return HIDDEN;
      if (overlapWidth * overlapHeight < 0.5 * box.width * box.height) {
        const previewWindow = clipBox.height >= limits.previewMinimumPixels && clipBox.width >= limits.previewMinimumPixels;
        return previewWindow ? CLIPPED : HIDDEN;
      }
    }
    if (limits.checkCovering && isCovered(textNode, element)) return HIDDEN;
    return VISIBLE;
  };

  const startScroll = window.scrollY;
  const parts = [];
  const clippedParts = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const textNode = walker.currentNode;
    const parentTag = textNode.parentElement ? textNode.parentElement.tagName : '';
    if (parentTag === 'SCRIPT' || parentTag === 'STYLE' || parentTag === 'NOSCRIPT' || parentTag === 'TEMPLATE') continue;
    if (textNode.textContent.trim() === '') {
      parts.push(textNode.textContent);
      continue;
    }
    const state = visibility(textNode);
    if (state === VISIBLE) {
      parts.push(textNode.textContent);
    } else {
      parts.push(' ');
      if (state === CLIPPED) clippedParts.push(textNode.textContent);
    }
  }
  window.scrollTo(0, startScroll);
  return limits.withClipped ? { visible: parts.join(''), clipped: clippedParts.join(' ') } : parts.join('');
}
"""


HEADLINE_TEXT_SCRIPT = (
    "([expected, xpath, minimumOverlap, limits]) => { const findHeading = " + MARK_HEADLINE_SCRIPT.strip()
    + "; const visibleText = " + VISIBLE_TEXT_SCRIPT.strip()
    + "; const heading = findHeading([expected, xpath, minimumOverlap]);"
    " return heading ? visibleText(heading, limits) : null; }"
)
BODY_TEXT_SCRIPT = (
    "(limits) => { const visibleText = " + VISIBLE_TEXT_SCRIPT.strip()
    + "; return document.body ? visibleText(document.body, limits) : { visible: '', clipped: '' }; }"
)


def _limits(check_covering, with_clipped=False):
    return {
        "previewMinimumPixels": PREVIEW_WINDOW_MINIMUM_PIXELS,
        "withClipped": with_clipped,
        "minimumFontPixels": MINIMUM_READABLE_FONT_SIZES["px"],
        "minimumOpacity": MINIMUM_VISIBLE_OPACITY,
        "minimumContrast": MINIMUM_VISIBLE_CONTRAST,
        "opaqueAlpha": OPAQUE_ALPHA,
        "pageOverlayShare": PAGE_OVERLAY_VIEWPORT_SHARE,
        "checkCovering": check_covering,
    }


def rendered_visible_text(locator, check_covering=True):
    """Text of a Playwright locator (or element handle) that a reader can actually see.

    check_covering: also drop text another element is drawn over (hit-testing); slower.
    """
    return re.sub(r"\s+", " ", locator.evaluate(VISIBLE_TEXT_SCRIPT, _limits(check_covering))).strip()


def rendered_text_parts(locator, check_covering=True):
    """(visible text, text cut off by a preview window such as a metered paywall)."""
    parts = locator.evaluate(VISIBLE_TEXT_SCRIPT, _limits(check_covering, with_clipped=True))
    return re.sub(r"\s+", " ", parts["visible"]).strip(), re.sub(r"\s+", " ", parts["clipped"]).strip()


def _site_of(url):
    """The last two labels of the host name ("www.cnbc.com" -> "cnbc.com"), as a cheap site key."""
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or "").lower()
    labels = host.split(".")
    if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in ("co", "com", "net", "org", "ac", "gov"):
        return ".".join(labels[-3:])  # news.yahoo.co.jp -> yahoo.co.jp
    return ".".join(labels[-2:])


@dataclass
class RenderedPage:
    headline_text: str      # visible text of the headline element, or None when it was not found
    page_text: str          # visible text of the whole <body>
    clipped_text: str       # text of the <body> cut off by a preview window (paywall, collapsed section)
    milliseconds: float
    complete: bool          # False when loading timed out; the texts are then what had rendered
    note: str = ""


class BrowserVerifier:
    """A warm Chrome that renders pages from HTML the caller already fetched.

    The page's own address is used, so relative stylesheets and scripts load as they do
    for readers, but the main document is served from the given HTML: Chrome checks
    exactly what the scraper saw. Images, media and fonts are not downloaded. Scripts and
    stylesheets are, from any site, because a third-party script is one way to hide text.

    Uses Google Chrome (channel="chrome"); needs playwright (pip install playwright).
    """

    def __init__(self, channel="chrome", settle_milliseconds=DEFAULT_SETTLE_MILLISECONDS,
                 timeout_milliseconds=DEFAULT_TIMEOUT_MILLISECONDS, blocked_resource_types=BLOCKED_RESOURCE_TYPES,
                 same_site_only=False):
        """same_site_only: load scripts and stylesheets only from the page's own site. Faster
        (no ads or analytics), but a compromised third-party script then goes unseen."""
        self.channel = channel
        self.same_site_only = same_site_only
        self.settle_milliseconds = settle_milliseconds
        self.timeout_milliseconds = timeout_milliseconds
        self.blocked_resource_types = set(blocked_resource_types)
        self._playwright = None
        self._browser = None

    def start(self):
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(channel=self.channel, headless=True)
        return self

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def __enter__(self):
        return self.start()

    def __exit__(self, exception_type, exception, traceback):
        self.close()

    def render(self, url, html, headline_xpath=None, heading_text=None, expected_words=None):
        """Renders html as the page at url and returns what a reader sees (RenderedPage).

        heading_text: the heading's full text as the static reading found it; the rendered
        heading is the one whose text matches it best (headline_xpath is tried first).
        expected_words: about how many words the article has; a first read showing far fewer
        is repeated once after RETRY_SETTLE_MILLISECONDS.
        """
        from playwright.sync_api import Error as PlaywrightError

        if self._browser is None:
            self.start()
        started = time.perf_counter()
        context = self._browser.new_context(viewport=VIEWPORT, service_workers="block")
        page = context.new_page()
        served = {"documents": 0}
        page_site = _site_of(url)

        def handle(route):
            request = route.request
            if request.resource_type == "document" and request.frame == page.main_frame:
                # A script navigating elsewhere (a regional redirect such as bbc.co.uk -> bbc.com)
                # gets the same page again, so the check stays on what the scraper fetched.
                served["documents"] += 1
                if served["documents"] > MAXIMUM_DOCUMENT_SERVES:
                    route.abort()
                else:
                    route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
            elif request.resource_type in self.blocked_resource_types:
                route.abort()
            elif self.same_site_only and _site_of(request.url) != page_site:
                route.abort()
            else:
                route.continue_()

        page.route("**/*", handle)
        complete = True
        note = ""
        try:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_milliseconds)
            except PlaywrightError as error:
                complete = False
                note = str(error).split("\n")[0]
            page.wait_for_timeout(self.settle_milliseconds)
            headline_text, page_text, clipped_text, complete, note = self._read(
                page, headline_xpath, heading_text, complete, note)
            shown_words = len(page_text.split()) + len(clipped_text.split())
            if expected_words and shown_words < RETRY_VISIBLE_SHARE * expected_words:
                page.wait_for_timeout(RETRY_SETTLE_MILLISECONDS)
                headline_text, page_text, clipped_text, complete, note = self._read(
                    page, headline_xpath, heading_text, complete, note)
        finally:
            context.close()
        return RenderedPage(headline_text, page_text, clipped_text, (time.perf_counter() - started) * 1000,
                            complete, note)

    def _read(self, page, headline_xpath, heading_text, complete, note):
        """(headline_text, page_text, clipped_text, complete, note) as the page shows now."""
        from playwright.sync_api import Error as PlaywrightError

        headline_text = None
        page_text = ""
        clipped_text = ""
        for attempt in range(2):
            try:
                if heading_text:
                    headline_text = page.evaluate(
                        HEADLINE_TEXT_SCRIPT,
                        [heading_text, headline_xpath or "", MINIMUM_HEADING_OVERLAP, _limits(True)],
                    )
                    if headline_text is not None:
                        headline_text = re.sub(r"\s+", " ", headline_text).strip()
                parts = page.evaluate(BODY_TEXT_SCRIPT, _limits(True, with_clipped=True))
                page_text = re.sub(r"\s+", " ", parts["visible"]).strip()
                clipped_text = re.sub(r"\s+", " ", parts["clipped"]).strip()
                break
            except PlaywrightError as error:
                message = str(error).split("\n")[0]
                if attempt == 0 and "context was destroyed" in message:
                    # The page navigated while being read (a script redirect): read the new one.
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=self.timeout_milliseconds)
                        page.wait_for_timeout(self.settle_milliseconds)
                    except PlaywrightError:
                        pass
                    continue
                complete = False
                note = note or message
        return headline_text, page_text, clipped_text, complete, note
