# -*- coding: utf-8 -*-
"""
Toplama + GitHub Release yükleme sonuçlarını özetleyip Gmail SMTP üzerinden e-posta gönderir.
collector.py'nin ürettiği collector_report.json ve upload_to_github_release.py'nin ürettiği
github_release_report.json dosyalarını okur. Biri veya ikisi de yoksa "çalışmadı" olarak
işaretler (örn. collector.py hiç bitmeden çökerse).

Ortam değişkenleri:
  GMAIL_ADDRESS       - gönderen Gmail adresi
  GMAIL_APP_PASSWORD  - Gmail uygulama şifresi (boşluksuz)
  REPORT_EMAIL_TO     - raporun gideceği adres
"""

from pathlib import Path
from datetime import datetime, timezone, timedelta
import json
import os
import smtplib
import sys
from email.mime.text import MIMEText

BASE_DIR = Path(__file__).resolve().parent

TR_TZ = timezone(timedelta(hours=3))


def load_json(name):
    path = BASE_DIR / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_body(collector_report, release_report):
    lines = []
    now_tr = datetime.now(TR_TZ).strftime("%d-%m-%Y %H:%M")
    lines.append(f"Prospekt Collector calisma raporu - {now_tr} (TR saati)")
    lines.append("")

    lines.append("== Toplama (Discounto) ==")
    if collector_report is None:
        lines.append("Rapor bulunamadi - script bitmeden calisma durmus olabilir.")
    else:
        lines.append(f"Yeni indirilen : {collector_report['downloaded']}")
        lines.append(f"Zaten mevcut   : {collector_report['skipped']}")
        lines.append(f"Hatali         : {collector_report['failed']}")
        for line in collector_report.get("failed_brands", []):
            lines.append(f"  - {line}")
    lines.append("")

    lines.append("== GitHub Release'e yukleme ==")
    if release_report is None:
        lines.append("Rapor bulunamadi - yukleme adimi hic calismamis olabilir.")
    else:
        lines.append(f"Yuklenen : {release_report['uploaded']}")
        lines.append(f"Hatali   : {release_report['failed']}")
        for line in release_report.get("failed_files", []):
            lines.append(f"  - {line}")

        if release_report.get("zip_url"):
            lines.append("")
            lines.append(f"TUMUNU TEK SEFERDE INDIR (zip): {release_report['zip_url']}")

        if release_report.get("release_url"):
            lines.append("")
            lines.append(f"Tum dosyalar (release sayfasi): {release_report['release_url']}")

        downloads = release_report.get("downloads", [])
        if downloads:
            lines.append("")
            lines.append("Dogrudan indirme linkleri:")
            lines.append("")
            for item in sorted(downloads, key=lambda d: d["brand"]):
                lines.append(item["brand"])
                lines.append(f"  {item['url']}")
                lines.append("")

    return "\n".join(lines)


def clean_env(name):
    """Ortam değişkenini okur, olası UTF-8 BOM ve baştaki/sondaki boşlukları temizler."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    return raw.encode("utf-8").decode("utf-8-sig").strip()


def main():
    gmail_address = clean_env("GMAIL_ADDRESS")
    gmail_password = clean_env("GMAIL_APP_PASSWORD")
    report_to = clean_env("REPORT_EMAIL_TO")

    if not gmail_address or not gmail_password or not report_to:
        print("HATA: GMAIL_ADDRESS, GMAIL_APP_PASSWORD veya REPORT_EMAIL_TO tanımlı değil.")
        sys.exit(1)

    collector_report = load_json("collector_report.json")
    release_report = load_json("github_release_report.json")

    total_failed = (collector_report or {}).get("failed", 0) + (release_report or {}).get("failed", 0)
    ok = collector_report is not None and release_report is not None and total_failed == 0
    status = "OK" if ok else "DIKKAT"

    subject = f"[Prospekt Collector] {status} - {datetime.now(TR_TZ).strftime('%d-%m-%Y')}"
    body = build_body(collector_report, release_report)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = report_to

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(gmail_address, gmail_password)
        server.sendmail(gmail_address, [report_to], msg.as_string())

    print(f"Rapor gönderildi: {report_to}")


if __name__ == "__main__":
    main()
