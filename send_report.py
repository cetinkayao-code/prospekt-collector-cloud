# -*- coding: utf-8 -*-
"""
Toplama + Drive yükleme sonuçlarını özetleyip Gmail SMTP üzerinden e-posta gönderir.
collector.py'nin ürettiği collector_report.json ve upload_to_drive.py'nin ürettiği
drive_report.json dosyalarını okur. Biri veya ikisi de yoksa "çalışmadı" olarak işaretler
(örn. collector.py hiç bitmeden çökerse).

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


def build_body(collector_report, drive_report):
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

    lines.append("== Google Drive'a yukleme ==")
    if drive_report is None:
        lines.append("Rapor bulunamadi - yukleme adimi hic calismamis olabilir.")
    else:
        lines.append(f"Yuklenen   : {drive_report['uploaded']}")
        lines.append(f"Zaten vardi: {drive_report['skipped']}")
        lines.append(f"Hatali     : {drive_report['failed']}")
        for line in drive_report.get("failed_files", []):
            lines.append(f"  - {line}")

    return "\n".join(lines)


def main():
    gmail_address = os.environ.get("GMAIL_ADDRESS")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")
    report_to = os.environ.get("REPORT_EMAIL_TO")

    if not gmail_address or not gmail_password or not report_to:
        print("HATA: GMAIL_ADDRESS, GMAIL_APP_PASSWORD veya REPORT_EMAIL_TO tanımlı değil.")
        sys.exit(1)

    collector_report = load_json("collector_report.json")
    drive_report = load_json("drive_report.json")

    total_failed = (collector_report or {}).get("failed", 0) + (drive_report or {}).get("failed", 0)
    ok = collector_report is not None and drive_report is not None and total_failed == 0
    status = "OK" if ok else "DIKKAT"

    subject = f"[Prospekt Collector] {status} - {datetime.now(TR_TZ).strftime('%d-%m-%Y')}"
    body = build_body(collector_report, drive_report)

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
