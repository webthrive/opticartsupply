"""
Optic Art Supply — Ghost Image Downloader
==========================================
Scrapes every post on opticartsupply.com and downloads all images to ./images/
preserving a clean folder structure.

Usage:
    pip install requests beautifulsoup4 lxml
    python download_images.py

Output: ./images/<slug>/<filename>  (one folder per post, flat for shared images)
"""

import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── CONFIG ──────────────────────────────────────────────────────────
BASE_URL      = "https://www.opticartsupply.com"
SITEMAP_POSTS = "https://www.opticartsupply.com/sitemap-posts.xml"
SITEMAP_PAGES = "https://www.opticartsupply.com/sitemap-pages.xml"
OUTPUT_DIR    = Path("./images")
DELAY_SEC     = 0.5      # polite crawl delay between requests
TIMEOUT       = 20       # seconds per request
HEADERS       = {"User-Agent": "OpticArtSupply-ImageMigration/1.0"}

# ── HELPERS ──────────────────────────────────────────────────────────
def fetch(url: str) -> requests.Response | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"  ⚠  SKIP {url}  ({e})")
        return None


def slug_from_url(url: str) -> str:
    """Turn a post URL into a filesystem-safe slug."""
    path = urllib.parse.urlparse(url).path.strip("/")
    # use the last path segment as slug (handles /category/slug/ patterns)
    return re.sub(r"[^a-z0-9\-_]", "", path.replace("/", "--"))


def urls_from_sitemap(sitemap_url: str) -> list[str]:
    r = fetch(sitemap_url)
    if not r:
        return []
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.fromstring(r.text)
    return [loc.text for loc in root.findall(".//sm:loc", ns) if loc.text]


def image_urls_from_page(html: str, page_url: str) -> list[str]:
    """Extract all image src URLs from a parsed HTML page."""
    soup = BeautifulSoup(html, "lxml")
    urls = set()

    for tag in soup.find_all("img"):
        # prefer data-srcset / srcset for full-size images
        for attr in ("data-src", "src"):
            src = tag.get(attr, "")
            if src and src.startswith("http"):
                # strip Ghost's /size/wXXX/ resizing path to get original
                src = re.sub(r"/size/w\d+/", "/", src)
                urls.add(src)
        # also parse srcset
        srcset = tag.get("srcset", "") or tag.get("data-srcset", "")
        for part in srcset.split(","):
            part = part.strip().split(" ")[0]
            if part.startswith("http"):
                part = re.sub(r"/size/w\d+/", "/", part)
                urls.add(part)

    # Also capture Ghost og:image / meta image
    for meta in soup.find_all("meta", property="og:image"):
        content = meta.get("content", "")
        if content.startswith("http"):
            content = re.sub(r"/size/w\d+/", "/", content)
            urls.add(content)

    return list(urls)


def download_image(img_url: str, dest_dir: Path) -> bool:
    """Download a single image into dest_dir. Returns True on success."""
    filename = urllib.parse.unquote(img_url.split("?")[0].split("/")[-1])
    if not filename or "." not in filename:
        filename = "image_" + str(abs(hash(img_url)))[:8] + ".jpg"

    dest = dest_dir / filename
    if dest.exists():
        return True  # already downloaded

    r = fetch(img_url)
    if not r or not r.content:
        return False

    dest.write_bytes(r.content)
    return True


# ── MAIN ─────────────────────────────────────────────────────────────
def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Collect all post + page URLs
    print("📋  Fetching sitemaps…")
    post_urls = urls_from_sitemap(SITEMAP_POSTS)
    page_urls = urls_from_sitemap(SITEMAP_PAGES)
    # deduplicate and keep only same-domain URLs
    all_urls = list({
        u for u in post_urls + page_urls
        if "opticartsupply.com" in u
        and not u.endswith("sitemap")
    })
    print(f"   Found {len(all_urls)} pages to crawl.\n")

    total_images  = 0
    failed_images = 0
    manifest      = []   # list of (page_url, image_url, local_path)

    for i, page_url in enumerate(all_urls, 1):
        print(f"[{i:>3}/{len(all_urls)}]  {page_url}")

        r = fetch(page_url)
        if not r:
            continue

        img_urls = image_urls_from_page(r.text, page_url)
        if not img_urls:
            print("         (no images)")
            time.sleep(DELAY_SEC)
            continue

        slug   = slug_from_url(page_url)
        folder = OUTPUT_DIR / slug
        folder.mkdir(parents=True, exist_ok=True)

        for img_url in img_urls:
            ok = download_image(img_url, folder)
            filename = img_url.split("/")[-1].split("?")[0]
            local    = f"images/{slug}/{filename}"
            status   = "✓" if ok else "✗"
            print(f"         {status}  {filename}")
            if ok:
                total_images += 1
                manifest.append((page_url, img_url, local))
            else:
                failed_images += 1

        time.sleep(DELAY_SEC)

    # 2. Write manifest CSV (useful for updating HTML src paths later)
    manifest_path = Path("image_manifest.csv")
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write("page_url,original_img_url,local_path\n")
        for row in manifest:
            f.write(",".join(f'"{v}"' for v in row) + "\n")

    print(f"\n{'─'*60}")
    print(f"✅  Done. Downloaded {total_images} images ({failed_images} failed).")
    print(f"📄  Manifest written to: {manifest_path}")
    print(f"📁  Images saved to:     {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
