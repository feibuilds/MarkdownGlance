# Contributing to MarkdownGlance

Issues and pull requests are welcome.

## Running the tests

The parser is the Package Control `Markdown` library, so the tests need it and
`pymdown-extensions` installed. Package Control serves a different release to
each plugin host; install the pair for the Python you are running:

```bash
python -m pip install "Markdown==3.2.2" "pymdown-extensions==8.1.1"    # Python 3.8, build 4200
python -m pip install "Markdown==3.10.3" "pymdown-extensions==11.0.2"  # Python 3.13 and later
```

The package imports itself as `MarkdownGlance.preview`, so the checkout
directory must be named `MarkdownGlance` and the tests run from its parent:

```bash
python -m unittest discover -s MarkdownGlance/tests -t . -p 'test_*.py'
```

CI runs the same suite on Linux, macOS and Windows against Python 3.8 — the
Sublime Text 4200 runtime — and Python 3.14, each with the library pair its
host receives. Code that has to run inside Sublime Text must stay valid on 3.8.

## Trying a change in Sublime Text

Clone or symlink the checkout into the directory that **Preferences → Browse
Packages…** opens, under the name `MarkdownGlance`. Sublime Text reloads the
plugin on save. Before a release, walk the
[manual test plan](docs/manual-test-plan.md).

## Pull requests

- A behavioural change should come with a test.
- A decision that constrains the design belongs in a new ADR under
  [`docs/adr`](docs/adr); follow the numbering and shape of the existing ones.
- Keep the commit subject in the imperative mood and under about 72 characters.
- Note anything user-visible in [`CHANGELOG.md`](CHANGELOG.md) under
  *Unreleased*.

## Scope

MarkdownGlance renders Markdown with the Sublime API alone: no browser, no
WebView, no external process, and no runtime dependency outside the standard
library and the two Package Control libraries it declares. `Open in Browser`
is an export, off the preview path, and the one command that starts a process.
A change that needs more than this is unlikely to be accepted — open an issue
first and let us talk it through.
