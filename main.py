import json
import re
import urllib.request
from datetime import datetime, timezone, timedelta

def fetch_fancode_data():
    output_json_file = "fancode_matches.json"

    # IST Time without any external library (UTC + 5:30)
    ist_zone = timezone(timedelta(hours=5, minutes=30))
    now_ist = datetime.now(ist_zone).strftime("%I:%M:%S %p %d-%m-%Y")

    final_payload = {
        "name": "Fancode Live Matches Data in Json",
        "telegram": "https://t.me/+rQTz5VL8CRpjNTZl",
        "last update time": now_ist,
        "matches": []
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5"
    }

    print("🟢 Fetching FanCode schedule page...")

    target_url = "https://www.fancode.com/schedule"
    try:
        req = urllib.request.Request(target_url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

        # Matches links find karna
        raw_matches = re.findall(r'href="(/matches/[^"]+)"', html)
        seen_ids = set()

        for path in raw_matches:
            slug = path.split("/")[-1].split("?")[0]
            
            # Match ID nikalna
            id_match = re.search(r'(\d+)', slug)
            match_id = int(id_match.group(1)) if id_match else slug

            if match_id in seen_ids:
                continue
            seen_ids.add(match_id)

            # Match title format karna
            clean_title = re.sub(r'[-_]', ' ', slug).strip()
            clean_title = re.sub(r'\s+', ' ', clean_title).title()

            teams = clean_title.split(" Vs ")
            team_1 = teams[0].strip() if len(teams) > 0 else clean_title
            team_2 = teams[1].strip() if len(teams) > 1 else ""

            match_name = f"{team_1} vs {team_2}" if team_2 else team_1

            entry = {
                "event_category": "Cricket",
                "match_id": match_id,
                "title": clean_title,
                "match_name": match_name,
                "event_name": "FanCode Series",
                "src": "",
                "team_1": team_1,
                "team_2": team_2,
                "status": "UPCOMING",
                "startTime": now_ist
            }

            final_payload["matches"].append(entry)

        print(f"🟢 Found {len(final_payload['matches'])} matches.")

    except Exception as e:
        print(f"🔴 Error fetching matches: {str(e)}")

    with open(output_json_file, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=4, ensure_ascii=False)

    print(f"🟢 Done! Saved to {output_json_file}")

if __name__ == "__main__":
    fetch_fancode_data()
    
