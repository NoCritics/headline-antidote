---
name: verify
description: How to verify a headline_antidote change at its package boundary - build the wheel, install it into its own folder, drive HeadlineAntidote over served pages with the headless-Chrome browser check.
---

# Verifying headline_antidote

The surface is the installed package: `from headline_antidote import HeadlineAntidote`, `extract_article`,
`verify_article_in_browser`, `to_dict()`. Drive it, not the repo's modules.

## Build and install (offline, no new downloads)

From the repo root, with the project venv (`.venv/Scripts/python.exe`; system Python lacks tinycss2):

```bash
rm -rf build
.venv/Scripts/python.exe -m pip wheel --no-build-isolation --no-deps --no-index -q -w <dir>/wheel .
.venv/Scripts/python.exe -m pip install -q --no-deps --no-index --target <dir>/install <dir>/wheel/*.whl
```

For a before/after comparison, `git stash` the change, build a second wheel, then `git stash pop`.
The deps (tinycss2, playwright, lexbor parser, requests) come from the venv.

## Drive

- Driver: `sys.path.insert(0, <install dir>)`, then import headline_antidote and print `headline_antidote.__file__`
  to prove the installed copy loaded. Run it from outside the repo so the source tree is not on the path.
- Serve the test pages with `python -m http.server <port> --bind 127.0.0.1` in their folder; fetch with
  `requests` and set `response.encoding = "utf-8"` (a wrong decoding once gave a false pass).
- `with BrowserVerifier() as verifier:` then `guard.verify_article_in_browser(article, html, url, verifier)`.
  Chrome runs headless (no window); the user still wants to hear before a run.
- Print verdict, headline and each flag's (category, severity, field, flagged_text, evidence), static and
  after the browser check. The browser check is the Chrome ground truth for the same page.

## Gotchas

- Hidden words in an `<h1>` that the `<title>` lacks show up statically as `headline_adds_words` (low)
  when the reader thinks they are visible; a high `hidden_html_text` when it thinks they are hidden.
- The venv holds an editable install of the repo, so a wrong install path silently imports the repo
  copy. Git Bash converts `/c/...` to `C:\...` only in command arguments: inside a `python -c` string
  or a script, write the Windows path. Always check the printed `__file__`.
- Chrome 158 crashes the tab on `inherit(var(--n))`; `verify_article_in_browser` then raises
  `TargetClosedError`.
