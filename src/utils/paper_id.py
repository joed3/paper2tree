import hashlib
import re


def make_paper_id(title: str, url: str) -> str:
    """Generate a stable, filesystem-safe paper ID from title + URL.

    Format: <slug>-<8-char-url-hash>
    Example: attention-is-all-you-need-a1b2c3d4
    """
    # Slugify: lowercase, keep alphanumeric + spaces, collapse spaces to hyphens
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = slug[:50].rstrip("-")

    # 8-char hash of the URL for uniqueness
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:8]

    return f"{slug}-{url_hash}" if slug else url_hash
