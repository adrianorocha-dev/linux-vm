# Release notes

Add one UTF-8 Markdown file named `VERSION.md`, such as `0.2.0.md`.
Use the same version as `CFBundleShortVersionString` in `macos/Resources/Info.plist`.
Commit the file before running `scripts/release.py VERSION`.
A missing or empty file blocks the release.

Write short notes for the person updating the app.
Describe visible changes, fixes, and anything they must do before updating.
Do not put private information in the notes.
They appear on the public GitHub release and in Sparkle's update window.

The appcast renderer supports headings (`#` through `######`), paragraphs, and flat bullet lists using `- ` or `* `.
Separate paragraphs with a blank line.
It supports `**bold**`, `*emphasis*`, inline backtick code, and `[label](https://example.com)` links.
Links must use HTTP or HTTPS.
Raw HTML is escaped.
Tables, images, fenced code, nested lists, and other Markdown extensions are not supported in the appcast.
GitHub receives the original Markdown file.
