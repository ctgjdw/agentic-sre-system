import hashlib
import math
import re

_TOKEN = re.compile(r"[a-z0-9]+")


def hash_embedding(text: str, dim: int = 768) -> list[float]:
    """Deterministic bag-of-tokens pseudo-embedding for the fake profile: same text,
    same vector, and texts sharing tokens land measurably closer. Retrieval tests
    rely on that: token overlap, not luck, decides nearest-neighbor order."""
    acc = [0.0] * dim
    for token in _TOKEN.findall(text.lower()) or [text]:
        seed = hashlib.sha256(token.encode()).digest()
        for i in range(dim):
            byte = seed[(i * 7 + 3) % len(seed)] ^ (i & 0xFF)
            acc[i] += (byte / 255.0) * 2 - 1
    norm = math.sqrt(sum(v * v for v in acc)) or 1.0
    return [v / norm for v in acc]
