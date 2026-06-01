# Brussels Pedestrian Network

Carte interactive des flux piétons simulés à Bruxelles, construite à partir des données OpenStreetMap.

**[Voir la carte](https://pasloin.github.io/Brussels-Pedestrian-Network/)**  
**[Statistiques](https://pasloin.github.io/Brussels-Pedestrian-Network/stats.html)**

---

## Principe

Le pipeline simule des trajets piétons entre des paires origine-destination échantillonnées depuis les adresses OSM. Les chemins les plus courts sont calculés sur le graphe de voirie via Dijkstra (igraph), puis les passages sont agrégés par arête pour produire des couches de flux.

Le résultat permet d'identifier :
- les **corridors piétons les plus fréquentés** (flux sur footway/pedestrian/path)
- les **routes où les piétons sont forcés de marcher sur la chaussée** (flux sur road, sans infrastructure dédiée à proximité)
- les **pistes cyclables empruntées faute d'alternative** (flux sur cycleway sans `foot=yes`)
- les **lacunes du réseau** : trottoirs mappés d'un seul côté, absence de tags sidewalk

---

## Couches PMTiles

| Couche | Description |
|--------|-------------|
| `highways` | Réseau piéton de base (footway, pedestrian, path, steps, cycleway…) |
| `flow_edges` | Flux simulés — propriétés : `infra_type`, `flow_pct`, `highway` |
| `street_scores` | Score de marchabilité par rue (0–1), pénalisé selon les tags sidewalk |
| `sidewalk_gaps` | Routes avec un trottoir mappé d'un seul côté (analyse spatiale) |
| `sidewalk_roads` | Tags sidewalk sur routes (QA cartographique) |

> **Note** : les couches `forced_segments` et `forced_cycleway` ont été fusionnées dans `flow_edges` via la propriété `highway=*`. Leurs GeoJSON complets sont toujours produits comme artifacts CI.

### Propriétés de `flow_edges`

| Propriété | Valeurs | Description |
|-----------|---------|-------------|
| `infra_type` | `pedestrian`, `road`, `cycleway_foot_yes`, `cycleway_no_foot` | Type d'infrastructure |
| `flow_pct` | 0–100 | Flux relatif (% du max global) |
| `highway` | `footway`, `primary`, `residential`… | Tag OSM d'origine |

---

## Pipeline de build

```
brussels.osm.pbf
    │
    ├─ osmium tags-filter → highways_ped.osm.pbf → highways.geojson  (visual layer)
    ├─ osmium tags-filter → roads_sidewalk.osm.pbf → sidewalk_roads_raw.geojson
    ├─ osmium tags-filter → routing_raw.osm.pbf → routing_raw.osm
    └─ osmium tags-filter → addresses_raw.osm.pbf → addresses.geojson
              │
    scripts/main.py
              │
    ├─ clean_osm.py       — split ways aux barrières bloquées
    ├─ build_graph.py     — OSMnx → igraph, index sidewalk
    ├─ sample_od.py       — échantillonnage OD géographique + snapping par arête
    ├─ routing.py         — Dijkstra groupé par source, accumulation flux
    ├─ export.py          — flow_edges / forced_* / street_scores / graph.json
    ├─ sidewalk_gap.py    — détection spatiale trottoirs unilatéraux
    └─ export_sidewalk_roads.py — QA tags sidewalk
              │
    tippecanoe → pedestrian.pmtiles
              │
    GitHub Pages
```

---

## Modules Python (`scripts/`)

| Fichier | Rôle |
|---------|------|
| `config.py` | Tous les paramètres (lus depuis variables d'env) |
| `clean_osm.py` | Nettoyage OSM XML, split aux barrières |
| `build_graph.py` | Construction graphe igraph, index sidewalk |
| `sample_od.py` | Échantillonnage OD depuis adresses, snapping |
| `routing.py` | Génération paires OD, Dijkstra, accumulation |
| `export.py` | Export GeoJSON + graph.json + stats.json |
| `sidewalk_gap.py` | Détection lacunes trottoirs (analyse spatiale) |
| `export_sidewalk_roads.py` | Export tags sidewalk sur routes (QA) |
| `debug_snap.py` | Diagnostic snapping adresses (usage local) |

---

## Paramètres configurables

Tous les paramètres sont des variables d'environnement définies dans `.github/workflows/build.yml` :

### Échantillonnage OD
| Variable | Défaut | Description |
|----------|--------|-------------|
| `OD_SAMPLE_INTERVAL_M` | 100 | Intervalle géographique entre points OD (m) |
| `MIN_OD_DISTANCE_M` | 900 | Distance min entre paires OD |
| `MAX_OD_DISTANCE_KM` | 1 | Distance max entre paires OD |
| `MAX_OD_PAIRS` | 900 000 | Cap sur le nombre de paires |

### Flux et export
| Variable | Défaut | Description |
|----------|--------|-------------|
| `TOP_RANK_PCT` | 15 | Top N% de flux → artifacts forced_* |
| `MIN_FLOW_THRESHOLD` | 5 | Seuil min pour inclure une arête dans flow_edges PMTiles |

### Marchabilité
| Variable | Défaut | Description |
|----------|--------|-------------|
| `WALK_SCORE_RADIUS_M` | 1000 | Longueur début/fin de trajet comptabilisée |
| `SIDEWALK_PENALTY_NONE` | 0.3 | Multiplicateur si `sidewalk=no` |
| `SIDEWALK_PENALTY_PARTIAL` | 0.6 | Multiplicateur si sidewalk un seul côté |
| `SIDEWALK_PENALTY_UNKNOWN` | 0.5 | Multiplicateur si aucun tag sidewalk |

### Détection de lacunes
| Variable | Défaut | Description |
|----------|--------|-------------|
| `SIDEWALK_GAP_OFFSET_M` | 12 | Distance du centreaxe pour chercher un footway |
| `SIDEWALK_GAP_SEARCH_M` | 8 | Rayon de recherche autour de l'offset |
| `SIDEWALK_GAP_MAX_ANGLE` | 35 | Angle max (°) pour considérer un footway parallèle |
| `SIDEWALK_GAP_MIN_COVERAGE` | 0.4 | Couverture min (fraction) pour valider un côté |

---

## Coût des arêtes (routage)

| Highway | Coût |
|---------|------|
| `pedestrian`, `footway` | 1.0 |
| `path`, `living_street` | 1.2 |
| `cycleway` (foot=yes) | 1.0 |
| `cycleway` (sans foot) | 1.8 |
| `steps` | 1.5 |
| `residential`, `service` | 2.0 |
| `unclassified` | 2.2 |
| `tertiary` | 3.5 |
| `secondary` | 5.0 |
| `primary` | 8.0 |

---

## Interface

- **Flux piéton** (vert) — infrastructure dédiée : footway, pedestrian, path, living_street
- **Flux cycleway** (bleu/violet) — pistes cyclables avec ou sans `foot=yes`
- **Flux sur route** (orange→rouge) — chaussée sans infrastructure piétonne séparée ; épaisseur variable selon la classe de route (`primary` > `secondary` > `tertiary` > `residential`)
- **Slider "Flux route min"** — masque les segments de flux sur route sous un seuil de `flow_pct` (n'affecte pas les flux piétons ni cycleway)
- **Score marchabilité** — point par rue, couleur 0 (rouge) → 1 (vert)
- **Trottoir un seul côté** — segments routiers avec footway mappé d'un seul côté
- **Tags sidewalk** — état de la documentation OSM par segment de route
- **Navigation** — routage Dijkstra client-side depuis `graph.json`
- **Éditer dans OSM** — lien direct vers l'éditeur OSM au niveau de zoom actuel (activé à partir du zoom 16)

---

## Données

- **Source OSM** : extrait quotidien Brussels Capital Region
- **Mise à jour** : tous les lundis à 3h UTC (cron GitHub Actions)
- **Licence** : données © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) (ODbL)
- **Tuiles de fond** : [OpenFreeMap](https://openfreemap.org/) Liberty style
