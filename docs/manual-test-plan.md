# MarkdownGlance manual test plan

## Matrix

Run the release matrix on Linux, macOS and Windows with Sublime Text build
4200/Python 3.8. The newest available dev build/Python 3.14 is optional
forward-compatibility testing.

1. Open saved and unsaved Markdown in Side-by-Side and Full Screen; repeat open
   and toggles from source, preview and TOC focus.
2. Edit, save, Save As, rename and delete on disk. Confirm the latest edit wins,
   the title/base path update, and the source is never closed or recreated.
3. Check default light, default dark and one third-party scheme; change scheme
   while open. With MarkdownEditing installed, set a Markdown-only scheme with
   `markdownediting: select color scheme` that contrasts with the global
   `ui: select color scheme` -- preview, TOC and outline must all follow the
   Markdown-only one, including the strip of view below the content, and must
   move when either scheme is changed under an open preview. Exercise keyboard
   and mouse zoom, then reset.
4. Check short, Unicode, malformed/raw HTML and 100 KiB documents. For TOC,
   test below-threshold, nested and duplicate headings and top/middle/bottom
   navigation.
5. Check tables: narrow, wider than the preview, right/centre aligned, CJK and
   mixed CJK/Latin, links and bold inside cells, and a raw HTML table. Confirm
   every row stays on the column grid and no row is wrapped by the host. Resize
   and maximise the window, and zoom in and out: the table refits within about
   a second and still fills the group.
6. Check relative, absolute, missing, oversized and extensionless local images;
   HTTPS, redirect, timeout, invalid and oversized remote images.
7. Check Mermaid disabled, enabled disclosure, offline, timeout, invalid source
   and custom HTTPS server. Confirm diagnostics contain no source or locator.
   Render a `sequenceDiagram` under a dark and a light colour scheme: message
   and note labels must stay legible, and the image background must match the
   preview's, in both.
8. Close TOC, preview, source, group and window; reload the plugin. Change the
   layout after preview creation and confirm it is not overwritten on close.
9. Outline: open with `Ctrl+Shift+B` on a file with no preview, and again with
   a preview open — it must take a group of its own, never a tab in the
   preview's. Check ATX, setext, fenced-code and front-matter documents and one
   with no headings; move the caret across headings; type a new heading and
   watch it appear; click entries top, middle and bottom; toggle focus and
   close; zoom; close the outline, the source, the group and the window; open
   outlines for two files at once and switch between them.
10. Widths: with `auto_width` on, open a table of contents and an outline over
   documents with short headings and with one very long heading — no entry may
   wrap, and neither group may be wider than it was with the setting off. Drag
   the divider and confirm nothing moves it back until the group is closed and
   reopened; then zoom, resize the window and type a longer heading and confirm
   the group follows. Switch `auto_width` off and confirm both widen back.
11. Install beside MarkdownLivePreview. Check directory, module, command,
   settings and resource isolation; document the expected shortcut collision.
12. Open in Browser: on a saved file with a relative image, a table, a nested
   list, a fenced block inside a list item and two headings with the same
   text linked as `#same` and `#same-2`, run the command and confirm the page
   opens, the image resolves, both heading links stay on the page and the list
   shapes match the preview. Put the file in a directory whose name has a
   space and a `#`. Repeat on an unsaved buffer. Confirm the command is absent
   from the palette on a non-Markdown view. On Linux, `ls -l` the page under
   `$TMPDIR/MarkdownGlance` and confirm mode 600.
13. Fresh install through Package Control (`Add Repository` with this
   repository while the channel entry is pending): confirm the `Markdown` and
   `pymdown-extensions` libraries are installed with the package and that a
   preview renders without any other step; confirm the install note is the
   only message shown. In the console, `import markdown, pymdownx` and print
   both `__version__` and `__file__`: 3.2.2 and 8.1.1, from the Python 3.8
   library directory.
14. Manual install without the libraries: clone into Packages and start
   Sublime Text. A dialog must name the two libraries and the fix; the console
   must show no traceback; the commands stay in the palette and repeat the
   dialog. Run Satisfy Libraries, restart, confirm the preview renders.
15. Pygments present: install MarkdownPreview beside this package (it brings
   the Pygments library), restart, and confirm a Mermaid fence with
   `enable_mermaid` on is still a diagram and a fenced block still has its
   language class.

## Automated prerequisites

Run `python -m unittest discover -s MarkdownGlance/tests -t . -p 'test_*.py'` from the parent of the `MarkdownGlance` checkout, Python
compilation, the contract runner and the 100-sample benchmark. The last two
are developer commands, kept out of the command palette; run them from the
Sublime console with `window.run_command("mdglance_run_contract_tests")` and
`window.run_command("mdglance_run_benchmark")`.
Attach JSON evidence from `docs/verification/` to the release record.
