#!/usr/bin/env python3
"""İzmir etkinliklerini resmi/lisanslı kaynaklardan çekip tek bir
events_izmir.json üretir. GitHub Actions (cron) bunu çalıştırır; uygulama
üretilen JSON'u okur (her telefon Ticketmaster'ı doğrudan çağırmaz →
kota/anahtar-sızması yok).

Kaynaklar:
  - Ticketmaster Discovery API (Biletix = Ticketmaster TR): konser/tiyatro/
    stand-up/spor. Mekan KOORDİNATLI gelir. Anahtar: env TM_API_KEY.
  - İBB Kültür-Sanat API (public, CC-BY): belediye etkinlikleri. Mekan sadece
    isim → landmarks.json'dan koordinata eşlenir (best-effort).

Kullanım: python fetch_events.py [cikti.json]
"""
import json
import os
import sys
import urllib.request
import urllib.parse
import unicodedata
from datetime import datetime, timezone

TM_KEY = os.environ.get("TM_API_KEY", "").strip()
TM_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
IBB_URL = "https://openapi.izmir.bel.tr/api/ibb/kultursanat/etkinlikler"
# landmarks.json yolu: env LANDMARKS_JSON ile ezilebilir (data reposunda kökte),
# yoksa varsayılan izmir_dolmus/assets/data/landmarks.json.
LANDMARKS = os.environ.get("LANDMARKS_JSON") or os.path.join(
    os.path.dirname(__file__), "..", "assets", "data", "landmarks.json")

UA = {"User-Agent": "izmir-dolmus-events/1.0"}


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def norm(s):
    """Türkçe-duyarlı kaba normalizasyon (eşleme için)."""
    if not s:
        return ""
    s = s.replace("İ", "i").replace("I", "i").replace("ı", "i")
    s = s.lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s if c.isalnum())


def load_venue_index():
    """landmarks.json → normalize(ad) -> (lat,lng). İBB mekan eşlemesi için."""
    idx = {}
    try:
        with open(LANDMARKS, "r", encoding="utf-8") as f:
            for l in json.load(f):
                idx[norm(l[0])] = (float(l[1]), float(l[2]))
    except Exception as e:
        print(f"[uyarı] landmarks okunamadı: {e}", file=sys.stderr)
    return idx


def match_venue(name, idx):
    """Mekan adını landmark koordinatına eşle (tam / içerir)."""
    n = norm(name)
    if not n:
        return (None, None)
    if n in idx:
        return idx[n]
    for k, v in idx.items():
        if len(k) >= 6 and (k in n or n in k):
            return v
    return (None, None)


def pick_image(images):
    if not images:
        return None
    best = None
    for im in images:
        w = im.get("width", 0) or 0
        if 500 <= w <= 1100 and im.get("ratio") == "16_9":
            return im.get("url")
        if best is None or w > (best.get("width", 0) or 0):
            best = im
    return best.get("url") if best else None


def fetch_ticketmaster():
    if not TM_KEY:
        print("[uyarı] TM_API_KEY yok → Ticketmaster atlandı.", file=sys.stderr)
        return []
    out = []
    for page in range(0, 3):  # ~200 etkinlik yeter
        q = urllib.parse.urlencode({
            "apikey": TM_KEY,
            "countryCode": "TR",
            "city": "Izmir",
            "size": 100,
            "page": page,
            "sort": "date,asc",
        })
        try:
            data = _get(f"{TM_URL}?{q}")
        except Exception as e:
            print(f"[uyarı] TM sayfa {page}: {e}", file=sys.stderr)
            break
        events = data.get("_embedded", {}).get("events", [])
        if not events:
            break
        for e in events:
            ven = (e.get("_embedded", {}).get("venues") or [{}])[0]
            loc = ven.get("location", {})
            cls = (e.get("classifications") or [{}])[0]
            dates = e.get("dates", {}).get("start", {})
            start = dates.get("dateTime") or dates.get("localDate")
            lat = loc.get("latitude")
            lng = loc.get("longitude")
            out.append({
                "id": "tm_" + str(e.get("id")),
                "source": "ticketmaster",
                "title": e.get("name"),
                "category": (cls.get("segment") or {}).get("name"),
                "start": start,
                "venue": ven.get("name"),
                "city": (ven.get("city") or {}).get("name"),
                "lat": float(lat) if lat else None,
                "lng": float(lng) if lng else None,
                "image": pick_image(e.get("images")),
                "url": e.get("url"),
            })
        total_pages = data.get("page", {}).get("totalPages", 1)
        if page + 1 >= total_pages:
            break
    return out


def fetch_ibb(idx):
    try:
        data = _get(IBB_URL)
    except Exception as e:
        print(f"[uyarı] İBB: {e}", file=sys.stderr)
        return []
    rows = data if isinstance(data, list) else data.get("value", data)
    out = []
    for e in rows if isinstance(rows, list) else []:
        venue = e.get("EtkinlikMerkezi")
        lat, lng = match_venue(venue or "", idx)
        out.append({
            "id": "ibb_" + str(e.get("Id")),
            "source": "ibb",
            "title": e.get("Adi"),
            "category": e.get("Tur"),
            "start": e.get("EtkinlikBaslamaTarihi"),
            "end": e.get("EtkinlikBitisTarihi"),
            "venue": venue,
            "city": "İzmir",
            "lat": lat,
            "lng": lng,
            "image": e.get("Resim") or e.get("KucukAfis"),
            "url": e.get("EtkinlikUrl"),
        })
    return out


def main():
    out_path = sys.argv[1] if len(sys.argv) > 1 else "events_izmir.json"
    idx = load_venue_index()
    events = fetch_ticketmaster() + fetch_ibb(idx)

    # Bitmiş etkinlikleri at (süren = bitişi bugünden sonra kalsın),
    # başlangıç tarihine göre sırala.
    today = datetime.now(timezone.utc).date().isoformat()
    def latest(ev):
        return (ev.get("end") or ev.get("start") or "")[:10]
    events = [e for e in events if latest(e) >= today]
    events.sort(key=lambda e: e.get("start") or "9999")

    doc = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "source": "Ticketmaster (Biletix) + İBB",
        "count": len(events),
        "events": events,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    with_coord = sum(1 for e in events if e.get("lat"))
    print(f"yazıldı: {out_path} — {len(events)} etkinlik "
          f"({with_coord} koordinatlı)")


if __name__ == "__main__":
    main()
