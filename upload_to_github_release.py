# -*- coding: utf-8 -*-
"""
FINAL_PROSPEKTE altındaki PDF'leri, o haftaya ait yeni bir GitHub Release'e
asset olarak yükler. Google Drive'daki OAuth/verification zincirinden kaçınmak
için GitHub Actions'ın kendi GITHUB_TOKEN'ı kullanılır - ek bir secret,
hesap veya doğrulama gerekmez, token süresi dolmaz.

RETENTION_WEEKS'ten eski release'ler (etiketleriyle birlikte) otomatik silinir,
böylece depolama sınırsız büyümez.

Ortam değişkenleri:
  GITHUB_TOKEN     - Actions'ın verdiği yerleşik token (contents: write yeterli)
  GITHUB_REPOSITORY - "owner/repo" (Actions tarafından otomatik set edilir)
  RETENTION_WEEKS  - kaç haftadan eski release'lerin silineceği (varsayılan 5)
"""

from pathlib import Path
from datetime import datetime, timezone, timedelta
import json
import os
import zipfile
import sys

import requests

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "FINAL_PROSPEKTE"
API_ROOT = "https://api.github.com"


def clean_env(name, default=None):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.encode("utf-8").decode("utf-8-sig").strip()


def api_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_release_by_tag(repo, token, tag):
    resp = requests.get(
        f"{API_ROOT}/repos/{repo}/releases/tags/{tag}",
        headers=api_headers(token),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def create_or_reuse_release(repo, token, tag, title, body):
    """Aynı gün workflow elle tekrar tetiklenirse (örn. bir hatadan sonra retry)
    o günün release'i zaten var olabilir - bu durumda hata vermek yerine
    var olan release'i yeniden kullanırız."""
    resp = requests.post(
        f"{API_ROOT}/repos/{repo}/releases",
        headers=api_headers(token),
        json={"tag_name": tag, "name": title, "body": body},
        timeout=30,
    )
    if resp.status_code == 422:
        return get_release_by_tag(repo, token, tag)
    resp.raise_for_status()
    return resp.json()


def delete_asset(repo, token, asset_id):
    requests.delete(
        f"{API_ROOT}/repos/{repo}/releases/assets/{asset_id}",
        headers=api_headers(token),
        timeout=30,
    )


def upload_asset(repo, upload_url_template, token, asset_name, path, existing_assets):
    """existing_assets: {asset_name: asset_id} - aynı isimde asset zaten varsa
    (örn. aynı gün retry), önce silip yeniden yükler."""
    if asset_name in existing_assets:
        delete_asset(repo, token, existing_assets[asset_name])

    upload_url = upload_url_template.split("{")[0]
    headers = api_headers(token)
    headers["Content-Type"] = "application/zip" if path.suffix == ".zip" else "application/pdf"
    with open(path, "rb") as f:
        resp = requests.post(
            upload_url,
            headers=headers,
            params={"name": asset_name},
            data=f,
            timeout=300,
        )
    resp.raise_for_status()
    return resp.json()


def cleanup_old_releases(repo, token, retention_weeks):
    resp = requests.get(
        f"{API_ROOT}/repos/{repo}/releases",
        headers=api_headers(token),
        params={"per_page": 100},
        timeout=30,
    )
    resp.raise_for_status()
    cutoff = datetime.now(timezone.utc) - timedelta(weeks=retention_weeks)

    deleted = []
    for release in resp.json():
        tag = release.get("tag_name", "")
        if not tag.startswith("prospekte-"):
            continue
        try:
            tag_date = datetime.strptime(tag.removeprefix("prospekte-"), "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            continue

        if tag_date >= cutoff:
            continue

        requests.delete(
            f"{API_ROOT}/repos/{repo}/releases/{release['id']}",
            headers=api_headers(token),
            timeout=30,
        )
        requests.delete(
            f"{API_ROOT}/repos/{repo}/git/refs/tags/{tag}",
            headers=api_headers(token),
            timeout=30,
        )
        deleted.append(tag)

    return deleted


def main():
    token = clean_env("GITHUB_TOKEN")
    repo = clean_env("GITHUB_REPOSITORY")
    retention_weeks = int(clean_env("RETENTION_WEEKS", "5"))

    if not token or not repo:
        print("HATA: GITHUB_TOKEN veya GITHUB_REPOSITORY tanımlı değil.")
        sys.exit(1)

    if not OUTPUT_DIR.exists():
        print("FINAL_PROSPEKTE klasörü yok, yüklenecek bir şey bulunamadı.")
        report = {"uploaded": 0, "skipped": 0, "failed": 0, "failed_files": [],
                   "release_url": None, "zip_url": None, "downloads": []}
        (BASE_DIR / "github_release_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return

    today = datetime.now(timezone.utc)
    tag = f"prospekte-{today.strftime('%Y-%m-%d')}"
    title = f"Prospektler - {today.strftime('%d-%m-%Y')}"

    brand_dirs = sorted(p for p in OUTPUT_DIR.iterdir() if p.is_dir())
    pdf_count = sum(len(list(b.glob("*.pdf"))) for b in brand_dirs)

    uploaded = 0
    failed = 0
    failed_files = []
    downloads = []
    release_url = None

    if pdf_count == 0:
        print("Yüklenecek PDF yok, release oluşturulmadı.")
    else:
        try:
            release = create_or_reuse_release(repo, token, tag, title, f"{pdf_count} PDF - otomatik yükleme")
            release_url = release["html_url"]
            upload_url_template = release["upload_url"]
            existing_assets = {a["name"]: a["id"] for a in release.get("assets", [])}
        except Exception as e:
            print(f"RELEASE OLUŞTURMA HATASI: {e}")
            failed += pdf_count
            failed_files.append(f"release oluşturulamadı: {type(e).__name__}: {e}")
            upload_url_template = None
            existing_assets = {}

        if upload_url_template:
            for brand_dir in brand_dirs:
                pdfs = sorted(brand_dir.glob("*.pdf"))
                for pdf in pdfs:
                    asset_name = f"{brand_dir.name}__{pdf.name}"
                    try:
                        print(f"[{brand_dir.name}] YÜKLENİYOR: {pdf.name}")
                        asset = upload_asset(repo, upload_url_template, token, asset_name, pdf, existing_assets)
                        uploaded += 1
                        downloads.append({
                            "brand": brand_dir.name,
                            "filename": pdf.name,
                            "url": asset["browser_download_url"],
                        })
                    except Exception as e:
                        failed += 1
                        failed_files.append(f"{brand_dir.name}/{pdf.name}: {type(e).__name__}: {e}")
                        print(f"[{brand_dir.name}] YÜKLEME HATASI ({pdf.name}): {e}")

    zip_url = None
    if pdf_count > 0 and upload_url_template:
        zip_name = f"Tum_Prospektler_{today.strftime('%Y-%m-%d')}.zip"
        zip_path = BASE_DIR / zip_name
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for brand_dir in brand_dirs:
                    for pdf in sorted(brand_dir.glob("*.pdf")):
                        zf.write(pdf, arcname=f"{brand_dir.name}/{pdf.name}")

            print(f"TÜMÜ ZİP OLARAK YÜKLENİYOR: {zip_name}")
            asset = upload_asset(repo, upload_url_template, token, zip_name, zip_path, existing_assets)
            zip_url = asset["browser_download_url"]
        except Exception as e:
            failed += 1
            failed_files.append(f"tumu.zip: {type(e).__name__}: {e}")
            print(f"ZİP YÜKLEME HATASI: {e}")
        finally:
            zip_path.unlink(missing_ok=True)

    try:
        deleted = cleanup_old_releases(repo, token, retention_weeks)
        if deleted:
            print(f"Silinen eski release'ler: {', '.join(deleted)}")
    except Exception as e:
        print(f"ESKİ RELEASE TEMİZLEME HATASI: {e}")

    report = {
        "uploaded": uploaded,
        "skipped": 0,
        "failed": failed,
        "failed_files": failed_files,
        "release_url": release_url,
        "zip_url": zip_url,
        "downloads": downloads,
    }
    (BASE_DIR / "github_release_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print()
    print(f"Release'e yüklenen : {uploaded}")
    print(f"Hatalı             : {failed}")


if __name__ == "__main__":
    main()
