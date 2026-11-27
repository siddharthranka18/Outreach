"""64-bit fingerprints for job description similarity."""

from collections import Counter
import hashlib
import html
import re

from bs4 import BeautifulSoup


FOOTER = re.compile(
    r"\b(?:equal opportunity employer|we are an equal opportunity|"
    r"privacy notice|recruitment privacy policy|about our benefits)\b.*",
    re.IGNORECASE | re.DOTALL,
)


def description_simhash(description: str | None) -> str | None:
    if not description:
        return None
    plain = BeautifulSoup(html.unescape(description), "html.parser").get_text(" ")
    tokens = re.findall(r"[a-z0-9]+", FOOTER.sub("", plain.casefold()))
    if len(set(tokens)) < 20:
        return None
    weights = [0] * 64
    for token, count in Counter(tokens).items():
        value = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big")
        for index in range(64):
            weights[index] += min(count, 3) if value & (1 << index) else -min(count, 3)
    return f"{sum(1 << index for index, weight in enumerate(weights) if weight > 0):016x}"


def hamming_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()
