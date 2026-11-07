import json, os, re, time
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

TOKEN = os.environ["TG_TOKEN"].strip()
CHAT_ID = os.environ["TG_CHAT_ID"].strip()

LIEUX = ["Delémont", "Porrentruy", "Saignelégier", "Neuchâtel", "La Chaux-de-Fonds",
         "Fribourg", "Bulle", "Genève", "Nyon", "Yverdon-les-Bains", "Vallorbe"]
TERMES = ["operateur", "agent de production", "controleur qualite", "conditionnement",
          "assemblage", "montage", "salle blanche", "production"]

# Le titre doit contenir un de ces mots...
MOTS_OK = ["opérat", "operat", "agent", "contrôleur", "controleur", "conducteur",
           "production", "conditionnement", "assembl", "montage", "monteur",
           "salle blanche", "stérilis", "sterilis", "lavage", "finition",
           "fabrication", "qualit", "machine", "cnc", "manoeuvre", "manœuvre"]
# ...et aucun de ceux-là
MOTS_KO = ["formateur", "chef", "responsable", "ingénieur", "ingenieur", "directeur",
           "apprenti", "stagiaire", "polymécanicien", "polymecanicien", "programmeur",
           "mécanicien", "mecanicien", "commercial", "vendeur"]

SEEN_FILE = "seen.json"
seen = set(json.load(open(SEEN_FILE))) if os.path.exists(SEEN_FILE) else set()

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "fr-CH,fr;q=0.9,en;q=0.5",
})


def envoyer(texte):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": texte,
                            "disable_web_page_preview": "true"}, timeout=20)
    print("Telegram:", r.status_code)
    r.raise_for_status()


def envoyer_par_blocs(blocs):
    msg = ""
    for b in blocs:
        if len(msg) + len(b) > 3500:
            envoyer(msg)
            msg = ""
            time.sleep(1)
        msg += b + "\n\n"
    if msg:
        envoyer(msg)


def slug(s):
    return quote(s.lower().replace(" ", "-"))


def trop_vieille(age):
    m = re.fullmatch(r"(\d+)\+?\s*([a-z]+)", age.strip().lower())
    if not m:
        return False
    n, u = int(m.group(1)), m.group(2)
    return u == "m" or (u == "w" and n > 2)


nouvelles = []
vus_ce_run = set()
pages_ok = pages_total = 0

for lieu in LIEUX:
    for terme in TERMES:
        url = f"https://www.jobscout24.ch/en/jobs-in-{slug(lieu)}/{quote(terme)}/"
        pages_total += 1
        try:
            r = S.get(url, timeout=25)
        except Exception as e:
            print("Erreur", url, e)
            continue
        print(r.status_code, url)
        time.sleep(1)
        if r.status_code != 200:
            continue
        pages_ok += 1
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select('a[href*="/job/"]'):
            m = re.search(r"/job/([0-9a-f\-]{36})", a.get("href", ""))
            if not m:
                continue
            jid = m.group(1)
            if jid in seen or jid in vus_ce_run:
                continue
            titre = (a.get("title") or a.get_text(strip=True) or "").strip()
            low = titre.lower()
            if not any(k in low for k in MOTS_OK) or any(k in low for k in MOTS_KO):
                continue
            li = a.find_parent("li")
            infos = list(li.stripped_strings) if li else []
            age = infos[-1] if infos else ""
            if trop_vieille(age):
                continue
            details = " | ".join(i for i in infos if i != titre)
            lien = f"https://www.jobscout24.ch/en/job/{jid}/"
            vus_ce_run.add(jid)
            nouvelles.append((jid, f"🆕 {titre}\n{details}\n{lien}"))

if nouvelles:
    envoyer_par_blocs([t for _, t in nouvelles])
    seen.update(j for j, _ in nouvelles)

if os.environ.get("MANUAL") == "1":
    envoyer(f"✅ Le bot fonctionne !\nPages lues : {pages_ok}/{pages_total}\n"
            f"Nouvelles annonces : {len(nouvelles)}")

json.dump(sorted(seen), open(SEEN_FILE, "w"))
