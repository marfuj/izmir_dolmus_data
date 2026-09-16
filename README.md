# izmir_dolmus_data

İzmir Dolmuş uygulamasının okuduğu **açık veri**. Kod burada değil; yalnızca
periyodik üretilen veri dosyaları.

## events_izmir.json
İzmir etkinlikleri (konser, tiyatro, stand-up, sergi…), tek dosyada.
- Kaynaklar: **Ticketmaster (Biletix) Discovery API** + **İzmir Büyükşehir
  Belediyesi Kültür-Sanat API'si** (CC-BY 4.0).
- `.github/workflows/events.yml` bunu **6 saatte bir** günceller
  (`fetch_events.py`). Ticketmaster anahtarı repo secret'ında (`TM_API_KEY`).
- Her etkinlik: `title, category, start, end, venue, city, lat, lng, image,
  url, source`.

Uygulama bu dosyayı `raw.githubusercontent.com` üzerinden okur; hiçbir telefon
Ticketmaster'ı doğrudan çağırmaz (kota/anahtar güvenliği).
