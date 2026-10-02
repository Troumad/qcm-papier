"""Conversion Markdown → balisage Pango pour l'interface GTK.

Même sous-ensemble que ``web/static/markdown.js`` : titres, paragraphes,
listes, blocs de code, citations, lignes horizontales, gras, italique, code en
ligne et liens. Tout le texte est échappé : le résultat est toujours un
balisage Pango valide, utilisable avec ``Gtk.Label.set_markup`` ou
``Gtk.TextBuffer.insert_markup``.
"""

from __future__ import annotations

import re
from html import escape

TITLE_SIZES = {1: "x-large", 2: "large", 3: "medium"}
LINK_COLOR = "#2459c7"
MUTED_COLOR = "#5f6b7a"


def _inline(text: str) -> str:
    codes: list[str] = []

    def keep_code(match: re.Match[str]) -> str:
        codes.append(f"<tt>{match.group(1)}</tt>")
        return f"\x00{len(codes) - 1}\x00"

    html = re.sub(r"`([^`]+)`", keep_code, escape(text, quote=False))
    html = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", html)
    html = re.sub(r"(^|[\s(])\*([^*\s][^*]*)\*", r"\1<i>\2</i>", html)
    html = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        rf'<span foreground="{LINK_COLOR}" underline="single">\1</span> (\2)',
        html,
    )
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], html)


def render(markdown: str) -> str:
    """Balisage Pango du texte Markdown (blocs séparés par une ligne vide)."""
    out: list[str] = []
    paragraph: list[str] = []
    code: list[str] | None = None

    def flush() -> None:
        if paragraph:
            out.append(_inline(" ".join(paragraph)))
            out.append("")
            paragraph.clear()

    for raw in markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.rstrip()
        if code is not None:
            if line.strip().startswith("```"):
                out.append(f"<tt>{escape(chr(10).join(code), quote=False)}</tt>")
                out.append("")
                code = None
            else:
                code.append(raw)
            continue
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            code = []
            continue
        if not stripped:
            flush()
            continue
        title = re.match(r"(#{1,6})\s+(.*)", stripped)
        if title:
            flush()
            size = TITLE_SIZES.get(len(title.group(1)), "medium")
            out.append(f'<span size="{size}"><b>{_inline(title.group(2))}</b></span>')
            out.append("")
            continue
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            flush()
            out.append("─" * 30)
            out.append("")
            continue
        if stripped.startswith(">"):
            flush()
            out.append(f'<span foreground="{MUTED_COLOR}"><i>{_inline(stripped.lstrip("> "))}</i></span>')
            continue
        item = re.match(r"(\s*)([-*+]|\d+[.)])\s+(.*)", line)
        if item:
            flush()
            indent = "    " * (len(item.group(1).expandtabs(4)) // 2)
            marker = "•" if item.group(2) in "-*+" else item.group(2)
            out.append(f"{indent}{marker} {_inline(item.group(3))}")
            continue
        if out and out[-1] and not paragraph and re.match(r"\s{2,}", raw):
            # Suite d'un élément de liste sur la ligne suivante.
            out[-1] += " " + _inline(stripped)
            continue
        paragraph.append(stripped)
    if code is not None:
        out.append(f"<tt>{escape(chr(10).join(code), quote=False)}</tt>")
    flush()
    return "\n".join(out).strip("\n")
