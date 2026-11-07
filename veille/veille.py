import json, os, re, time, math, unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

TOKEN = os.environ["TG_TOKEN"].strip()
CHAT_ID = os.environ["TG_CHAT_ID"].strip()
API = f"https://api.telegram.org/bot{TOKEN}"
MANUAL = os.environ.get("MANUAL") == "1"

# ----------------------------------------------------------------------------
# RÉGLAGES PAR DÉFAUT (tu peux tout changer ensuite depuis le menu Telegram)
# ----------------------------------------------------------------------------
LIEUX_BASE = {  # ville: (latitude, longitude)
    "Delémont": (47.3649, 7.3444), "Porrentruy": (47.4156, 7.0752),
    "Saignelégier": (47.2559, 6.9967), "Neuchâtel": (46.9929, 6.9319),
    "La Chaux-de-Fonds": (47.1035, 6.8286), "Fribourg": (46.8065, 7.1620),
    "Bulle": (46.6195, 7.0567), "Genève": (46.2044, 6.1432),
    "Nyon": (46.3833, 6.2396), "Yverdon-les-Bains": (46.7785, 6.6410),
    "Vallorbe": (46.7090, 6.3753),
}
TERMES = ["operateur", "agent de production", "controleur qualite", "conditionnement",
          "assemblage", "montage", "salle blanche", "production"]
MOTS_OK = ["opérat", "operat", "agent", "contrôleur", "controleur", "conducteur",
           "production", "conditionnement", "assembl", "montage", "monteur",
           "salle blanche", "stérilis", "sterilis", "lavage", "finition",
           "fabrication", "qualit", "machine", "cnc", "manoeuvre", "manœuvre"]
MOTS_KO = ["formateur", "chef", "responsable", "ingénieur", "ingenieur", "directeur",
           "apprenti", "stagiaire", "polymécanicien", "polymecanicien", "programmeur",
           "mécanicien", "mecanicien", "commercial", "vendeur"]
JOURS_NORMAL = 14  # en passage normal, on ignore les annonces de plus de 14 jours

FREQS = [(10, "10 min"), (20, "20 min"), (30, "30 min"), (60, "1 h"), (180, "3 h"),
         (360, "6 h"), (1440, "1 jour"), (2880, "2 jours"), (4320, "3 jours"),
         (5760, "4 jours")]
RAYONS = [(0, "Ville seule"), (5, "5 km"), (10, "10 km"), (20, "20 km"), (30, "30 km (tout)")]

DEFAUT = {"intervalle_min": 30, "lieux": list(LIEUX_BASE), "rayon_km": 30,
          "actif": True, "dernier_passage": 0}

SETTINGS_FILE, SEEN_FILE, GEO_FILE = "settings.json", "seen.json", "geocache.json"


def charger(f, defaut):
    try:
        with open(f, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return defaut


def sauver(f, data):
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)


settings = {**DEFAUT, **charger(SETTINGS_FILE, {})}
seen = set(charger(SEEN_FILE, []))
geo = charger(GEO_FILE, {})


def norm(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


BASE_N = {norm(k): v for k, v in LIEUX_BASE.items()}

# ----------------------------------------------------------------------------
# TELEGRAM
# ----------------------------------------------------------------------------


def tg(method, **params):
    try:
        r = requests.post(f"{API}/{method}", data=params, timeout=25)
        j = r.json()
    except Exception as e:
        print("TG erreur", method, e)
        return {}
    if not j.get("ok"):
        print("TG", method, str(j)[:200])
    return j


def envoyer(texte, markup=None):
    p = {"chat_id": CHAT_ID, "text": texte, "disable_web_page_preview": "true"}
    if markup:
        p["reply_markup"] = json.dumps(markup)
    j = tg("sendMessage", **p)
    return j.get("ok", False)


def modifier(message_id, texte, markup):
    j = tg("editMessageText", chat_id=CHAT_ID, message_id=message_id, text=texte,
           reply_markup=json.dumps(markup))
    if j.get("ok") or "not modified" in str(j):
        return True
    return False


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


def btn(texte, data):
    return {"text": texte, "callback_data": data}


def lignes(boutons, n):
    return [boutons[i:i + n] for i in range(0, len(boutons), n)]


def libelle_freq(m):
    return dict(FREQS).get(m, f"{m} min")


def heure(ts):
    if not ts:
        return "jamais"
    return datetime.fromtimestamp(ts, ZoneInfo("Europe/Zurich")).strftime("%d/%m %H:%M")


def liste_villes():
    return list(LIEUX_BASE) + [v for v in settings["lieux"] if v not in LIEUX_BASE]


def vue(nom):
    s = settings
    if nom == "freq":
        txt = "⏱ Tous les combien de temps le bot doit-il chercher ?"
        rows = lignes([btn(("✅ " if s["intervalle_min"] == m else "") + l, f"f:{m}")
                       for m, l in FREQS], 3)
        rows.append([btn("⬅️ Retour", "m:main")])
        return txt, {"inline_keyboard": rows}
    if nom == "rayon":
        txt = ("📏 Zone autour de chaque ville.\n"
               "« Ville seule » = uniquement les annonces situées dans la ville.\n"
               "Maximum 30 km (limite du site).")
        rows = lignes([btn(("✅ " if s["rayon_km"] == k else "") + l, f"r:{k}")
                       for k, l in RAYONS], 3)
        rows.append([btn("⬅️ Retour", "m:main")])
        return txt, {"inline_keyboard": rows}
    if nom == "villes":
        txt = ("📍 Villes surveillées (touche pour activer / désactiver).\n"
               "Autre ville : écris /ville Martigny (seulement celle-là) "
               "ou /ajouter Martigny.")
        rows = lignes([btn(("✅ " if v in s["lieux"] else "▫️ ") + v, f"v:{v}")
                       for v in liste_villes()], 2)
        rows.append([btn("✅ Toutes", "v:*"), btn("⬅️ Retour", "m:main")])
        return txt, {"inline_keyboard": rows}
    # menu principal
    lieux = ("toutes mes villes" if set(s["lieux"]) == set(LIEUX_BASE)
             else ", ".join(s["lieux"]))
    r = s["rayon_km"]
    zone = "ville seule" if r == 0 else (f"rayon {r} km" if r < 30 else "30 km (par défaut)")
    etat = "🟢 actif" if s["actif"] else "⏸ en pause"
    txt = (f"⚙️ MENU DU BOT\n\n⏱ Fréquence : toutes les {libelle_freq(s['intervalle_min'])}\n"
           f"📍 Villes : {lieux}\n📏 Zone : {zone}\n{etat}\n"
           f"🕒 Dernier passage : {heure(s['dernier_passage'])}\n\n"
           "Tes choix sont appliqués au prochain passage du bot (5 min maximum).")
    rows = [
        [btn("⏱ Fréquence", "m:freq"), btn("📍 Villes", "m:villes")],
        [btn("📏 Rayon", "m:rayon"),
         btn("▶️ Reprendre" if not s["actif"] else "⏸ Pause", "a:1" if not s["actif"] else "a:0")],
        [btn("🔎 Chercher maintenant", "go")],
        [btn("📅 24 h", "rep:1"), btn("📅 3 jours", "rep:3"), btn("📅 7 jours", "rep:7")],
    ]
    return txt, {"inline_keyboard": rows}


# ----------------------------------------------------------------------------
# 1) LECTURE DE TES BOUTONS ET COMMANDES
# ----------------------------------------------------------------------------
forcer = MANUAL
rapport = None
vue_courante = "main"
interaction = False
cb_ids, dernier_msg_id = [], None


def appliquer_callback(data):
    global forcer, rapport, vue_courante
    if data.startswith("m:"):
        vue_courante = data[2:]
    elif data.startswith("f:"):
        settings["intervalle_min"] = int(data[2:])
        vue_courante = "main"
    elif data.startswith("r:"):
        settings["rayon_km"] = int(data[2:])
        vue_courante = "main"
    elif data.startswith("v:"):
        nom = data[2:]
        if nom == "*":
            settings["lieux"] = list(LIEUX_BASE)
        elif nom in settings["lieux"]:
            if len(settings["lieux"]) > 1:
                settings["lieux"].remove(nom)
        else:
            settings["lieux"].append(nom)
        vue_courante = "villes"
    elif data.startswith("a:"):
        settings["actif"] = data[2:] == "1"
        vue_courante = "main"
    elif data == "go":
        forcer = True
        vue_courante = "main"
    elif data.startswith("rep:"):
        rapport = max(rapport or 0, int(data[4:]))
        vue_courante = "main"


def appliquer_texte(t):
    global forcer, rapport, vue_courante
    low = t.strip().lower()
    vue_courante = "main"
    if low.startswith("/semaine"):
        rapport = max(rapport or 0, 7)
    elif re.match(r"/jours?\s+\d+", low):
        rapport = max(rapport or 0, min(int(re.findall(r"\d+", low)[0]), 60))
    elif low.startswith("/chercher"):
        forcer = True
    elif low.startswith("/pause"):
        settings["actif"] = False
    elif low.startswith("/reprendre"):
        settings["actif"] = True
    elif low.startswith("/ville "):
        settings["lieux"] = [t.strip()[7:].strip()]
    elif low.startswith("/ajouter "):
        v = t.strip()[9:].strip()
        if v and v not in settings["lieux"]:
            settings["lieux"].append(v)


res = tg("getUpdates").get("result", [])
dernier_update = None
for u in res:
    dernier_update = u["update_id"]
    cb = u.get("callback_query")
    msg = u.get("message")
    if cb:
        m = cb.get("message") or {}
        if str(m.get("chat", {}).get("id")) != CHAT_ID:
            continue
        interaction = True
        cb_ids.append(cb["id"])
        dernier_msg_id = m.get("message_id")
        try:
            appliquer_callback(cb.get("data", ""))
        except Exception as e:
            print("callback ignoré", e)
    elif msg and str(msg.get("chat", {}).get("id")) == CHAT_ID and msg.get("text"):
        interaction = True
        dernier_msg_id = None
        appliquer_texte(msg["text"])

sauver(SETTINGS_FILE, settings)
if dernier_update is not None:  # marque les messages comme lus
    tg("getUpdates", offset=dernier_update + 1)

if interaction:
    for cid in cb_ids:
        tg("answerCallbackQuery", callback_query_id=cid)
    txt, markup = vue(vue_courante)
    if not (dernier_msg_id and modifier(dernier_msg_id, txt, markup)):
        envoyer(txt, markup)

# ----------------------------------------------------------------------------
# 2) FAUT-IL CHERCHER MAINTENANT ?
# ----------------------------------------------------------------------------
maintenant = time.time()
du = settings["actif"] and (
    maintenant - settings["dernier_passage"] >= settings["intervalle_min"] * 60 - 150)
if not (forcer or rapport or du):
    print("Rien à faire ce coup-ci.")
    raise SystemExit(0)

# ----------------------------------------------------------------------------
# 3) RECHERCHE
# ----------------------------------------------------------------------------
S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "fr-CH,fr;q=0.9,en;q=0.5",
})
geo_requetes = 0


def coords(nom):
    global geo_requetes
    k = norm(nom)
    if not k:
        return None
    if k in BASE_N:
        return BASE_N[k]
    if k in geo:
        return geo[k]
    if geo_requetes >= 60:
        return None
    geo_requetes += 1
    try:
        r = requests.get("https://nominatim.openstreetmap.org/search",
                         params={"q": f"{nom}, Suisse", "format": "json", "limit": 1,
                                 "countrycodes": "ch"},
                         headers={"User-Agent": "veille-emploi-bot/1.0 (usage personnel)"},
                         timeout=20)
        j = r.json()
        time.sleep(1.1)
    except Exception as e:
        print("geocodage", nom, e)
        return None
    geo[k] = [float(j[0]["lat"]), float(j[0]["lon"])] if j else None
    return geo[k]


def distance_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((la2 - la1) / 2) ** 2
         + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2)
    return 6371 * 2 * math.asin(math.sqrt(h))


def passe_zone(ville, lieu):
    r = settings["rayon_km"]
    if r >= 30:
        return True, None
    if r == 0:
        return bool(lieu) and norm(ville) in norm(lieu), None
    a, b = coords(lieu), coords(ville)
    if not a or not b:
        return True, None  # lieu inconnu : on garde l'annonce
    d = distance_km(a, b)
    return d <= r, d


def lieu_annonce(infos):
    for i, t in enumerate(infos[:3]):
        if "," in t:
            fin = t.rsplit(",", 1)[-1].strip()
            return fin or (infos[i + 1] if i + 1 < len(infos) else "")
    return ""


def age_en_jours(age):
    m = re.fullmatch(r"(\d+)\+?\s*([a-z]+)", age.strip().lower())
    if not m:
        return 0
    return int(m.group(1)) * {"d": 1, "w": 7, "m": 30}.get(m.group(2), 0)


def slug(s):
    return quote(s.lower().replace(" ", "-"))


trouvees = {}  # id -> (âge en jours, texte)
pages_ok = pages_total = 0

for ville in settings["lieux"]:
    for terme in TERMES:
        url = f"https://www.jobscout24.ch/en/jobs-in-{slug(ville)}/{quote(terme)}/"
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
            if not m or m.group(1) in trouvees:
                continue
            jid = m.group(1)
            titre = (a.get("title") or a.get_text(strip=True) or "").strip()
            low = titre.lower()
            if not any(k in low for k in MOTS_OK) or any(k in low for k in MOTS_KO):
                continue
            li = a.find_parent("li")
            infos = [i for i in (li.stripped_strings if li else []) if i != titre]
            ok, d = passe_zone(ville, lieu_annonce(infos))
            if not ok:
                continue
            age = age_en_jours(infos[-1]) if infos else 0
            ligne2 = " | ".join(infos)
            if d is not None:
                ligne2 += f"\n📏 {d:.0f} km de {ville}"
            lien = f"https://www.jobscout24.ch/en/job/{jid}/"
            trouvees[jid] = (age, f"🆕 {titre}\n{ligne2}\n{lien}")

# ----------------------------------------------------------------------------
# 4) ENVOI
# ----------------------------------------------------------------------------
if rapport:
    choisies = sorted((a, j, t) for j, (a, t) in trouvees.items() if a <= rapport)
    envoyer(f"📅 Annonces des {rapport} derniers jours : {len(choisies)} trouvée(s)")
else:
    choisies = sorted((a, j, t) for j, (a, t) in trouvees.items()
                      if j not in seen and a <= JOURS_NORMAL)

if choisies:
    envoyer_par_blocs([t for _, _, t in choisies])
    seen.update(j for _, j, _ in choisies)
elif forcer and not rapport:
    envoyer("🔎 Aucune nouvelle annonce pour le moment.")

if forcer:
    envoyer(f"✅ Passage terminé : {pages_ok}/{pages_total} pages lues, "
            f"{len(choisies)} annonce(s) envoyée(s).")

settings["dernier_passage"] = time.time()
sauver(SETTINGS_FILE, settings)
sauver(SEEN_FILE, sorted(seen))
sauver(GEO_FILE, geo)
