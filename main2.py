import asyncio
import json
import re
import urllib.request
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright

async def scrape_complete_fancode_live_and_upcoming():
    output_json_file = "fancode_matches.json"

    # IST Time format (UTC + 5:30)
    ist_zone = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist_zone)
    now_ist = now.strftime("%I:%M:%S %p %d-%m-%Y")

    final_payload = {
        "name": "Fancode Live Matches Data in Json",
        "telegram": "https://t.me/+rQTz5VL8CRpjNTZl",
        "last update time": now_ist,
        "matches": []
    }

    user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent=user_agent,
            viewport={"width": 1440, "height": 900}
        )
        page = await context.new_page()

        # STEP 1: Live Matches & Stream interceptor (/live-now/all-sports)
        print("🟢 Step 1: Checking Live Matches & Streaming Links...")
        live_matches_data = []

        try:
            await page.goto("https://www.fancode.com/live-now/all-sports", wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(4)

            live_cards = await page.evaluate("""() => {
                let items = [];
                let anchors = document.querySelectorAll('a[href*="/matches/"]');
                anchors.forEach(a => {
                    let href = a.href;
                    let text = a.innerText.replace(/\\n/g, ' | ').trim();
                    let img = a.querySelector('img');
                    let src = img ? (img.src || img.getAttribute('data-src') || '') : '';
                    if (href && text.length > 3) {
                        items.push({ href, text, src });
                    }
                });
                return items;
            }""")

            for card in live_cards:
                m_url = card["href"]
                raw_text = card["text"]
                img_src = card["src"]

                id_m = re.search(r'[-/](\d{6,8})(?:/|$)', m_url)
                mid_num = id_m.group(1) if id_m else "0"
                match_id = f"{mid_num}_ENG"

                # Stream capture
                match_page = await context.new_page()
                captured_streams = []
                match_page.on("request", lambda req: captured_streams.append(req.url) if ".m3u8" in req.url else None)

                try:
                    await match_page.goto(m_url, wait_until="domcontentloaded", timeout=15000)
                    await asyncio.sleep(5)
                except Exception:
                    pass

                master_url = next((u for u in captured_streams if "1080p.m3u8" in u or "index.m3u8" in u), None)
                if not master_url and captured_streams:
                    master_url = captured_streams[0]

                # Convert master .m3u8 content into HEX format (Jaise aapke json mein hai)
                m3u8_hex = None
                if master_url:
                    try:
                        req = urllib.request.Request(master_url, headers={"User-Agent": user_agent})
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            m3u8_text = resp.read().decode('utf-8', errors='ignore')
                            m3u8_hex = m3u8_text.encode('utf-8').hex()
                    except Exception:
                        pass

                await match_page.close()

                # Clean Title & Teams
                clean_t = re.sub(r'(LIVE|WATCH LIVE|HIGHLIGHTS|VIEW DETAILS)', '', raw_text, flags=re.I)
                clean_t = re.sub(r'[-–—|]', ' ', clean_t).strip()
                t_parts = re.split(r'\s+vs\s+|\s+VS\s+|\s+v\s+', clean_t, flags=re.I)
                t1 = t_parts[0].strip() if len(t_parts) > 0 else clean_t
                t2 = t_parts[1].strip() if len(t_parts) > 1 else ""

                live_entry = {
                    "event_category": "Cricket", # Dynamic detect
                    "match_id": match_id,
                    "title": f"{clean_t} [English]",
                    "match_name": f"{t1} vs {t2} [English]" if t2 else f"{clean_t} [English]",
                    "event_name": clean_t,
                    "src": img_src,
                    "team_1": t1,
                    "team_2": t2,
                    "status": "LIVE",
                    "startTime": now_ist,
                    "user-agent": user_agent,
                    "dai_url": master_url,
                    "adfree_url": master_url,
                    "google_m3u8_hex": m3u8_hex,
                    "akamai_m3u8_hex": None
                }
                final_payload["matches"].append(live_entry)
                print(f"🔴 Captured LIVE: {live_entry['match_name']}")

        except Exception as e:
            print(f"🟡 Live scrape info: {str(e)}")

        # STEP 2: Sabhi Tours se 1-Week Upcoming Matches Extract karna
        print("🟢 Step 2: Extracting 1-Week Upcoming Matches across all Sports...")
        tours_url = "https://www.fancode.com/tour-listing/all"
        tours_list = []

        try:
            await page.goto(tours_url, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(3)

            for _ in range(5):
                await page.evaluate("window.scrollBy(0, 1000);")
                await asyncio.sleep(0.8)

            tours_list = await page.evaluate("""() => {
                let items = [];
                let anchors = document.querySelectorAll('a[href*="/tour/"]');
                anchors.forEach(a => {
                    let href = a.href;
                    let text = a.innerText.replace(/\\n/g, ' ').trim();
                    if (href && !items.some(i => i.href === href)) {
                        items.push({ href: href, title: text });
                    }
                });
                return items;
            }""")
        except Exception as e:
            print(f"🔴 Error loading tours: {str(e)}")

        seen_match_ids = {m["match_id"] for m in final_payload["matches"]}

        # Top 35 active tours scan
        for idx, tour in enumerate(tours_list[:35]):
            t_url = tour["href"]
            matches_url = t_url if "/matches" in t_url else f"{t_url.rstrip('/')}/matches"
            print(f"[{idx+1}/{min(len(tours_list), 35)}] Scanning: {matches_url}")

            sport_name = "Cricket"
            if "/football/" in t_url:
                sport_name = "Football"
            elif "/tennis/" in t_url or "/lawn-tennis/" in t_url:
                sport_name = "Tennis"
            elif "/formula1/" in t_url:
                sport_name = "Formula 1"
            elif "/motogp/" in t_url:
                sport_name = "MotoGP"
            elif "/badminton/" in t_url:
                sport_name = "Badminton"
            elif "/golf/" in t_url:
                sport_name = "Golf"
            elif "/racing/" in t_url:
                sport_name = "Motorsports"

            try:
                await page.goto(matches_url, wait_until="domcontentloaded", timeout=18000)
                await asyncio.sleep(2)
                await page.evaluate("window.scrollBy(0, 800);")
                await asyncio.sleep(1)

                upcoming_fixtures = await page.evaluate("""() => {
                    let found = [];

                    // Top hero/banner poster check
                    let pageHero = document.querySelector('img[class*="CasaBackgroundImage"], div[class*="hero"] img');
                    let pageHeroSrc = pageHero ? pageHero.src : '';

                    // DOM Cards
                    let cards = document.querySelectorAll('a[href*="/matches/"], div[role="article"]');
                    cards.forEach(c => {
                        let text = c.innerText ? c.innerText.replace(/\\n/g, ' | ') : '';
                        let linkEl = c.tagName === 'A' ? c : c.querySelector('a');
                        let href = linkEl ? linkEl.href : '';
                        let img = c.querySelector('img');
                        let poster = img ? (img.src || img.getAttribute('data-src') || '') : pageHeroSrc;

                        let isComp = text.includes('Completed') || text.includes('Highlights');
                        if (text.length > 5 && !isComp) {
                            found.push({ text, href, poster });
                        }
                    });

                    // Next.js state scan
                    if (window.__NEXT_DATA__) {
                        try {
                            let scan = (node) => {
                                if (!node) return;
                                if (typeof node === 'object') {
                                    if ((node.matchId || node.id) && (node.startTime || node.teams)) {
                                        let poster = node.src || node.image || node.banner || pageHeroSrc;
                                        found.push({
                                            text: (node.name || node.title || '') + ' | ' + (node.startTime || ''),
                                            href: '/matches/' + (node.matchId || node.id),
                                            poster: poster,
                                            node: node
                                        });
                                    }
                                    for (let k in node) scan(node[k]);
                                }
                            };
                            scan(window.__NEXT_DATA__);
                        } catch(e) {}
                    }

                    return found;
                }""")

                for itm in upcoming_fixtures:
                    raw_text = itm.get("text", "")
                    href = itm.get("href", "")
                    node_data = itm.get("node", {})

                    id_m = re.search(r'[-/](\d{6,8})(?:/|$)', href)
                    mid_str = id_m.group(1) if id_m else str(node_data.get("matchId") or node_data.get("id") or "")
                    
                    if not mid_str:
                        mid_str = str(abs(hash(raw_text)))[:7]

                    mid_val = int(mid_str) if mid_str.isdigit() else mid_str

                    if mid_val in seen_match_ids or f"{mid_val}_ENG" in seen_match_ids:
                        continue
                    seen_match_ids.add(mid_val)

                    clean_t = re.sub(r'(Upcoming|Completed|Highlights|Watch Live|Live Now|VIEW DETAILS)', '', raw_text, flags=re.I)
                    clean_t = re.sub(r'[-–—|]', ' ', clean_t)
                    clean_t = re.sub(r'\s+', ' ', clean_t).strip()

                    teams = re.split(r'\s+vs\s+|\s+VS\s+|\s+v\s+', clean_t, flags=re.I)
                    t1 = teams[0].strip() if len(teams) > 0 else clean_t
                    t2 = teams[1].strip() if len(teams) > 1 else ""

                    match_name = f"{t1} vs {t2}" if t2 else t1
                    event_title = tour.get("title") or f"{sport_name} Series"
                    full_title = f"{match_name} ({event_title})"

                    # Exact Poster resolution
                    poster_url = itm.get("poster", "")
                    if not poster_url:
                        poster_url = f"https://www.fancode.com/skillup-uploads/cms-media/{mid_str}_fc-web.jpg"

                    start_time = node_data.get("startTime") or now_ist

                    # Exact Schema structure jaisa sample json mein hai
                    entry = {
                        "event_category": sport_name,
                        "match_id": mid_val,
                        "title": full_title,
                        "match_name": match_name,
                        "event_name": event_title,
                        "src": poster_url,
                        "team_1": t1,
                        "team_2": t2,
                        "status": "UPCOMING",
                        "startTime": start_time
                    }
                    final_payload["matches"].append(entry)

            except Exception:
                continue

        await browser.close()

        with open(output_json_file, "w", encoding="utf-8") as f:
            json.dump(final_payload, f, indent=4, ensure_ascii=False)

        print(f"🟢 Success! Total {len(final_payload['matches'])} matches saved in {output_json_file}")

if __name__ == "__main__":
    asyncio.run(scrape_complete_fancode_live_and_upcoming())
    
