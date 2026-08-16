#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ENERGY SENTINEL CI — Collecteur v1
Veiller. Vérifier. Expliquer. Valoriser.

Évolution du script "veille_renseignement.py" :
- Sources recentrées sur Hydrocarbures / Mines & Géologie / Énergie
  (Côte d'Ivoire > Afrique > International), au lieu du périmètre
  sécurité/renseignement général du script d'origine.
- Suppression complète du module de recherche d'images/vidéos via
  scraping Google Images, Bing Images, YouTube, Facebook, X — ce
  module était fragile et contraire à l'exigence de contenu
  "légalement utilisable" (voir le prompt maître du projet).
- Aucun identifiant en dur : tout passe par des variables
  d'environnement (voir la section CONFIG ci-dessous).
- Ajout du système de priorité ROUGE/ORANGE/VERT/BLEU et du statut
  de fiabilité (confirmé / à confirmer) demandés dans le cahier des
  charges.
- Ajout d'une fonction de génération de synthèse textuelle inspirée
  du gabarit "Synthèse de presse" fourni (sections CI / Continent /
  International, titres en gras, chapô en italique, paragraphe de
  résumé).
- Ajout d'un export JSON (data/items.json + data/sources.json) qui
  alimente directement le tableau de bord statique index.html. Cet
  export tourne après chaque cycle de collecte et peut aussi être
  déclenché seul avec --export. Voir .github/workflows/veille.yml
  pour l'automatisation via GitHub Actions.

IMPORTANT :
- Les URL marquées comme "site à confirmer" dans SOURCES n'ont pas
  de flux RSS officiel identifié : elles sont scrapées via la page
  d'actualités du site avec un extracteur générique. Ce n'est pas
  aussi fiable qu'un vrai flux RSS et devra être affiné site par
  site (chaque site a sa propre structure HTML).
- Ce script ne doit jamais inventer ou publier une information non
  vérifiée comme un fait confirmé : toute information à source
  unique est marquée fiabilite="a_confirmer".
"""

import os
import re
import sys
import json
import time
import sqlite3
import hashlib
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

# ============================================================
# CONFIG — tout via variables d'environnement, rien en dur
# ============================================================
TELEGRAM_TOKEN = os.environ.get("ENERGY_SENTINEL_TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("ENERGY_SENTINEL_TELEGRAM_CHAT_ID", "")
DOWNLOAD_DIR = os.environ.get("ENERGY_SENTINEL_DATA_DIR", os.path.join(os.path.expanduser("~"), "EnergySentinelCI"))
INTERVALLE_SECONDES = int(os.environ.get("ENERGY_SENTINEL_INTERVAL", "900"))  # 15 min par défaut
REQUEST_TIMEOUT = 15

# Dossier lu par index.html (data/items.json + data/sources.json), séparé du
# dossier de travail ci-dessus. Par défaut "data/" relatif au dossier courant
# : en local, lancez le script depuis la racine du dépôt cloné pour que le
# JSON tombe directement à côté de index.html. Dans GitHub Actions, le
# workflow se place déjà à la racine du dépôt, donc "data" fonctionne tel quel.
EXPORT_DIR = os.environ.get("ENERGY_SENTINEL_EXPORT_DIR", "data")
MAX_ITEMS_EXPORTES = int(os.environ.get("ENERGY_SENTINEL_MAX_EXPORT", "300"))

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(os.path.join(DOWNLOAD_DIR, "Rapports"), exist_ok=True)
os.makedirs(os.path.join(DOWNLOAD_DIR, "Syntheses"), exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)

DB_PATH = os.path.join(DOWNLOAD_DIR, "energy_sentinel.db")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

# ============================================================
# NOTIFICATIONS TELEGRAM (optionnel — silencieux si non configuré)
# ============================================================

def telegram_actif():
    return bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)

def send_telegram(message):
    if not telegram_actif():
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message[:4000], "parse_mode": "HTML",
                 "disable_web_page_preview": True}
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print(f"  [!] Telegram indisponible : {e}")

# ============================================================
# SOURCES — Hydrocarbures / Mines & Géologie / Énergie
# CI = niveau 1 (toujours prioritaire) / Afrique = niveau 2 / International = niveau 3
# type "rss" = flux confirmé ; type "web" = page à scraper (structure à affiner par site)
# ============================================================

SOURCES = {
    "hydrocarbures": [
        {"nom": "Ministère des Mines, du Pétrole et de l'Énergie (CI)", "url": "https://www.energie.gouv.ci/actualites", "type": "web", "zone": "ci"},
        {"nom": "PETROCI Holding", "url": "https://www.petroci.ci/", "type": "web", "zone": "ci"},
        {"nom": "Société Ivoirienne de Raffinage (SIR)", "url": "https://sir.ci/", "type": "web", "zone": "ci"},
        {"nom": "Agence Ecofin — Hydrocarbures", "url": "https://www.agenceecofin.com/hydrocarbures/feed", "type": "rss", "zone": "afrique"},
        {"nom": "Jeune Afrique — Économie", "url": "https://www.jeuneafrique.com/rubriques/economie/feed/", "type": "rss", "zone": "afrique"},
        {"nom": "Reuters — Énergie (international)", "url": "https://www.reuters.com/business/energy/", "type": "web", "zone": "international"},
    ],
    "mines": [
        {"nom": "Ministère des Mines, du Pétrole et de l'Énergie (CI) — volet Mines", "url": "https://www.energie.gouv.ci/actualites", "type": "web", "zone": "ci"},
        {"nom": "SODEMI", "url": "https://sodemi.ci/", "type": "web", "zone": "ci"},
        {"nom": "Agence Ecofin — Matières premières", "url": "https://www.agenceecofin.com/matieres-premieres/feed", "type": "rss", "zone": "afrique"},
        {"nom": "Banque Africaine de Développement — Actualités", "url": "https://www.afdb.org/fr/news-and-events", "type": "web", "zone": "afrique"},
    ],
    "energie": [
        {"nom": "CI-ENERGIES", "url": "https://www.cinergies.ci/", "type": "web", "zone": "ci"},
        {"nom": "Ministère des Mines, du Pétrole et de l'Énergie (CI) — volet Énergie", "url": "https://www.energie.gouv.ci/actualites", "type": "web", "zone": "ci"},
        {"nom": "Agence Ecofin — Énergies", "url": "https://www.agenceecofin.com/energies/feed", "type": "rss", "zone": "afrique"},
    ],
    "institutionnel": [
        {"nom": "Présidence de la République de Côte d'Ivoire", "url": "https://www.presidence.ci/feed/", "type": "rss", "zone": "ci"},
        {"nom": "Portail officiel du Gouvernement de Côte d'Ivoire", "url": "https://www.gouv.ci", "type": "web", "zone": "ci"},
    ],
}

# ============================================================
# MOTS-CLÉS SENSIBLES — recherche approfondie ciblée énergie/mines
# ============================================================

MOTS_CLES_SENSIBLES = [
    # Côte d'Ivoire
    "Côte d'Ivoire pétrole découverte", "Côte d'Ivoire bloc pétrolier", "Côte d'Ivoire forage",
    "Côte d'Ivoire gaz naturel", "Côte d'Ivoire raffinage SIR", "PETROCI accord",
    "Côte d'Ivoire mine or", "Côte d'Ivoire permis minier", "Côte d'Ivoire bauxite",
    "Côte d'Ivoire manganèse", "Côte d'Ivoire nickel", "Côte d'Ivoire lithium",
    "CI-ENERGIES centrale", "Côte d'Ivoire électricité", "Côte d'Ivoire énergie solaire",
    "Côte d'Ivoire hub énergétique", "Ministère Mines Pétrole Énergie Côte d'Ivoire",
    "Côte d'Ivoire investissement énergie", "Côte d'Ivoire prix carburant",
    # Afrique
    "Afrique pétrole découverte", "Afrique gisement gaz", "OPEP Afrique quota",
    "Afrique mine cuivre", "Afrique minéraux critiques", "APPO sommet",
    "Afrique électrification", "Afrique énergie renouvelable projet",
    "BAD financement énergie", "Afrique transition énergétique",
    # International
    "OPEP décision production", "prix baril pétrole", "prix gaz naturel marché",
    "compagnie pétrolière contrat Afrique", "minéraux critiques marché mondial",
    "transition énergétique mondiale", "énergie renouvelable investissement mondial",
]

# ============================================================
# BASE DE DONNÉES
# ============================================================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS informations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titre TEXT,
        date_publication TEXT,
        categorie TEXT,          -- hydrocarbures / mines / energie
        pays TEXT,
        zone TEXT,               -- ci / afrique / international
        resume TEXT,
        contexte TEXT,
        importance TEXT,
        source TEXT,
        url TEXT UNIQUE,
        heure_collecte TEXT,
        fiabilite TEXT,          -- confirme / a_confirmer
        priorite TEXT,           -- rouge / orange / vert / bleu
        traite INTEGER DEFAULT 0
    )''')
    conn.commit()
    return conn

def url_deja_traitee(conn, url):
    c = conn.cursor()
    c.execute("SELECT 1 FROM informations WHERE url=?", (url,))
    return c.fetchone() is not None

def enregistrer_information(conn, item):
    c = conn.cursor()
    try:
        c.execute('''INSERT INTO informations
            (titre, date_publication, categorie, pays, zone, resume, contexte, importance,
             source, url, heure_collecte, fiabilite, priorite)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (item["titre"], item.get("date_publication", ""), item["categorie"], item["pays"],
             item["zone"], item.get("resume", ""), item.get("contexte", ""), item.get("importance", ""),
             item["source"], item["url"], datetime.now().isoformat(timespec="seconds"),
             item["fiabilite"], item["priorite"]))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # doublon déjà présent (URL unique)

# ============================================================
# CLASSIFICATION — mots-clés => priorité (ROUGE/ORANGE/VERT/BLEU)
# Règle volontairement simple et transparente : à ajuster avec vous
# au fil de l'usage plutôt que de complexifier à l'aveugle.
# ============================================================

MOTS_ROUGE = ["accident", "explosion", "incendie", "fuite", "attentat", "sabotage",
              "grève générale", "arrêt de production", "catastrophe", "urgence"]
MOTS_ORANGE = ["découverte", "permis", "contrat", "accord", "investissement", "partenariat",
               "nomination", "réforme", "hausse des prix", "privatisation", "sommet"]
MOTS_BLEU = ["le saviez-vous", "histoire de", "dossier", "explication", "comprendre",
             "qu'est-ce que", "pédagogie"]

def classifier_priorite(titre, resume=""):
    texte = (titre + " " + resume).lower()
    if any(m in texte for m in MOTS_ROUGE):
        return "rouge"
    if any(m in texte for m in MOTS_BLEU):
        return "bleu"
    if any(m in texte for m in MOTS_ORANGE):
        return "orange"
    return "vert"

def determiner_fiabilite(source_officielle):
    """Une source de niveau institutionnel/officiel confirmé (ministère, société
    d'État) est considérée fiable dès la première collecte. Toute autre source
    reste 'à confirmer' tant qu'aucune deuxième source indépendante ne
    corrobore l'information — la corrélation multi-source reste à construire
    (phase suivante) : pour l'instant, seule la nature de la source est prise
    en compte."""
    return "confirme" if source_officielle else "a_confirmer"

SOURCES_OFFICIELLES = {
    "Ministère des Mines, du Pétrole et de l'Énergie (CI)",
    "Ministère des Mines, du Pétrole et de l'Énergie (CI) — volet Mines",
    "Ministère des Mines, du Pétrole et de l'Énergie (CI) — volet Énergie",
    "PETROCI Holding", "Société Ivoirienne de Raffinage (SIR)", "SODEMI",
    "CI-ENERGIES", "Présidence de la République de Côte d'Ivoire",
    "Portail officiel du Gouvernement de Côte d'Ivoire",
}

# ============================================================
# COLLECTE RSS
# ============================================================

def collecter_rss(source, categorie):
    resultats = []
    try:
        if HAS_FEEDPARSER:
            flux = feedparser.parse(source["url"])
            entries = flux.entries
        else:
            r = requests.get(source["url"], headers=HEADERS, timeout=REQUEST_TIMEOUT)
            soup = BeautifulSoup(r.content, "xml")
            entries = []
            for item in soup.find_all("item"):
                entries.append({
                    "title": item.title.text if item.title else "",
                    "link": item.link.text if item.link else "",
                    "summary": item.description.text if item.description else "",
                    "published": item.pubDate.text if item.pubDate else "",
                })
        for e in entries[:20]:
            titre = (e.get("title") or "").strip()
            url = (e.get("link") or "").strip()
            resume = re.sub("<[^<]+?>", "", e.get("summary", "") or "")[:400]
            if titre and url:
                resultats.append({"titre": titre, "url": url, "resume": resume,
                                   "date_publication": e.get("published", "")})
        print(f"  📡 RSS OK — {source['nom']} : {len(resultats)} entrées")
    except Exception as ex:
        print(f"  [!] RSS indisponible — {source['nom']} : {ex}")
    return resultats

# ============================================================
# COLLECTE WEB GÉNÉRIQUE (pour les sites sans flux RSS confirmé)
# Heuristique simple : liens de la page d'accueil/actualités dont le
# texte est assez long pour être un titre d'article. À remplacer par
# un extracteur dédié par site dès que possible (structure HTML
# propre à chaque site institutionnel).
# ============================================================

def collecter_web_generique(source, categorie, max_items=15):
    resultats = []
    try:
        r = requests.get(source["url"], headers=HEADERS, timeout=REQUEST_TIMEOUT)
        soup = BeautifulSoup(r.content, "html.parser")
        vus = set()
        for a in soup.find_all("a", href=True):
            texte = a.get_text(strip=True)
            href = a["href"]
            if len(texte) < 25 or len(texte) > 220:
                continue
            url_complete = urljoin(source["url"], href)
            if url_complete in vus:
                continue
            vus.add(url_complete)
            resultats.append({"titre": texte, "url": url_complete, "resume": "",
                               "date_publication": ""})
            if len(resultats) >= max_items:
                break
        print(f"  🌐 Web OK — {source['nom']} : {len(resultats)} liens candidats (à valider manuellement)")
    except Exception as ex:
        print(f"  [!] Site indisponible — {source['nom']} : {ex}")
    return resultats

# ============================================================
# CYCLE DE VEILLE
# ============================================================

def cycle_veille(conn):
    nouveaux = []
    for categorie, sources in SOURCES.items():
        for source in sources:
            if source["type"] == "rss":
                entries = collecter_rss(source, categorie)
            else:
                entries = collecter_web_generique(source, categorie)

            for e in entries:
                if url_deja_traitee(conn, e["url"]):
                    continue
                priorite = classifier_priorite(e["titre"], e.get("resume", ""))
                fiabilite = determiner_fiabilite(source["nom"] in SOURCES_OFFICIELLES)
                pays = "Côte d'Ivoire" if source["zone"] == "ci" else ("Afrique" if source["zone"] == "afrique" else "International")
                item = {
                    "titre": e["titre"],
                    "date_publication": e.get("date_publication", ""),
                    "categorie": categorie,
                    "pays": pays,
                    "zone": source["zone"],
                    "resume": e.get("resume", ""),
                    "contexte": "",
                    "importance": "",
                    "source": source["nom"],
                    "url": e["url"],
                    "fiabilite": fiabilite,
                    "priorite": priorite,
                }
                if enregistrer_information(conn, item):
                    nouveaux.append(item)
            time.sleep(1)  # courtoisie envers les sites scrapés
    return nouveaux

# ============================================================
# GÉNÉRATION DE SYNTHÈSE — style calqué sur le gabarit fourni
# (titres en gras, chapô en italique, paragraphe de résumé,
# sections Côte d'Ivoire / Continent africain / International)
# ============================================================

MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]

def date_francaise(d=None):
    d = d or datetime.now()
    return f"{d.day} {MOIS_FR[d.month - 1]} {d.year}"

def generer_synthese(conn, date_str=None):
    date_str = date_str or date_francaise()
    c = conn.cursor()

    def items_zone(zone):
        c.execute('''SELECT titre, resume, source, fiabilite FROM informations
                     WHERE zone=? AND date(heure_collecte)=date('now')
                     ORDER BY id DESC''', (zone,))
        return c.fetchall()

    sections = [("ci", "EN CÔTE D'IVOIRE"), ("afrique", "SUR LE CONTINENT AFRICAIN"),
                ("international", "AU PLAN INTERNATIONAL")]

    texte = f"*SYNTHÈSE ÉNERGIE, MINES & HYDROCARBURES DU {date_str.upper()}*\n\n"
    for zone_key, titre_section in sections:
        rows = items_zone(zone_key)
        texte += f"*{titre_section}*\n\n"
        if not rows:
            texte += "Aucune information collectée dans cette rubrique aujourd'hui.\n\n"
            continue
        for titre, resume, source, fiabilite in rows:
            suffixe = "" if fiabilite == "confirme" else " [À CONFIRMER]"
            texte += f"*{titre}*{suffixe}.\n\n"
            corps = resume.strip() if resume else "Résumé à compléter après vérification de la source."
            texte += f"{corps} (Source : {source})\n\n"

    texte += f"Telle est la synthèse énergie, mines et hydrocarbures du {date_str}."

    chemin = os.path.join(DOWNLOAD_DIR, "Syntheses", f"synthese_{datetime.now().strftime('%Y%m%d')}.txt")
    with open(chemin, "w", encoding="utf-8") as f:
        f.write(texte)
    return texte, chemin

# ============================================================
# RAPPORT STATISTIQUE
# ============================================================

def generer_rapport(conn):
    c = conn.cursor()
    total = c.execute("SELECT COUNT(*) FROM informations").fetchone()[0]
    aujourdhui = c.execute("SELECT COUNT(*) FROM informations WHERE date(heure_collecte)=date('now')").fetchone()[0]
    rouges = c.execute("SELECT COUNT(*) FROM informations WHERE priorite='rouge'").fetchone()[0]
    a_confirmer = c.execute("SELECT COUNT(*) FROM informations WHERE fiabilite='a_confirmer'").fetchone()[0]
    par_categorie = c.execute("SELECT categorie, COUNT(*) FROM informations GROUP BY categorie").fetchall()

    rapport = [
        "📊 RAPPORT ENERGY SENTINEL CI",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        "",
        f"📰 Total informations : {total}",
        f"📅 Aujourd'hui : {aujourdhui}",
        f"🔴 Priorité rouge : {rouges}",
        f"△ À confirmer : {a_confirmer}",
        "",
        "Par secteur :",
    ]
    for cat, nb in par_categorie:
        rapport.append(f"   • {cat} : {nb}")
    return "\n".join(rapport)

# ============================================================
# EXPORT JSON — alimente index.html (data/items.json + data/sources.json)
# C'est le pont entre ce collecteur et le tableau de bord statique.
# À appeler après chaque cycle de collecte (voir cycle_veille) et
# manuellement via --export.
# ============================================================

def exporter_items_json(conn):
    c = conn.cursor()
    c.execute('''SELECT id, titre, date_publication, categorie, pays, zone, resume,
                        source, url, heure_collecte, fiabilite, priorite
                 FROM informations
                 ORDER BY heure_collecte DESC
                 LIMIT ?''', (MAX_ITEMS_EXPORTES,))
    rows = c.fetchall()
    items = []
    for (id_, titre, date_publication, categorie, pays, zone, resume,
         source, url, heure_collecte, fiabilite, priorite) in rows:
        items.append({
            "id": id_,
            "titre": titre,
            "categorie": categorie,
            "pays": pays,
            "zone": zone,
            "priorite": priorite,
            "fiabilite": fiabilite,
            "source": source,
            "url": url,
            "resume": resume or "",
            "date_publication": date_publication or "",
            "heure_collecte": heure_collecte,
        })
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "items": items,
    }
    chemin = os.path.join(EXPORT_DIR, "items.json")
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return chemin

def exporter_sources_json():
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sources": {
            categorie: [
                {
                    "nom": s["nom"],
                    "url": s["url"],
                    "type": s["type"],
                    "zone": s["zone"],
                    "statut": "Flux RSS déclaré" if s["type"] == "rss" else "Scraping générique (à affiner par site)",
                }
                for s in sources
            ]
            for categorie, sources in SOURCES.items()
        },
    }
    chemin = os.path.join(EXPORT_DIR, "sources.json")
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return chemin

def exporter_json(conn):
    chemin_items = exporter_items_json(conn)
    chemin_sources = exporter_sources_json()
    print(f"  📤 Export JSON : {chemin_items}, {chemin_sources}")
    return chemin_items, chemin_sources

# ============================================================
# CLI
# ============================================================

def scan_unique():
    conn = init_db()
    print("Scan unique Energy Sentinel CI...")
    nouveaux = cycle_veille(conn)
    print(f"\n✅ Terminé : {len(nouveaux)} nouvelles informations collectées")
    exporter_json(conn)
    rapport = generer_rapport(conn)
    print(rapport)
    send_telegram(f"✅ Scan Energy Sentinel CI terminé\n{rapport}")
    conn.close()

def exporter_json_cli():
    conn = init_db()
    chemin_items, chemin_sources = exporter_json(conn)
    print(f"✅ Export terminé :\n  - {chemin_items}\n  - {chemin_sources}")
    conn.close()

def afficher_stats():
    conn = init_db()
    print(generer_rapport(conn))
    conn.close()

def generer_synthese_cli():
    conn = init_db()
    texte, chemin = generer_synthese(conn)
    print(texte)
    print(f"\n📄 Synthèse enregistrée : {chemin}")
    conn.close()

def boucle_principale():
    print("=" * 70)
    print("ENERGY SENTINEL CI — Collecteur")
    print(f"Démarrage : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"Secteurs : {', '.join(SOURCES.keys())}")
    print(f"Intervalle : {INTERVALLE_SECONDES}s")
    print(f"Dossier de données : {DOWNLOAD_DIR}")
    print(f"Telegram : {'connecté' if telegram_actif() else 'non configuré'}")
    print("=" * 70)

    conn = init_db()
    send_telegram(f"🚀 <b>ENERGY SENTINEL CI — Collecteur démarré</b>\nIntervalle : {INTERVALLE_SECONDES}s")

    cycle = 0
    try:
        while True:
            cycle += 1
            print(f"\n{'=' * 60}\nCYCLE {cycle} — {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n{'=' * 60}")
            nouveaux = cycle_veille(conn)
            print(f"→ {len(nouveaux)} nouvelles informations")
            exporter_json(conn)

            if cycle % 10 == 0:
                rapport = generer_rapport(conn)
                chemin = os.path.join(DOWNLOAD_DIR, "Rapports", f"rapport_{datetime.now().strftime('%Y%m%d_%H%M')}.txt")
                with open(chemin, "w", encoding="utf-8") as f:
                    f.write(rapport)
                print(f"📄 Rapport sauvegardé : {chemin}")

            print(f"\n⏳ Prochain scan dans {INTERVALLE_SECONDES}s (CTRL+C pour arrêter)")
            time.sleep(INTERVALLE_SECONDES)
    except KeyboardInterrupt:
        print("\n⏹️ Veille arrêtée")
        send_telegram(f"⏹️ Veille arrêtée après {cycle} cycles\n{generer_rapport(conn)}")
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ("--once", "-1"):
            scan_unique()
        elif arg in ("--stats", "-s"):
            afficher_stats()
        elif arg in ("--synthese", "-y"):
            generer_synthese_cli()
        elif arg in ("--export", "-e"):
            exporter_json_cli()
        else:
            print("Usage : python veille_rpetrole.py [--once|--stats|--synthese|--export]")
    else:
        boucle_principale()