import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
ALLOWED_URLS = {"http://www.w3.org/2000/svg"}


def site_sources():
    return [p for p in SITE.iterdir() if p.suffix in {".js", ".html", ".css"} and not p.name.endswith(".test.js")]


def test_site_makes_no_third_party_requests():
    for p in site_sources():
        for url in re.findall(r"https?://[^\s\"')]+", p.read_text(encoding="utf-8")):
            assert url in ALLOWED_URLS, f"{p.name} references {url}"


def test_site_sets_no_cookies():
    for p in site_sources():
        assert "document.cookie" not in p.read_text(encoding="utf-8"), p.name


def test_site_has_no_user_input_images_or_media():
    src = (SITE / "app.js").read_text(encoding="utf-8")
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert not re.search(r'el\("(img|audio|video|form|input|textarea|select)"', src)
    assert not re.search(r"<(img|audio|video|form|input|textarea|select)\b", html)


def test_no_secrets_or_topics_in_the_repo():
    for p in list(ROOT.glob("bench/*.py")) + list((ROOT / ".github").rglob("*.yml")) + [ROOT / "assets.yaml"]:
        for line in p.read_text(encoding="utf-8").splitlines():
            assert not re.search(r"ntfy\.sh/[A-Za-z0-9_-]{6,}", line.replace("ntfy.sh/{topic}", "")), (p.name, line)
