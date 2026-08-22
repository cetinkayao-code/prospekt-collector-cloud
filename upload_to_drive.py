# -*- coding: utf-8 -*-
"""
FINAL_PROSPEKTE altındaki PDF'leri Google Drive'daki paylaşılan klasöre yükler.
Her marka için Drive'da (yoksa oluşturarak) aynı isimde bir alt klasör kullanır.
Aynı isimde dosya zaten varsa tekrar yüklemez.

Kişisel/ücretsiz Gmail hesaplarında servis hesaplarının kendi depolama kotası
olmadığı için (bkz. Google'ın "Service Accounts do not have storage quota" hatası),
kullanıcının kendi hesabı adına, bir kereliğine alınmış bir OAuth refresh token
ile yükleme yapılır (bkz. get_refresh_token.py - yerelde tek seferlik çalıştırılır).

Ortam değişkenleri:
  GDRIVE_OAUTH_CLIENT_ID     - OAuth istemci ID'si
  GDRIVE_OAUTH_CLIENT_SECRET - OAuth istemci sırrı
  GDRIVE_OAUTH_REFRESH_TOKEN - kullanıcı hesabı adına alınmış refresh token
  GDRIVE_FOLDER_ID           - hedef Drive klasörünün ID'si
"""

from pathlib import Path
import json
import os
import sys

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "FINAL_PROSPEKTE"


def clean_env(name):
    """Ortam değişkenini okur, olası UTF-8 BOM ve baştaki/sondaki boşlukları temizler."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    return raw.encode("utf-8").decode("utf-8-sig").strip()


def get_drive_service():
    client_id = clean_env("GDRIVE_OAUTH_CLIENT_ID")
    client_secret = clean_env("GDRIVE_OAUTH_CLIENT_SECRET")
    refresh_token = clean_env("GDRIVE_OAUTH_REFRESH_TOKEN")
    folder_id = clean_env("GDRIVE_FOLDER_ID")

    if not all([client_id, client_secret, refresh_token, folder_id]):
        print(
            "HATA: GDRIVE_OAUTH_CLIENT_ID, GDRIVE_OAUTH_CLIENT_SECRET, "
            "GDRIVE_OAUTH_REFRESH_TOKEN veya GDRIVE_FOLDER_ID tanımlı değil."
        )
        sys.exit(1)

    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    creds.refresh(Request())

    service = build("drive", "v3", credentials=creds)
    return service, folder_id


def find_or_create_subfolder(service, parent_id, name):
    query = (
        f"'{parent_id}' in parents and name = '{name}' "
        "and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    res = service.files().list(q=query, fields="files(id, name)", spaces="drive").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def file_exists_in_folder(service, parent_id, filename):
    query = f"'{parent_id}' in parents and name = '{filename}' and trashed = false"
    res = service.files().list(q=query, fields="files(id)", spaces="drive").execute()
    return len(res.get("files", [])) > 0


def upload_file(service, parent_id, path):
    media = MediaFileUpload(str(path), mimetype="application/pdf", resumable=True)
    metadata = {"name": path.name, "parents": [parent_id]}
    service.files().create(body=metadata, media_body=media, fields="id").execute()


def main():
    if not OUTPUT_DIR.exists():
        print("FINAL_PROSPEKTE klasörü yok, yüklenecek bir şey bulunamadı.")
        return

    service, root_folder_id = get_drive_service()

    uploaded = 0
    skipped = 0
    failed = 0
    failed_files = []

    for brand_dir in sorted(p for p in OUTPUT_DIR.iterdir() if p.is_dir()):
        pdfs = sorted(brand_dir.glob("*.pdf"))
        if not pdfs:
            continue

        try:
            brand_folder_id = find_or_create_subfolder(service, root_folder_id, brand_dir.name)
        except Exception as e:
            failed += len(pdfs)
            failed_files.append(f"{brand_dir.name}: klasör oluşturulamadı - {type(e).__name__}: {e}")
            print(f"[{brand_dir.name}] KLASÖR HATASI: {e}")
            continue

        for pdf in pdfs:
            try:
                if file_exists_in_folder(service, brand_folder_id, pdf.name):
                    print(f"[{brand_dir.name}] ZATEN DRIVE'DA VAR: {pdf.name}")
                    skipped += 1
                    continue

                print(f"[{brand_dir.name}] YÜKLENİYOR: {pdf.name}")
                upload_file(service, brand_folder_id, pdf)
                uploaded += 1
            except Exception as e:
                failed += 1
                failed_files.append(f"{brand_dir.name}/{pdf.name}: {type(e).__name__}: {e}")
                print(f"[{brand_dir.name}] YÜKLEME HATASI ({pdf.name}): {e}")

    report = {
        "uploaded": uploaded,
        "skipped": skipped,
        "failed": failed,
        "failed_files": failed_files,
    }
    (BASE_DIR / "drive_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print()
    print(f"Drive'a yüklenen : {uploaded}")
    print(f"Zaten mevcut     : {skipped}")
    print(f"Hatalı           : {failed}")


if __name__ == "__main__":
    main()
