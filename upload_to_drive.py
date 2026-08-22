# -*- coding: utf-8 -*-
"""
FINAL_PROSPEKTE altındaki PDF'leri Google Drive'daki paylaşılan klasöre yükler.
Her marka için Drive'da (yoksa oluşturarak) aynı isimde bir alt klasör kullanır.
Aynı isimde dosya zaten varsa tekrar yüklemez.

Ortam değişkenleri:
  GDRIVE_SERVICE_ACCOUNT_JSON - servis hesabı anahtarının JSON içeriği (tamamı)
  GDRIVE_FOLDER_ID            - hedef Drive klasörünün ID'si
"""

from pathlib import Path
import json
import os
import sys

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]
BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "FINAL_PROSPEKTE"


def get_drive_service():
    raw = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON")
    folder_id = os.environ.get("GDRIVE_FOLDER_ID")
    if not raw or not folder_id:
        print("HATA: GDRIVE_SERVICE_ACCOUNT_JSON veya GDRIVE_FOLDER_ID tanımlı değil.")
        sys.exit(1)

    # Bazı ortamlarda secret değeri baştaki UTF-8 BOM ile geliyor; temizle.
    raw = raw.encode("utf-8").decode("utf-8-sig")
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
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
