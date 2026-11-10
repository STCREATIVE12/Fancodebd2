import json
import re
import urllib.request
from datetime import datetime, timezone, timedelta

def fetch_fancode_data():
    output_json_file = "fancode_matches.json"

    # IST Time format (UTC + 5:30)
    ist_zone = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist_zone).strftime("%I:%M:%S %p %d-%m-%Y")

    final_payload = {
        "name": "Fancode Live Matches Data in Json",
        "telegram": "https://t.me/+rQTz5VL8CRpjNTZl",
        "last update time": now_ist,
        "matches": []
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"
    }

    print("🟢 Fetching FanCode schedule page...")
    target_url = "https://www.fancode.com/schedule"

    try:
        req = urllib.request.Request(target_url, headers=headers)
        with urllib.request.urlopen(req, timeout=25) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

        # Next.js ka embedded data JSON extract karna
        next_data_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)

        if next_data_match:
            data = json.loads(next_data_match.group(1))
            page_props = data.get("props", {}).get("pageProps", {})

            # Match list nikalne ke liye common schema keys check karna
            raw_cards = (
                page_props.get("matches") or 
                page_props.get("scheduleData") or 
                page_props.get("dehydratedState", {}).get("queries", []) or 
                []
            )

            seen_ids = set()

            # Recursively JSON scan karke matches dhoondhna
            def extract_matches(obj):
                if isinstance(obj, dict):
                    if ("matchId" in obj or "id" in obj) and ("startTime" in obj or "status" in obj or "teams" in obj):
                        mid = obj.get("matchId") or obj.get("id")
                        if mid and mid not in seen_ids:
                            seen_ids.add(mid)
                            
                            status = str(obj.get("status", "UPCOMING")).upper()
                            if "LIVE" in status:
                                final_status = "LIVE"
                            else:
                                final_status = "UPCOMING"

                            teams = obj.get("teams", [])
                            t1 = teams[0].get("name", "") if len(teams) > 0 and isinstance(teams[0], dict) else obj.get("team1", "")
                            t2 = teams[1].get("name", "") if len(teams) > 1 and isinstance(teams[1], dict) else obj.get("team2", "")

                            name = obj.get("name") or obj.get("title") or f"{t1} vs {t2}".strip()

                            entry = {
                                "event_category": obj.get("sport") or obj.get("sportName") or "Cricket",
                                "match_id": int(mid) if str(mid).isdigit() else mid,
                                "title": obj.get("title") or name,
                                "match_name": f"{t1} vs {t2}" if (t1 and t2) else name,
                                "event_name": obj.get("tourName") or obj.get("seriesName") or "FanCode Series",
                                "src": obj.get("src") or obj.get("image") or obj.get("thumbnail") or "",
                                "team_1": t1,
                                "team_2": t2,
                                "status": final_status,
                                "startTime": obj.get("startTime") or obj.get("startDate") or now_ist
                            }

                            if final_status == "LIVE":
                                entry["user-agent"] = headers["User-Agent"]
                                entry["dai_url"] = None
                                entry["adfree_url"] = None
                                entry["google_m3u8_hex"] = None
                                entry["akamai_m3u8_hex"] = None

                            final_payload["matches"].append(entry)

                    for v in obj.values():
                        extract_matches(v)
                elif isinstance(obj, list):
                    for item in obj:
                        extract_matches(item)

            extract_matches(raw_cards)

        # Fallback: Agar __NEXT_DATA__ structure kisi din change ho jaye
        if not final_payload["matches"]:
            print("🟡 Trying fallback regex parser...")
            slug_matches = re.findall(r'href="(/matches/[^"]+)"', html)
            seen_slugs = set()
            for path in slug_matches:
                slug = path.split("/")[-1].split("?")[0]
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)

                id_m = re.search(r'(\d+)', slug)
                mid = int(id_m.group(1)) if id_m else slug
                clean_name = re.sub(r'[-_]', ' ', slug).strip().title()

                final_payload["matches"].append({
                    "event_category": "Cricket",
                    "match_id": mid,
                    "title": clean_name,
                    "match_name": clean_name,
                    "event_name": "FanCode Series",
                    "src": "",
                    "team_1": "",
                    "team_2": "",
                    "status": "UPCOMING",
                    "startTime": now_ist
                })

        print(f"🟢 Matches Found: {len(final_payload['matches'])}")

    except Exception as e:
        print(f"🔴 Error: {str(e)}")

    with open(output_json_file, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=4, ensure_ascii=False)

    print(f"🟢 Saved to {output_json_file}")

if __name__ == "__main__":
    fetch_fancode_data()
    
