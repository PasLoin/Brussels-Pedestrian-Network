# Brussels Pedestrian Network

Carte interactive des flux piétons simulés à Bruxelles, construite à partir des données OpenStreetMap.

[Voir la carte](https://pasloin.github.io/Brussels-Pedestrian-Network/) · [Statistiques](https://pasloin.github.io/Brussels-Pedestrian-Network/stats.html)

## Principe

Le pipeline simule des trajets piétons entre des paires origine-destination échantillonnées depuis les adresses OSM. Les chemins les plus courts sont calculés sur le graphe de voirie avec Dijkstra (igraph), puis les passages sont agrégés par arête pour produire des couches de flux.

On peut ainsi repérer :
- les corridors piétons les plus fréquentés (flux sur footway, pedestrian et path) ;
- les routes où les piétons doivent marcher sur la chaussée faute d'infrastructure dédiée à proximité ;
- les pistes cyclables empruntées faute d'alternative (cycleway sans `foot=yes`) ;
- les lacunes du réseau : trottoirs mappés d'un seul côté, routes sans tag sidewalk.

## Couches PMTiles

| Couche | Description |
|--------|-------------|
| `highways` | Réseau piéton de base (footway, pedestrian, path, steps, cycleway…) |
| `flow_edges` | Flux simulés, avec les propriétés `infra_type`, `flow_pct` et `highway` |
| `street_scores` | Score de marchabilité par rue (de 0 à 1), pénalisé selon les tags sidewalk |
| `sidewalk_gaps` | Routes avec un trottoir mappé d'un seul côté (analyse spatiale) |
| `sidewalk_roads` | Tags sidewalk sur les routes (QA cartographique) |

Les anciennes couches `forced_segments` et `forced_cycleway` sont maintenant incluses dans `flow_edges`, où on les distingue par la propriété `highway=*`. Leurs GeoJSON complets restent disponibles dans les artifacts CI.

### Propriétés de `flow_edges`

| Propriété | Valeurs | Description |
|-----------|---------|-------------|
| `infra_type` | `pedestrian`, `road`, `cycleway_foot_yes`, `cycleway_no_foot` | Type d'infrastructure |
| `flow_pct` | 0 à 100 | Flux relatif (% du maximum global) |
| `highway` | `footway`, `primary`, `residential`… | Tag OSM d'origine |

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
    ├─ clean_osm.py             : split ways aux barrières bloquées
    ├─ build_graph.py           : OSMnx → igraph, index sidewalk
    ├─ sample_od.py             : échantillonnage OD géographique + snapping par arête
    ├─ routing.py               : Dijkstra groupé par source, accumulation flux
    ├─ export.py                : flow_edges / forced_* / street_scores / graph.json
    ├─ sidewalk_gap.py          : détection spatiale trottoirs unilatéraux
    └─ export_sidewalk_roads.py : QA tags sidewalk
              │
    tippecanoe → pedestrian.pmtiles
              │
    GitHub Pages
```

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

## Paramètres configurables

Tous les paramètres sont des variables d'environnement définies dans `.github/workflows/build.yml`.

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
| `SIDEWALK_GAP_OFFSET_M` | 12 | Distance depuis l'axe de la route pour chercher un footway |
| `SIDEWALK_GAP_SEARCH_M` | 8 | Rayon de recherche autour de l'offset |
| `SIDEWALK_GAP_MAX_ANGLE` | 35 | Angle max (°) pour considérer un footway parallèle |
| `SIDEWALK_GAP_MIN_COVERAGE` | 0.4 | Couverture min (fraction) pour valider un côté |

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

## Interface

La légende de la carte propose les couches suivantes :
- Flux piéton (vert) : infrastructure dédiée (footway, pedestrian, path, living_street).
- Flux cycleway (bleu/violet) : pistes cyclables, avec ou sans `foot=yes`.
- Flux sur route (orange à rouge) : chaussée sans infrastructure piétonne séparée. L'épaisseur dépend de la classe de route (`primary` > `secondary` > `tertiary` > `residential`).
- Score de marchabilité : un point par rue, coloré de 0 (rouge) à 1 (vert). (amené à disparaître) 
- Trottoir un seul côté : segments routiers dont le footway n'est mappé que d'un côté.
- Tags sidewalk : état de la documentation OSM pour chaque segment de route.

Le curseur « Flux route min » masque les flux sur route dont le `flow_pct` est sous le seuil choisi ; les flux piétons et cycleway restent affichés. Le mode navigation calcule un itinéraire Dijkstra dans le navigateur à partir de `graph.json`. Le bouton « Éditer dans OSM » ouvre l'éditeur OSM au niveau de zoom actuel, à partir du zoom 16.

## Données

Les données viennent de l'extrait quotidien OSM de la Région de Bruxelles-Capitale. Le build tourne tous les jours à 1 h UTC (cron GitHub Actions). Données © [contributeurs OpenStreetMap](https://www.openstreetmap.org/copyright), licence ODbL. Le fond de carte est le style Liberty d'[OpenFreeMap](https://openfreemap.org/).
