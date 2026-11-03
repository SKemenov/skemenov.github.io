#!/usr/bin/env python3
"""Build the localized Minimal.md pages from the English ones.

The four English pages under docs/md/ are the source. Every piece of translatable text
in them is a key in l10n/strings.json; this script swaps each one for its translation,
fixes the relative paths for the deeper folder, and writes docs/md/<lang>/....
It also rewrites the two generated blocks (hreflang links, language switcher) on every
page, the English ones included.

    python3 -I l10n/build.py                # build; exit 1 on any problem
    python3 -I l10n/build.py --add-missing  # also add missing keys to strings.json, empty

Exit 1 on: a missing or orphaned string, a relative link or image that doesn't resolve,
an email address in the output, or unbalanced tags.
"""

import html.parser
import json
import posixpath
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
STRINGS = ROOT / "l10n" / "strings.json"
SITE = "https://skemenov.com"

# Endonym, and the word for "Language" (the switcher's accessible name), per language.
# The order is the switcher's order. A language builds only once it's listed in ENABLED.
LANGUAGES = {
    "en": ("English", "Language"),
    "de": ("Deutsch", "Sprache"),
    "es": ("Español", "Idioma"),
    "fr": ("Français", "Langue"),
    "it": ("Italiano", "Lingua"),
    "ru": ("Русский", "Язык"),
}
ENABLED = ["en"]

PAGES = ["/md/", "/md/markdown/", "/md/support/", "/md/privacy/"]

# Screenshots and the store badge have a copy per language.
SHOT = re.compile(r"^/assets/img/md/(\d-[a-z-]+\.png)$")
BADGE = "/assets/img/md/mac-app-store-badge.svg"
OG_IMAGE = f"{SITE}/assets/img/og/md.jpg"

INLINE = {"a", "strong", "em", "b", "i", "kbd", "code", "br", "span", "small", "sup", "sub"}
CANDIDATES = {"title", "a", "h1", "h2", "h3", "h4", "p", "li", "span", "figcaption", "dt", "dd", "td", "th"}
NO_LETTERS = {"kbd", "code"}  # text inside these doesn't make an element translatable
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
META_KEYS = {"description", "og:title", "og:description", "og:image:alt"}
BLOCK = re.compile(r"(<!-- (hreflang|lang-switcher) -->)(.*?)(\n[ \t]*<!-- /\2 -->)", re.S)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", re.I)
URL_ATTR = re.compile(r'\b(href|src)="([^"]*)"')
JSON_LD = re.compile(r'(<script type="application/ld\+json">)(.*?)(</script>)', re.S)

problems = []


def page_file(url):
    return DOCS / url.lstrip("/") / "index.html"


def localized(url, lang):
    return url if lang == "en" else url.replace("/md/", f"/md/{lang}/", 1)


def collapse(s):
    return " ".join(s.split())


def relative(target, from_dir):
    """A relative URL from directory from_dir to target, both absolute paths."""
    is_dir = target.endswith("/")
    rel = posixpath.relpath(target.rstrip("/") or "/", from_dir.rstrip("/") or "/")
    if is_dir:
        rel = "./" if rel == "." else rel + "/"
    return rel


class Scanner(html.parser.HTMLParser):
    """Finds the translatable pieces of a page as (start, end, kind, key) edits on the source."""

    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.source = source
        self.line_starts = [0]
        for line in source.splitlines(keepends=True):
            self.line_starts.append(self.line_starts[-1] + len(line))
        self.stack = []      # open elements: dict(tag, inner, pure, letters)
        self.segments = []   # (start, end, key)
        self.attrs = []      # (start, end, raw tag, [(attr, key)])
        self.skip = 0        # depth inside footer/script/style

    def pos(self):
        line, col = self.getpos()
        return self.line_starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        self.tag(tag, attrs, void=tag in VOID)

    def handle_startendtag(self, tag, attrs):
        self.tag(tag, attrs, void=True)

    def tag(self, tag, attrs, void):
        start = self.pos()
        raw = self.get_starttag_text()
        if tag not in INLINE:
            for frame in self.stack:
                frame["pure"] = False
        if self.skip or tag in ("footer", "script", "style"):
            if not void:
                self.skip += 1
                self.stack.append({"tag": tag, "skip": True})
            return
        a = dict(attrs)
        wanted = [k for k in ("alt", "aria-label") if a.get(k)]
        if tag == "meta" and (a.get("name") in META_KEYS or a.get("property") in META_KEYS):
            wanted.append("content")
        if wanted:
            self.attrs.append((start, start + len(raw), raw, wanted))
        if not void:
            self.stack.append({"tag": tag, "inner": start + len(raw), "pure": True, "letters": False})

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        end = self.pos()
        while self.stack:
            frame = self.stack.pop()
            if frame.get("skip"):
                self.skip -= 1
            if frame["tag"] == tag:
                break
            problems.append(f"unbalanced: <{frame['tag']}> closed by </{tag}> at line {self.getpos()[0]}")
        else:
            problems.append(f"unbalanced: stray </{tag}> at line {self.getpos()[0]}")
            return
        if frame.get("skip"):
            return
        if tag in CANDIDATES and frame["pure"] and frame["letters"]:
            self.segments.append((frame["inner"], end, collapse(self.source[frame["inner"]:end])))

    def handle_data(self, data):
        if self.skip or not any(c.isalpha() for c in data):
            return
        if any(f["tag"] in NO_LETTERS for f in self.stack):
            return
        for frame in self.stack:
            frame["letters"] = True

    def edits(self):
        """Outermost segments only, and no attribute edits inside a segment."""
        segs = sorted(self.segments)
        kept = []
        for s in segs:
            if kept and s[0] < kept[-1][1]:
                continue
            kept.append(s)
        inside = lambda pos: any(a <= pos < b for a, b, _ in kept)
        attrs = [x for x in self.attrs if not inside(x[0])]
        return kept, attrs


def scan(source):
    s = Scanner(source)
    s.feed(source)
    s.close()
    for frame in s.stack:
        if not frame.get("skip") and frame["tag"] not in ("html", "body", "head"):
            problems.append(f"unbalanced: <{frame['tag']}> never closed")
    return s.edits()


def keys_of(source):
    segs, attrs = scan(blank_blocks(source))
    keys = [k for _, _, k in segs]
    for _, _, raw, wanted in attrs:
        for name in wanted:
            m = re.search(rf'\b{re.escape(name)}="([^"]*)"', raw)
            keys.append(collapse(m.group(1)))
    m = JSON_LD.search(source)
    if m:
        data = json.loads(m.group(2))
        keys += [data[k] for k in ("description", "operatingSystem") if k in data]
    return keys


def blank_blocks(source):
    return BLOCK.sub(lambda m: m.group(1) + m.group(4), source)


def fill_blocks(source, url, lang):
    langs = ENABLED if len(ENABLED) > 1 else []
    here = localized(url, lang)
    indent_of = lambda m: re.search(r"\n([ \t]*)<!-- /", m.group(4)).group(1)

    def block(m):
        ind = indent_of(m)
        lines = []
        if m.group(2) == "hreflang":
            for code in langs:
                lines.append(f'<link rel="alternate" hreflang="{code}" href="{SITE}{localized(url, code)}">')
            if langs:
                lines.append(f'<link rel="alternate" hreflang="x-default" href="{SITE}{url}">')
        elif langs:
            name, word = LANGUAGES[lang]
            lines.append(f'<button type="button" class="lang-button" popovertarget="languages" aria-label="{word}: {name}">'
                         '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
                         'stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/>'
                         '<path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z"/></svg>'
                         f'<span>{name}</span></button>')
            lines.append(f'<div id="languages" class="languages-list" popover>')
            lines.append("  <ul>")
            for code in langs:
                target = relative(localized(url, code), here)
                current = ' aria-current="page"' if code == lang else ""
                lines.append(f'    <li><a href="{target}" lang="{code}" hreflang="{code}"{current}>{LANGUAGES[code][0]}</a></li>')
            lines.append("  </ul>")
            lines.append("</div>")
        body = "".join(f"\n{ind}{line}" for line in lines)
        return m.group(1) + body + m.group(4)

    return BLOCK.sub(block, source)


def rewrite_urls(text, url, lang):
    """Relative links keep pointing at the same thing from one folder deeper."""
    here = localized(url, lang)

    def fix(m):
        attr, value = m.groups()
        if re.match(r"^([a-z]+:|#|/)", value):
            return m.group(0)
        path, sep, rest = re.match(r"^([^?#]*)([?#]?)(.*)$", value).groups()
        target = posixpath.normpath(posixpath.join(url, path))
        if path.endswith("/") or path in ("", "."):
            target = target.rstrip("/") + "/"
        if target in PAGES:
            new = value  # same structure inside /md/<lang>/
        else:
            shot = SHOT.match(target)
            if shot:
                target = f"/assets/img/md/{lang}/{shot.group(1)}"
            elif target == BADGE:
                badge = f"/assets/img/md/badges/{lang}.svg"
                if (DOCS / badge.lstrip("/")).exists():
                    target = badge
                else:
                    print(f"warning: no docs{badge}, {lang} uses the English badge")
            new = relative(target, here) + sep + rest
        return f'{attr}="{new}"'

    text = URL_ATTR.sub(fix, text)

    def badge_width(m):
        # Localized badges differ in width; keep the height, take the width from the viewBox.
        svg = (DOCS / "assets/img/md/badges" / f"{m.group(2)}.svg").read_text()
        vb = re.search(r'viewBox="[\d.]+ [\d.]+ ([\d.]+) ([\d.]+)"', svg)
        width = round(float(vb.group(1)) * int(m.group(4)) / float(vb.group(2))) if vb else int(m.group(3))
        return f'{m.group(1)}width="{width}" height="{m.group(4)}"'

    return re.sub(r'(<img src="[^"]*badges/([a-z]+)\.svg" )width="(\d+)" height="(\d+)"', badge_width, text)


def translate(source, url, lang, strings, missing):
    def t(key):
        value = strings.get(key, {}).get(lang)
        if not value:
            missing.setdefault(key, set()).add(url)
            return None
        return value

    body = blank_blocks(source)
    segs, attrs = scan(body)
    edits = []
    for start, end, key in segs:
        value = t(key)
        if value is not None:
            inner = body[start:end]
            lead = inner[: len(inner) - len(inner.lstrip())]
            trail = inner[len(inner.rstrip()):]
            edits.append((start, end, lead + value + trail))
    for start, end, raw, wanted in attrs:
        new = raw
        for name in wanted:
            pattern = re.compile(rf'(\b{re.escape(name)}=")([^"]*)(")')
            value = t(collapse(pattern.search(new).group(2)))
            if value is not None:
                new = pattern.sub(lambda m: m.group(1) + value + m.group(3), new, count=1)
        edits.append((start, end, new))
    for start, end, new in sorted(edits, reverse=True):
        body = body[:start] + new + body[end:]

    def ld(m):
        data = json.loads(m.group(2))
        for k in ("description", "operatingSystem"):
            if k in data:
                data[k] = t(data[k]) or data[k]
        data["url"] = SITE + localized(url, lang)
        data["inLanguage"] = lang
        return m.group(1) + json.dumps(data, ensure_ascii=False) + m.group(3)

    body = JSON_LD.sub(ld, body)
    body = rewrite_urls(body, url, lang)
    body = body.replace('<html lang="en">', f'<html lang="{lang}">', 1)
    page = SITE + url
    body = body.replace(f'<link rel="canonical" href="{page}">', f'<link rel="canonical" href="{SITE}{localized(url, lang)}">')
    body = body.replace(f'<meta property="og:url" content="{page}">', f'<meta property="og:url" content="{SITE}{localized(url, lang)}">')
    og = DOCS / f"assets/img/og/md-{lang}.jpg"
    if og.exists():
        body = body.replace(f'content="{OG_IMAGE}"', f'content="{SITE}/assets/img/og/md-{lang}.jpg"')
    else:
        print(f"warning: no {og.relative_to(ROOT)}, {lang} uses the English link preview")
    note = f"<!-- Generated from {url} by l10n/build.py: edit the English page and l10n/strings.json, not this file. -->"
    body = body.replace("<!doctype html>\n", f"<!doctype html>\n{note}\n", 1)
    return fill_blocks(body, url, lang)


def check(path, text, url, pending):
    """Every relative link and image resolves to a file (or one about to be written);
    no email address as text."""
    for _, value in URL_ATTR.findall(text):
        if re.match(r"^([a-z]+:|#)", value):
            continue
        p = re.match(r"^([^?#]*)", value).group(1)
        target = posixpath.normpath(posixpath.join(url, p)) if not p.startswith("/") else p
        f = DOCS / target.lstrip("/")
        if p.endswith("/") or p in ("", "."):
            ok = (f / "index.html").exists() or (f / "index.md").exists() or (f / "index.html") in pending
        else:
            ok = f.exists()
        if not ok:
            problems.append(f"{path.relative_to(ROOT)}: broken link {value}")
    if EMAIL.search(text):
        problems.append(f"{path.relative_to(ROOT)}: email address as text")


def write(path, text):
    if not path.exists() or path.read_text() != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        print(f"wrote {path.relative_to(ROOT)}")


def main():
    strings = json.loads(STRINGS.read_text()) if STRINGS.exists() else {}
    missing, used = {}, set()
    outputs = []
    for url in PAGES:
        src_path = page_file(url)
        source = fill_blocks(src_path.read_text(), url, "en")
        used.update(keys_of(source))
        outputs.append((src_path, source, url))
        for lang in ENABLED:
            if lang != "en":
                outputs.append((page_file(localized(url, lang)), translate(source, url, lang, strings, missing), localized(url, lang)))

    pending = {path for path, _, _ in outputs}
    for path, text, url in outputs:
        check(path, text, url, pending)
    if problems:
        print("\n".join(sorted(set(problems))))
        return 1
    for path, text, _ in outputs:
        write(path, text)

    orphans = sorted(set(strings) - used)
    for key in orphans:
        print(f"orphaned: {key[:90]}")
    for key, urls in sorted(missing.items()):
        langs = [l for l in ENABLED if l != "en" and not strings.get(key, {}).get(l)]
        print(f"missing [{', '.join(langs)}] {', '.join(sorted(urls))}: {key[:90]}")

    if "--add-missing" in sys.argv:
        for key in sorted(used):
            entry = strings.setdefault(key, {})
            for lang in ENABLED:
                if lang != "en":
                    entry.setdefault(lang, "")
        STRINGS.write_text(json.dumps(strings, ensure_ascii=False, indent=2) + "\n")
        print(f"strings.json: {len(strings)} keys")

    print(f"{len(used)} strings, {len(missing)} missing, {len(orphans)} orphaned, languages: {', '.join(ENABLED)}")
    return 1 if missing or orphans else 0


if __name__ == "__main__":
    sys.exit(main())
