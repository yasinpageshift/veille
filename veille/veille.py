import json, os, requests
from bs4 import BeautifulSoup

TOKEN = os.environ["TG_TOKEN"].strip()
CHAT_ID = os.environ["TG_CHAT_ID"].strip()

# À remplir plus tard avec tes vrais sites
SOURCES = []

SEEN_FILE = "seen.json"
seen = set(json.load(open(SEEN_FILE))) if os.path.exists(SEEN_FILE) else set()

def notifier(msg):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg}, timeout=20)
    print("Telegram:", r.status_code, r.text)
    r.raise_for_status()

if os.environ.get("MANUAL") == "1":
    notifier("✅ Le bot fonctionne !")

for s in SOURCES:
    try:
        r = requests.get(s["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select(s["selecteur"]):
            lien = requests.compat.urljoin(s["url"], a.get("href", ""))
            if lien and lien not in seen:
                seen.add(lien)
                notifier(f"[{s['nom']}] {a.get_text(strip=True)}\n{lien}")
    except Exception as e:
        print("Erreur", s["nom"], e)

json.dump(list(seen), open(SEEN_FILE, "w"))
