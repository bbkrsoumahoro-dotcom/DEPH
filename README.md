# ENERGY SENTINEL CI

**Veiller. Vérifier. Expliquer. Valoriser.**

Dispositif de veille Hydrocarbures / Mines & Géologie / Énergie, centré sur la
Côte d'Ivoire (niveau 1), l'Afrique (niveau 2) et l'International (niveau 3).

Le dépôt contient deux briques qui communiquent uniquement par un fichier
JSON — pas de serveur, pas de base de données à héberger :

```
energy-sentinel-ci/
├── index.html                     ← le tableau de bord (site statique)
├── data/
│   ├── items.json                 ← informations collectées (généré)
│   └── sources.json               ← liste des sources (généré)
├── collector/
│   ├── veille_rpetrole.py         ← le collecteur Python
│   ├── requirements.txt
│   └── state/                     ← base SQLite persistée (générée)
├── .github/workflows/veille.yml   ← programme le collecteur automatiquement
└── README.md
```

**Comment ça marche :** `collector/veille_rpetrole.py` interroge les sources
(RSS + scraping générique), classe chaque information (priorité
rouge/orange/vert/bleu, fiabilité confirmé/à confirmer), l'enregistre dans une
base SQLite, puis exporte `data/items.json` et `data/sources.json`.
`index.html` charge ces deux fichiers au démarrage (`fetch`) et bascule
automatiquement :
- **Mode démo** (bandeau orange) si les fichiers sont absents/vides ou
  inaccessibles (aperçu local sans serveur, par exemple).
- **Mode réel** (pastille verte, avec l'heure de la dernière mise à jour) dès
  que `data/items.json` contient au moins une information.

Aucune information n'est donc jamais codée en dur dans la page : tout vient du
JSON généré par le collecteur.

## 1. Aperçu en local

```bash
cd energy-sentinel-ci
python3 -m http.server 8000
```

Puis ouvrez `http://localhost:8000`. (Ouvrir `index.html` directement en
double-cliquant ne fonctionnera pas pour le chargement des données réelles :
les navigateurs bloquent `fetch()` sur les fichiers `file://` — un simple
serveur local comme ci-dessus suffit.)

## 2. Lancer le collecteur en local

```bash
cd energy-sentinel-ci
pip install -r collector/requirements.txt

# Un seul cycle de collecte + export JSON (idéal pour tester)
python3 collector/veille_rpetrole.py --once

# Uniquement régénérer data/items.json et data/sources.json
# à partir de la base existante, sans relancer une collecte
python3 collector/veille_rpetrole.py --export

# Statistiques rapides
python3 collector/veille_rpetrole.py --stats

# Synthèse texte du jour (gabarit "titres gras / chapô italique")
python3 collector/veille_rpetrole.py --synthese

# Boucle continue (par défaut toutes les 15 min, CTRL+C pour arrêter)
python3 collector/veille_rpetrole.py
```

Variables d'environnement utiles (aucune ne doit être écrite en dur dans le
code, y compris pour un usage local) :

| Variable | Rôle | Défaut |
|---|---|---|
| `ENERGY_SENTINEL_DATA_DIR` | Dossier de travail (base SQLite, rapports, synthèses) | `~/EnergySentinelCI` |
| `ENERGY_SENTINEL_EXPORT_DIR` | Dossier où écrire `items.json` / `sources.json` | `data` (relatif au dossier courant) |
| `ENERGY_SENTINEL_MAX_EXPORT` | Nombre max d'informations exportées vers le site | `300` |
| `ENERGY_SENTINEL_INTERVAL` | Intervalle entre deux cycles en mode boucle continue (secondes) | `900` |
| `ENERGY_SENTINEL_TELEGRAM_TOKEN` / `ENERGY_SENTINEL_TELEGRAM_CHAT_ID` | Notifications Telegram (optionnel) | vide = désactivé |

## 3. Héberger sur GitHub (site + automatisation)

### a. Créer le dépôt et pousser le code

```bash
cd energy-sentinel-ci
git init
git add .
git commit -m "Initial commit — ENERGY SENTINEL CI"
git branch -M main
git remote add origin https://github.com/<votre-compte>/<votre-repo>.git
git push -u origin main
```

### b. Activer GitHub Pages

`Settings` → `Pages` → *Build and deployment* → **Deploy from a branch** →
branche `main`, dossier `/ (root)` → **Save**.
Le site sera servi à `https://<votre-compte>.github.io/<votre-repo>/`
(`index.html` étant à la racine, tout fonctionne tel quel).

### c. Autoriser les Actions à publier les données

`Settings` → `Actions` → `General` → *Workflow permissions* → cocher
**Read and write permissions**, puis **Save**.
Sans ça, `.github/workflows/veille.yml` ne pourra pas committer
`data/items.json` mis à jour.

### d. (Optionnel) Notifications Telegram

`Settings` → `Secrets and variables` → `Actions` → **New repository secret** :
- `ENERGY_SENTINEL_TELEGRAM_TOKEN`
- `ENERGY_SENTINEL_TELEGRAM_CHAT_ID`

Le workflow les passe automatiquement au script s'ils existent ; sinon le
script reste silencieux sur ce point (rien à faire pour désactiver).

### e. Programmation automatique du collecteur

`.github/workflows/veille.yml` est déjà en place :
- tourne toutes les **30 minutes** (`cron: '*/30 * * * *'` — modifiable),
- peut aussi être lancé manuellement depuis l'onglet **Actions** du dépôt
  (bouton *Run workflow*),
- à chaque exécution : lance un cycle de collecte, régénère
  `data/items.json` et `data/sources.json`, et republie automatiquement ces
  fichiers (+ la base SQLite persistée dans `collector/state/`) sur `main`
  s'il y a du nouveau.

GitHub Pages republie le site automatiquement à chaque push sur `main` — donc
dès qu'un cycle de collecte trouve du nouveau, le tableau de bord en ligne se
met à jour sans aucune action manuelle.

> Le cron GitHub Actions n'est pas garanti à la minute près sur le plan
> gratuit (délai possible en cas de forte charge sur l'infrastructure
> GitHub) — c'est normal et sans impact sur le fonctionnement.

## 4. Étapes suivantes à valider avec vous avant mise en production

- **Flux RSS à confirmer** : plusieurs sources dans
  `collector/veille_rpetrole.py` (`SOURCES`) sont en `type: "web"` faute de
  flux RSS officiel identifié — elles sont scrapées avec un extracteur
  générique (liens de la page d'accueil), donc moins fiable et à affiner
  site par site.
- **Classification par mots-clés** (`MOTS_ROUGE` / `MOTS_ORANGE` /
  `MOTS_BLEU`) est volontairement simple et transparente — à ajuster avec
  l'usage plutôt que de la complexifier à l'aveugle.
- **Fiabilité "confirmé"** n'est aujourd'hui déterminée que par la nature
  officielle de la source (`SOURCES_OFFICIELLES`) ; le recoupement
  multi-sources est prévu en phase suivante.
- **Synthèses, vidéos, rapports automatiques** : modules volontairement
  laissés en placeholder dans `index.html` (pages *Synthèses*, *Vidéos*,
  *Rapports*) — à construire une fois le collecteur validé en conditions
  réelles, pour ne pas partir dans plusieurs directions à la fois.
- **Sécurité** : aucun identifiant n'est écrit en dur ; tout passe par des
  secrets GitHub Actions ou des variables d'environnement locales.

## 5. Format des fichiers générés

`data/items.json`
```json
{
  "generated_at": "2026-08-16T17:28:26",
  "items": [
    {
      "id": 12,
      "titre": "…",
      "categorie": "hydrocarbures",
      "pays": "Côte d'Ivoire",
      "zone": "ci",
      "priorite": "orange",
      "fiabilite": "a_confirmer",
      "source": "…",
      "url": "https://…",
      "resume": "…",
      "date_publication": "…",
      "heure_collecte": "2026-08-16T17:20:03"
    }
  ]
}
```

`data/sources.json`
```json
{
  "generated_at": "2026-08-16T17:28:26",
  "sources": {
    "hydrocarbures": [
      {"nom": "…", "url": "…", "type": "rss", "zone": "ci", "statut": "…"}
    ]
  }
}
```
