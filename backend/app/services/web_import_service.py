import ipaddress
import os
import socket
import importlib
from urllib.parse import urlparse

import requests


def _is_private_or_local_ip(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return True

    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_public_url(url: str) -> str:
    parsed = urlparse(url.strip())

    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http/https URLs are allowed")
    if not parsed.hostname:
        raise ValueError("Invalid URL")

    host = parsed.hostname.lower()
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        raise ValueError("Local addresses are not allowed")

    try:
        addr_info = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        raise ValueError("Could not resolve URL host")

    for entry in addr_info:
        resolved_ip = entry[4][0]
        if _is_private_or_local_ip(resolved_ip):
            raise ValueError("Private or local network targets are not allowed")

    return url


def fetch_url_html(url: str, timeout_seconds: int = 12, max_size_bytes: int = 2_500_000) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/145.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": url,
    }

    try:
        response = requests.get(url, headers=headers, timeout=timeout_seconds, allow_redirects=True)
        response.raise_for_status()
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code in {401, 403, 406, 429}:
            raise ValueError(
                "This website blocks automated content fetching. Try a different URL."
            )
        raise ValueError(f"Failed to fetch URL content (HTTP {status_code})")
    except requests.RequestException as exc:
        raise ValueError(f"Failed to fetch URL content: {str(exc)}")

    content_type = (response.headers.get("content-type") or "").lower()
    if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
        raise ValueError("URL did not return HTML content")

    body = response.text
    if len(body.encode("utf-8", errors="ignore")) > max_size_bytes:
        raise ValueError("The page is too large to import")

    return body


def extract_article_text(html: str, source_url: str) -> tuple[str, str]:
    try:
        trafilatura = importlib.import_module("trafilatura")
    except ModuleNotFoundError:
        raise ValueError("trafilatura is not installed on the backend")
    extracted_text = trafilatura.extract(
        html,
        include_links=False,
        include_tables=True,
        include_images=False,
        favor_precision=True,
    )

    source_title = ""
    downloaded = trafilatura.extract_metadata(html)
    if downloaded and downloaded.title:
        source_title = downloaded.title.strip()

    if extracted_text and extracted_text.strip():
        text = extracted_text.strip()
    else:
        downloaded_html = trafilatura.fetch_url(source_url)
        if downloaded_html:
            alt_text = trafilatura.extract(
                downloaded_html,
                include_links=False,
                include_tables=True,
                include_images=False,
                favor_precision=True,
            )
            if alt_text and alt_text.strip():
                text = alt_text.strip()
            else:
                text = ""
        else:
            text = ""

    if not text:
        try:
            bs4_module = importlib.import_module("bs4")
        except ModuleNotFoundError:
            raise ValueError("beautifulsoup4 is not installed on the backend")
        BeautifulSoup = bs4_module.BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            source_title = source_title or soup.title.string.strip()

        for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
            tag.decompose()

        main = soup.find("article") or soup.find("main") or soup.body
        if not main:
            raise ValueError("Could not extract readable content from this URL")

        text = "\n".join(line.strip() for line in main.get_text("\n").splitlines() if line.strip())

    if not source_title:
        parsed = urlparse(source_url)
        source_title = parsed.netloc

    if len(text) < 300:
        raise ValueError("The fetched page does not have enough article content")

    # Keep prompt payload bounded for predictable generation cost and latency.
    if len(text) > 25_000:
        text = text[:25_000]

    return source_title, text


def generate_blog_draft_from_source(
    source_url: str,
    source_title: str,
    source_text: str,
    detail_level: str = "normal",
    output_mode: str = "paraphrase",
) -> tuple[str, str]:
    from openai import OpenAI

    normalized_mode = (output_mode or "paraphrase").strip().lower()
    if normalized_mode not in {"summary", "paraphrase", "exact"}:
        raise ValueError("Invalid output_mode. Allowed values: summary, paraphrase, exact")

    if normalized_mode == "exact":
        return source_title, source_text

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured")

    detail_styles = {
        "brief": "Write a concise draft of around 350-500 words.",
        "normal": "Write a well-structured draft of around 700-900 words.",
        "detailed": "Write a comprehensive draft of around 1100-1400 words.",
    }
    detail_instruction = detail_styles.get(detail_level, detail_styles["normal"])

    mode_instruction = {
        "summary": (
            "Create a concise summary draft from the source. "
            "Focus on key points and remove repetitive details."
        ),
        "paraphrase": (
            "Create a full rewritten blog draft from the source. "
            "Preserve meaning while rephrasing in original wording."
        ),
    }

    client = OpenAI(api_key=api_key)
    prompt = f"""
You are drafting a new original blog post based on source material.

Rules:
1. Preserve the key facts and intent from the source.
2. Rewrite in fresh wording; do not copy passages verbatim.
3. Use a professional, readable tone with clear headings.
4. Include a short attribution line at the end: "Source reference: {source_url}".
5. Return JSON with keys: title, content.

Output mode: {normalized_mode}
Mode-specific instruction: {mode_instruction[normalized_mode]}

{detail_instruction}

Source title: {source_title}
Source URL: {source_url}

Source content:
{source_text}
"""

    response = client.chat.completions.create(
        model=os.getenv("OPENAI_DRAFT_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": "You create high-quality draft blog posts."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.35,
        max_tokens=2200,
    )

    import json

    raw = response.choices[0].message.content or "{}"
    payload = json.loads(raw)

    title = (payload.get("title") or "Imported draft").strip()
    content = (payload.get("content") or "").strip()

    if not content:
        raise ValueError("Failed to generate draft content from source")

    return title, content
