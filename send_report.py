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
from collections import Counter
import html
import json
import os
import re
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
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


def file_info(filename):
    """MARKA_KW46_09-11-2026_14-11-2026.pdf -> ("KW46", "09.11 - 14.11")"""
    m = re.search(r"_(KW\d+)_(\d{2})-(\d{2})-\d{4}_(\d{2})-(\d{2})-\d{4}", filename)
    if not m:
        return None, ""
    return m.group(1), f"{m.group(2)}.{m.group(3)} - {m.group(4)}.{m.group(5)}"


def collect_problems(collector_report, release_report):
    problems = []
    if collector_report is None:
        problems.append("Toplama adımı bitmeden durmuş, rapor yok.")
    else:
        problems += collector_report.get("failed_brands", [])
    if release_report is None:
        problems.append("Yükleme adımı çalışmamış, rapor yok.")
    else:
        problems += release_report.get("failed_files", [])
    return problems


def build_bodies(release_report, problems, kw, retention_weeks):
    rr = release_report or {}
    zip_url = rr.get("zip_url")
    downloads = sorted(rr.get("downloads", []), key=lambda d: d["brand"])
    n = len(downloads)

    # --- düz metin (HTML açamayan istemciler için) ---
    t = [f"Haftalık broşürler {kw}".strip(), ""]
    if zip_url:
        t += [f"Tümünü indir (ZIP, {n} PDF):", zip_url, ""]
    for d in downloads:
        _, dates = file_info(d["filename"])
        t.append(f"{d['brand']:<10} {dates}")
    if problems:
        t += ["", "Alınamayanlar:"] + [f"- {p}" for p in problems]
    t += ["", f"Bağlantılar {retention_weeks} hafta geçerlidir."]
    text = "\n".join(t)

    # --- HTML ---
    h = ['<div style="font-family:Arial,Helvetica,sans-serif;color:#1f2937;max-width:560px">']
    h.append(f'<h2 style="margin:0 0 16px;font-size:20px">Haftalık broşürler {html.escape(kw)}</h2>')
    if zip_url:
        h.append(
            f'<a href="{html.escape(zip_url)}" style="display:inline-block;background:#0f766e;'
            'color:#ffffff;text-decoration:none;font-weight:bold;font-size:16px;'
            f'padding:14px 24px;border-radius:6px">Tümünü indir (ZIP, {n} PDF)</a>'
        )
    if downloads:
        h.append('<table style="margin-top:24px;border-collapse:collapse;font-size:13px;color:#4b5563">')
        for d in downloads:
            _, dates = file_info(d["filename"])
            h.append(
                f'<tr><td style="padding:3px 16px 3px 0"><a href="{html.escape(d["url"])}" '
                f'style="color:#4b5563">{html.escape(d["brand"])}</a></td>'
                f'<td style="padding:3px 0">{html.escape(dates)}</td></tr>'
            )
        h.append("</table>")
    if problems:
        h.append('<div style="margin-top:20px;padding:12px;background:#fef2f2;border-radius:6px;'
                 'font-size:13px;color:#991b1b"><b>Alınamayanlar</b><br>')
        h.append("<br>".join(html.escape(p) for p in problems))
        h.append("</div>")
    h.append(f'<p style="margin-top:24px;font-size:12px;color:#9ca3af">Her Pazartesi otomatik gönderilir. '
             f'Bağlantılar {retention_weeks} hafta geçerlidir.</p></div>')
    return text, "".join(h)


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

    # Birden fazla alıcı virgülle ayrılır: "a@x.com, b@y.com"
    recipients = [a.strip() for a in report_to.split(",") if a.strip()]

    problems = collect_problems(collector_report, release_report)
    downloads = (release_report or {}).get("downloads", [])
    kws = Counter(file_info(d["filename"])[0] for d in downloads)
    kws.pop(None, None)
    kw = kws.most_common(1)[0][0] if kws else ""

    prefix = "[DİKKAT] " if problems else ""
    subject = f"{prefix}Haftalık broşürler {kw} - {datetime.now(TR_TZ).strftime('%d.%m.%Y')}"
    text, html_body = build_bodies(release_report, problems, kw, clean_env("RETENTION_WEEKS") or "5")

    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = ", ".join(recipients)

    # Teşhis (repo herkese açık: şifre/adres yazdırılmaz, sadece uzunluk ve alan adı)
    print(f"Teşhis: adres alan adı={gmail_address.split('@')[-1]}, "
          f"şifre uzunluğu={len(gmail_password)}, boşluk içeriyor mu={' ' in gmail_password}")

    def send_starttls():
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.starttls()
            server.login(gmail_address, gmail_password)
            server.sendmail(gmail_address, recipients, msg.as_string())

    def send_ssl():
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(gmail_address, gmail_password)
            server.sendmail(gmail_address, recipients, msg.as_string())

    sent = False
    for name, fn in (("587/STARTTLS", send_starttls), ("465/SSL", send_ssl)):
        for attempt in (1, 2):
            try:
                fn()
                print(f"Rapor gönderildi ({name}, deneme {attempt}): {len(recipients)} alıcı")
                sent = True
                break
            except smtplib.SMTPAuthenticationError as e:
                print(f"[{name} deneme {attempt}] Kimlik doğrulama reddedildi: {e.smtp_code} {e.smtp_error!r}")
                break  # şifre yanlışsa tekrar denemek anlamsız
            except Exception as e:
                print(f"[{name} deneme {attempt}] {type(e).__name__}: {e}")
        if sent:
            break

    if not sent:
        sys.exit(1)


if __name__ == "__main__":
    main()
