# Prospekt Collector (Cloud)

`prospekt-collector`'ın (bkz. [cetinkayao-code/prospekt-collector](https://github.com/cetinkayao-code/prospekt-collector)) bulutta, GitHub Actions üzerinde otomatik çalışan kopyası. Orijinal repo elle çalıştırılan bir Windows script'iydi; bu repo aynı toplama mantığını değiştirmeden, bulutta zamanlanmış olarak çalışacak şekilde uyarlar.

## Ne yapıyor

`collector.py`, 9 Alman market/market zinciri markasının (LIDL, NETTO, PENNY, TOOM, BAUHAUS, OBI, NORMA, ALDI-NORD, ALDI-SUD) Discounto.de üzerindeki güncel haftalık broşürünü bulur ve PDF olarak `FINAL_PROSPEKTE/<marka>/` altına indirir. Daha önce indirilmiş bir broşür tekrar indirilmez (`collector_manifest_v16.json` ile takip edilir).

## Otomasyon

`.github/workflows/collector.yml`, her **Pazartesi saat 12:00 Türkiye saatinde** (09:00 UTC) çalışır ve yeni indirilen PDF'leri otomatik olarak bu repoya commit'ler. `Actions` sekmesinden **Run workflow** ile elle de tetiklenebilir.

## Yerelde çalıştırma

```
pip install -r requirements.txt
python -m playwright install --with-deps chromium
python collector.py
```

Görünür tarayıcı ile denemek için: `HEADLESS=0 python collector.py` (Windows PowerShell: `$env:HEADLESS="0"`).

## Yol haritası

- [x] Bulutta (GitHub Actions) zamanlanmış çalışma
- [x] Sonuçların bu repoya otomatik commit'lenmesi
- [ ] Sonuçların şirket SharePoint'ine (Microsoft Graph API ile) otomatik yüklenmesi — bir Azure AD uygulama kaydı ve gerekli Graph API izinleri gerektiriyor, henüz kurulmadı.
