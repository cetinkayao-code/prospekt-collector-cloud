# -*- coding: utf-8 -*-
"""
FINAL PROSPEKT COLLECTOR v1.7
9 MARKA - SADECE DISCOUNTO

LIDL       -> Discounto
NORMA      -> Discounto
ALDI-NORD  -> Discounto
ALDI-SUD   -> Discounto
NETTO      -> Discounto
PENNY      -> Discounto
TOOM       -> Discounto
BAUHAUS    -> Discounto
OBI        -> Discounto

Mantık:
- Discounto marka sayfasını açar.
- "Current ... brochure (week XX)" başlığını bulur.
- SADECE bu başlığın bağlı olduğu güncel broşürü işler.
- Geçmiş/gelecek broşürleri almaz.
- KW başlıktan, tarih aralığı broşür kartından/URL'den alınır.
- Her marka kendi klasörüne kaydedilir.
- Aynı PDF tekrar indirilmez.
"""

from pathlib import Path
from datetime import datetime
import os
import re
import json
import requests
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

# Repo-relative çıktı klasörü: hem yerelde hem GitHub Actions runner'ında
# aynı şekilde çalışsın diye script'in bulunduğu klasöre göre konumlandırılır.
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "FINAL_PROSPEKTE"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# CI'da (GitHub Actions) ekran olmadığı için tarayıcı headless çalışmalı.
# Yerelde denemek istersen: $env:HEADLESS="0" diyip görünür modda çalıştırabilirsin.
HEADLESS = os.environ.get("HEADLESS", "1") != "0"

MANIFEST_FILE = OUTPUT_DIR / "collector_manifest_v16.json"

BRANDS = [
    "LIDL",
    "NETTO",
    "PENNY",
    "TOOM",
    "BAUHAUS",
    "OBI",
    "NORMA",
    "ALDI-NORD",
    "ALDI-SUD",
]

DISCOUNTO = {
    "LIDL": "https://www.discounto.de/Prospekte/Anbieter%3ALidl/",
    "NORMA": "https://www.discounto.de/Prospekte/Anbieter%3ANorma/",
    "ALDI-NORD": "https://www.discounto.de/Prospekte/Anbieter%3Aaldi/",
    "ALDI-SUD": "https://www.discounto.de/Prospekte/Anbieter%3Aaldi_sued/",
    "NETTO": "https://www.discounto.de/Prospekte/Anbieter%3ANetto-Marken-Discount/",
    "PENNY": "https://www.discounto.de/Prospekte/Anbieter%3Apenny_markt/",
    "TOOM": "https://www.discounto.de/Prospekte/Anbieter%3AToom/",
    "BAUHAUS": "https://www.discounto.de/Prospekte/Anbieter%3ABauhaus/",
    "OBI": "https://www.discounto.de/Prospekte/Anbieter%3Aobi/",
}

for brand in BRANDS:
    (OUTPUT_DIR / brand).mkdir(parents=True, exist_ok=True)


def safe_name(text):
    return re.sub(r'[<>:"/\\|?*]+', "-", text).strip()


def load_manifest():
    if not MANIFEST_FILE.exists():
        return {}
    try:
        data = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_manifest(data):
    tmp = MANIFEST_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(MANIFEST_FILE)


def normalize_url(url):
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    return url


def parse_dates(text):
    if not text:
        return None, None

    # URL formatı: 2026-08-10_2026-08-15
    ds = re.findall(r"(\d{4}-\d{2}-\d{2})", text)
    if len(ds) >= 2:
        try:
            return (
                datetime.strptime(ds[0], "%Y-%m-%d"),
                datetime.strptime(ds[1], "%Y-%m-%d"),
            )
        except ValueError:
            pass

    # Alman tarih formatı
    ds = re.findall(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if len(ds) >= 2:
        try:
            return (
                datetime(int(ds[0][2]), int(ds[0][1]), int(ds[0][0])),
                datetime(int(ds[1][2]), int(ds[1][1]), int(ds[1][0])),
            )
        except ValueError:
            pass

    return None, None


def extract_kw(text):
    m = re.search(r"\bweek\s*(\d{1,2})\b", text or "", re.I)
    if m:
        return f"KW{int(m.group(1)):02d}"

    m = re.search(r"\bKW\s*(\d{1,2})\b", text or "", re.I)
    if m:
        return f"KW{int(m.group(1)):02d}"

    return None


def is_valid_pdf(path):
    try:
        if not path.exists() or path.stat().st_size < 1000:
            return False
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except Exception:
        return False


def download_pdf(url, dest, referer):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
        "Accept": "application/pdf,*/*",
        "Referer": referer,
    }

    tmp = dest.with_suffix(".part")

    with requests.get(
        url,
        headers=headers,
        timeout=180,
        stream=True,
    ) as r:
        r.raise_for_status()

        first = b""

        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if not chunk:
                    continue
                if not first:
                    first = chunk[:10]
                f.write(chunk)

    if not first.startswith(b"%PDF"):
        try:
            tmp.unlink()
        except Exception:
            pass
        raise RuntimeError(f"PDF değil. İlk bytes: {first!r}")

    tmp.replace(dest)
    return dest.stat().st_size


def accept_cookies(page):
    labels = [
        "Alle akzeptieren",
        "Alles akzeptieren",
        "Akzeptieren",
        "Accept All",
    ]

    for _ in range(4):
        for frame in page.frames:
            for label in labels:
                try:
                    loc = frame.get_by_text(label, exact=True)
                    for i in range(loc.count()):
                        el = loc.nth(i)
                        if el.is_visible(timeout=300):
                            el.click(force=True)
                            page.wait_for_timeout(1200)
                            return
                except Exception:
                    pass
        page.wait_for_timeout(500)


def find_current_brochure(page, brand):
    """
    Discounto marka sayfasındaki:
        Current XXX brochure (week XX)
    başlığını bulur.

    Bazı sayfalarda başlık iç içe <font> etiketleri nedeniyle
    normal h2.inner_text() araması güvenilir olmayabiliyor.
    Bu nedenle:
      1) h2 / heading text,
      2) tüm body text,
      3) ham HTML
    olmak üzere kademeli fallback kullanılır.

    Sadece Current başlığının hemen bağlı olduğu prospekt seçilir.
    """

    current_text = None
    current_h2 = None
    kw = None

    # Discounto sayfaları pratikte Almanca başlık döndürüyor:
    #   Aktueller Lidl Prospekt (KW 33)
    # Bazı durumlarda İngilizce çeviri de görülebilir:
    #   Current toom brochure (week 33)
    # Bu yüzden iki formatı da kabul ediyoruz.
    current_re = re.compile(
        r"(?:Current\s+.*?brochure\s*\(\s*week\s*(\d+)\s*\)"
        r"|Aktuell(?:er|e|es|en)?\s+.*?Prospekt\s*\(\s*KW\s*(\d+)\s*\))",
        re.I | re.S,
    )

    # ------------------------------------------------------------
    # 1) H2 başlıkları
    # ------------------------------------------------------------
    try:
        h2s = page.locator("h2")
        texts = h2s.all_inner_texts()
        for i, text in enumerate(texts):
            text = (text or "").strip()
            m = current_re.search(text)
            if m:
                current_h2 = h2s.nth(i)
                current_text = text
                week_no = m.group(1) or m.group(2)
                kw = f"KW{int(week_no):02d}"
                break
    except Exception:
        pass

    # ------------------------------------------------------------
    # 2) H1-H6 + heading role fallback
    # ------------------------------------------------------------
    if current_h2 is None:
        try:
            headings = page.locator("h1, h2, h3, h4, h5, h6, [role='heading']")
            for i in range(headings.count()):
                try:
                    el = headings.nth(i)
                    text = el.inner_text(timeout=700).strip()
                    m = current_re.search(text)
                    if m:
                        current_h2 = el
                        current_text = text
                        week_no = m.group(1) or m.group(2)
                        kw = f"KW{int(week_no):02d}"
                        break
                except Exception:
                    pass
        except Exception:
            pass

    # ------------------------------------------------------------
    # 3) Body text fallback
    # ------------------------------------------------------------
    if current_text is None:
        try:
            body_text = page.locator("body").inner_text(timeout=3000)
            m = current_re.search(body_text)
            if m:
                current_text = m.group(0).strip()
                week_no = m.group(1) or m.group(2)
                kw = f"KW{int(week_no):02d}"
        except Exception:
            pass

    # ------------------------------------------------------------
    # 4) Raw HTML fallback
    # ------------------------------------------------------------
    html = page.content()

    if current_text is None:
        # HTML içinde font/etiketlerin arasına giren boşlukları normalize et.
        plain = re.sub(r"<[^>]+>", " ", html)
        plain = re.sub(r"\s+", " ", plain)

        m = current_re.search(plain)
        if m:
            current_text = m.group(0).strip()
            week_no = m.group(1) or m.group(2)
            kw = f"KW{int(week_no):02d}"

    if current_text is None:
        # Bu hata artık teşhis açısından da daha faydalı.
        title = ""
        try:
            title = page.title()
        except Exception:
            pass

        raise RuntimeError(
            "Current brochure başlığı bulunamadı. "
            f"Sayfa title: {title!r}"
        )

    # ------------------------------------------------------------
    # Linki bul
    # ------------------------------------------------------------
    viewer = None
    card_text = ""

    if current_h2 is not None:
        # Önce aynı kart/section içinde ara.
        containers = [
            "xpath=ancestor::div[contains(@class,'card')][1]",
            "xpath=ancestor::section[1]",
            "xpath=ancestor::div[contains(@class,'row')][1]",
            "xpath=..",
        ]

        for xp in containers:
            try:
                c = current_h2.locator(xp)
                if c.count() == 0:
                    continue

                a = c.locator("a[href*='/Prospekte/']")
                for i in range(a.count()):
                    href = a.nth(i).get_attribute("href") or ""
                    if re.search(
                        r"/Prospekte/[^/]+-\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}_\d+/?$",
                        href,
                        re.I,
                    ):
                        viewer = urljoin(page.url, href)
                        try:
                            card_text = c.inner_text(timeout=1000)
                        except Exception:
                            pass
                        break

                if viewer:
                    break
            except Exception:
                pass

        # Kartta bulunamazsa başlıktan sonraki ilk tarihli prospekt linki.
        if not viewer:
            try:
                a = current_h2.locator(
                    "xpath=following::a[contains(@href,'/Prospekte/')][1]"
                )
                if a.count():
                    href = a.get_attribute("href") or ""
                    if re.search(
                        r"/Prospekte/[^/]+-\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}_\d+/?$",
                        href,
                        re.I,
                    ):
                        viewer = urljoin(page.url, href)
            except Exception:
                pass

    # ------------------------------------------------------------
    # H2 bulunamadıysa: ham HTML'den Current başlığından sonraki
    # ilk tarihli /Prospekte/ linkini seç.
    # ------------------------------------------------------------
    if not viewer:
        # Current metnini HTML'de bulmaya çalış.
        # Etiketleri atarak normalize edilmiş HTML üzerinden ilerle.
        plain_html = re.sub(r"<[^>]+>", " ", html)
        plain_html = re.sub(r"\s+", " ", plain_html)

        m = current_re.search(plain_html)
        if m:
            tail = plain_html[m.end():]
            lm = re.search(
                r'https?://www\.discounto\.de/Prospekte/[^"\s<>]+'
                r'|/Prospekte/[^"\s<>]+',
                tail,
                re.I,
            )
            if lm:
                href = lm.group(0)
                if not href.startswith("http"):
                    href = urljoin(page.url, href)
                if re.search(
                    r"/Prospekte/[^/]+-\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}_\d+/?$",
                    href,
                    re.I,
                ):
                    viewer = href

    if not viewer:
        raise RuntimeError(
            f"Current başlığı bulundu ({current_text}) fakat "
            "ona bağlı tarihli prospekt linki bulunamadı."
        )

    # Tarihleri viewer URL'sinden kesin olarak çıkar.
    start, end = parse_dates(viewer)

    # URL'den çıkmadıysa kart/body metninden dene.
    if not start:
        start, end = parse_dates(card_text)

    return {
        "viewer": viewer,
        "kw": kw,
        "start": start,
        "end": end,
        "heading": current_text,
        "card_text": card_text,
    }


def find_pdf_url(page, viewer_url):
    """Viewer sayfasından PDF URL'sini hızlı ve güvenli şekilde bulur.

    Önemli: Eski sürümde bütün <a> elemanlarını tek tek dolaşıyorduk.
    Özellikle OBI gibi sayfalarda bu liste çok büyük olabildiği için
    işlem burada uzun süre "takılmış" gibi görünebiliyordu.
    CSS selector ile doğrudan PDF adaylarını alıyoruz.
    """
    page.goto(viewer_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1800)

    # 1) href'i .pdf içeren linkler — doğrudan selector.
    try:
        pdf_links = page.locator("a[href*='.pdf'], a[href*='.PDF']")
        count = min(pdf_links.count(), 20)
        for i in range(count):
            try:
                href = pdf_links.nth(i).get_attribute("href", timeout=1500) or ""
                if ".pdf" in href.lower():
                    return normalize_url(href.replace("&amp;", "&"))
            except Exception:
                continue
    except Exception:
        pass

    # 2) HTML içinden src.discounto PDF — tek seferde regex.
    html = page.content()

    patterns = [
        r'https?://src\.discounto\.de/[^"\']+?\.pdf[^"\']*',
        r'//src\.discounto\.de/[^"\']+?\.pdf[^"\']*',
    ]

    for pattern in patterns:
        m = re.search(pattern, html, re.I)
        if m:
            return normalize_url(m.group(0).replace("&amp;", "&"))

    # 3) Genel PDF URL fallback.
    m = re.search(r'https?://[^"\']+?\.pdf(?:\?[^"\']*)?', html, re.I)
    if m:
        return normalize_url(m.group(0).replace("&amp;", "&"))

    raise RuntimeError("Viewer içinde PDF URL bulunamadı.")


def collect_brand(page, brand, manifest):
    print("=" * 70)
    print(f"[{brand}] Discounto")
    print(DISCOUNTO[brand])

    page.goto(
        DISCOUNTO[brand],
        wait_until="domcontentloaded",
        timeout=60000,
    )
    page.wait_for_timeout(2500)
    accept_cookies(page)
    page.wait_for_timeout(1500)

    info = find_current_brochure(page, brand)

    print(f"[{brand}] CURRENT: {info['heading']}")
    print(f"[{brand}] Viewer: {info['viewer']}")

    if info["start"]:
        date1 = info["start"].strftime("%d-%m-%Y")
    else:
        date1 = "Tarih??"

    if info["end"]:
        date2 = info["end"].strftime("%d-%m-%Y")
    else:
        date2 = date1

    kw = info["kw"] or "KW??"

    # KW bulunamazsa URL tarihinden ISO hafta çıkar.
    if kw == "KW??" and info["start"]:
        kw = f"KW{info['start'].isocalendar().week:02d}"

    print(f"[{brand}] Viewer açılıyor, PDF aranıyor...")
    pdf_url = find_pdf_url(page, info["viewer"])
    print(f"[{brand}] PDF: {pdf_url}")

    filename = (
        f"{safe_name(brand)}_{kw}_"
        f"{date1}_{date2}.pdf"
    )

    dest = OUTPUT_DIR / brand / filename

    key = pdf_url.split("?", 1)[0].lower()

    # Duplicate: manifest veya dosya
    old = manifest.get(key)

    if old:
        old_path = Path(old)
        if is_valid_pdf(old_path):
            print(f"  ZATEN VAR: {old_path.name}")
            return "skip"

    if is_valid_pdf(dest):
        manifest[key] = str(dest)
        print(f"  ZATEN VAR: {dest.name}")
        return "skip"

    # Aynı isimde bozuk dosya varsa temizle
    if dest.exists():
        try:
            dest.unlink()
        except Exception:
            pass

    size = download_pdf(
        pdf_url,
        dest,
        referer=info["viewer"],
    )

    manifest[key] = str(dest)

    print(f"  İNDİRİLDİ: {size / 1024 / 1024:.2f} MB")
    print(f"  DOSYA: {dest}")

    return "download"


def main():
    print("=" * 70)
    print("FINAL PROSPEKT COLLECTOR v1.7")
    print("9 MARKA - SADECE DISCOUNTO")
    print("=" * 70)
    print(f"OUTPUT: {OUTPUT_DIR}")
    print()

    manifest = load_manifest()

    downloaded = 0
    skipped = 0
    failed = 0
    failed_brands = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        page = browser.new_page(
            viewport={"width": 1440, "height": 900},
            locale="de-DE",
        )

        for brand in BRANDS:
            try:
                result = collect_brand(page, brand, manifest)

                if result == "download":
                    downloaded += 1
                elif result == "skip":
                    skipped += 1

            except Exception as e:
                failed += 1
                failed_brands.append(f"{brand}: {type(e).__name__}: {e}")
                print(f"[{brand}] HATA: {type(e).__name__}: {e}")

            print()

        browser.close()

    save_manifest(manifest)

    report = {
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
        "failed_brands": failed_brands,
    }
    (BASE_DIR / "collector_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=" * 70)
    print("FINAL SONUÇ")
    print("=" * 70)
    print(f"Yeni indirilen : {downloaded}")
    print(f"Zaten mevcut   : {skipped}")
    print(f"Hatalı         : {failed}")
    print(f"Klasör         : {OUTPUT_DIR}")
    print("=" * 70)
    print()
    print("Klasör yapısı:")
    for brand in BRANDS:
        print(f"  FINAL_PROSPEKTE\\{brand}\\")


if __name__ == "__main__":
    main()
