"""Remove common hidden and instruction-shaped content from posting text."""

import re
import unicodedata

from bs4 import BeautifulSoup, Comment

INSTRUCTION = re.compile(
    r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions|system\s+prompt|"
    r"output\s+the\s+following\s+json|^\s*you\s+are\s+now\b",
    re.I,
)
HIDDEN = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:px|em|rem|%|\s|;|$)", re.I)


def sanitize_untrusted_text(raw_text: str, max_chars: int = 2500) -> tuple[str, list[str]]:
    flags = set()
    visible = "".join(char for char in (raw_text or "")
                      if char in "\n\t" or unicodedata.category(char) not in {"Cc", "Cf"})
    if visible != raw_text:
        flags.add("control characters")
    document = BeautifulSoup(visible, "html.parser")
    for comment in document.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()
        flags.add("hidden content")
    for node in document.find_all(True):
        if node.attrs is not None and (node.name in {"script", "style", "template"} or
                                       node.has_attr("hidden") or HIDDEN.search(node.get("style", ""))):
            node.decompose()
            flags.add("hidden content")
    lines = []
    for line in document.get_text(" ").splitlines():
        if INSTRUCTION.search(line):
            flags.add("instruction-like text")
        else:
            lines.append(line.strip())
    cleaned = "\n".join(line for line in lines if line)
    if len(cleaned) > max_chars:
        flags.add("length limit")
    return cleaned[:max_chars], sorted(flags)
