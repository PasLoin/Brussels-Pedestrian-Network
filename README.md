# Brussels Pedestrian Network

Carte des flux piétons simulés à Bruxelles, calculés à partir d'OpenStreetMap, avec des couches de contrôle qualité pour les contributeurs OSM.

[Carte](https://pasloin.github.io/Brussels-Pedestrian-Network/) · [Statistiques](https://pasloin.github.io/Brussels-Pedestrian-Network/stats.html) · [Évolution](https://pasloin.github.io/Brussels-Pedestrian-Network/evolution.html) · [Méthodologie](https://pasloin.github.io/Brussels-Pedestrian-Network/about.html)

## Principe

Le pipeline tire des paires origine-destination parmi les adresses OSM, calcule le plus court chemin pondéré de chacune avec Dijkstra (igraph), puis compte les passages par segment.

La carte montre ainsi :
- les trottoirs, zones piétonnes et chemins les plus utilisés ;
- les routes où la simulation fait marcher les piétons sur la chaussée, faute d'infrastructure piétonne mappée à proximité ;
- les pistes cyclables empruntées faute d'autre chemin (cycleway sans `foot=yes`) ;
- des erreurs et lacunes de mapping : trottoir d'un seul côté, traversées non reliées, kerbs absents, bandes podotactiles incohérentes, îlots du graphe.

## Couches PMTiles

| Couche | Contenu |
|--------|---------|
| `highways` | Réseau piéton de base (footway, pedestrian, path, steps, cycleway, track…) et nœuds crossing / elevator |
| `flow_edges` | Flux simulés : `infra_type`, `flow_pct`, `highway` |
| `sidewalk_gaps` | Routes avec un trottoir séparé détecté d'un seul côté |
| `sidewalk_separate_candidates` | Routes avec trottoirs séparés des deux côtés mais sans aucun tag sidewalk |
| `sidewalk_roads` | Statut des tags sidewalk sur les routes |
| `footway_crossing_candidates` | Footways qui relient deux trottoirs à travers une route sans `footway=crossing` |
| `graph_islands` | Parties du graphe non reliées au réseau principal, et discontinuités de `level` sur les escaliers |
| `missing_crossings` | Nœuds `highway=crossing` sans way `footway=crossing` correctement relié |
| `tactile_paving_issues` | `tactile_paving` du crossing en contradiction avec celui des kerbs |
| `kerb_issues` | Kerb absent en bout de traversée, ou kerb sans `tactile_paving` |

Les trois dernières couches sont construites dans une archive séparée sans suppression de points (`-r1 --no-feature-limit --no-tile-size-limit`), puis fusionnées avec `tile-join`.

`forced_segments.geojson` et `forced_cycleway.geojson` ne sont plus dans le PMTiles ; on retrouve l'information dans `flow_edges` via `highway=*`. Les fichiers complets restent dans les artifacts CI (7 jours).

### Propriétés de `flow_edges`

| Propriété | Valeurs | Description |
|-----------|---------|-------------|
| `infra_type` | `pedestrian`, `road`, `cycleway_foot_yes`, `cycleway_no_foot` | Type d'infrastructure |
| `flow_pct` | 0 à 100 | Flux relatif, en % du maximum |
| `highway` | `footway`, `primary`, `residential`… | Tag OSM d'origine |

## Pipeline de build

```
brussels.osm.pbf
    │
    ├─ osmium tags-filter → highways.geojson          (couche visuelle)
    ├─ osmium tags-filter → sidewalk_roads_raw.geojson, sidewalk_footways_raw.geojson
    ├─ osmium tags-filter → kerbs_raw, platforms_raw, service_roads_raw, cycleways_raw, tracks_raw
    ├─ osmium tags-filter → routing_raw.osm
    └─ osmium tags-filter → addresses.geojson
              │
    scripts/main.py
              │
    ├─ clean_osm.py                    : coupe les ways aux barrières bloquantes
    ├─ build_graph.py                  : OSMnx → igraph, index sidewalk
    ├─ detect_graph_islands.py         : composantes hors réseau principal, discontinuités de niveau
    ├─ sample_od.py                    : points OD par intervalle, accrochage aux arêtes
    ├─ routing.py                      : paires OD, Dijkstra groupé par source
    ├─ export.py                       : flow_edges, forced_*, graph.json, stats.json
    ├─ sidewalk_gap.py                 : trottoirs d'un seul côté
    ├─ export_sidewalk_roads.py        : statut des tags sidewalk
    ├─ detect_missing_crossings.py     : traversées non reliées
    ├─ detect_footway_connectivity.py  : candidats footway=crossing
    └─ detect_tactile_paving_issues.py : kerbs et bandes podotactiles
              │
    tippecanoe + tile-join → pedestrian.pmtiles
              │
    GitHub Pages (branche gh-pages)
```

## Modules Python (`scripts/`)

| Fichier | Rôle |
|---------|------|
| `config.py` | Paramètres communs, lus depuis les variables d'environnement |
| `clean_osm.py` | Nettoyage de l'OSM XML, découpe aux barrières |
| `build_graph.py` | Graphe igraph, index sidewalk |
| `sample_od.py` | Points OD depuis les adresses, accrochage |
| `routing.py` | Paires OD, Dijkstra, cumul des flux |
| `export.py` | GeoJSON, `graph.json`, `stats.json` |
| `detect_graph_islands.py` | Îlots et discontinuités de niveau |
| `sidewalk_gap.py` | Trottoirs d'un seul côté |
| `export_sidewalk_roads.py` | Tags sidewalk des routes |
| `detect_missing_crossings.py` | Traversées manquantes |
| `detect_footway_connectivity.py` | Candidats `footway=crossing` |
| `detect_tactile_paving_issues.py` | Kerbs et `tactile_paving` |
| `compute_history.py` | Snapshots mensuels pour `history.json` |
| `pwg_schema_fetch.py`, `pwg_criteria.py` | Lecture du schéma PWG du wiki OSM et des surcharges de `pwg/overrides.yaml` |
| `timing.py` | Mesure de durée par étape |
| `debug_snap.py`, `bench_dijkstra.py` | Outils de diagnostic, hors build |

## Paramètres

Les valeurs utilisées en production sont dans le bloc `env` de `.github/workflows/build.yml`. La colonne « Code » donne la valeur par défaut quand la variable est absente.

### Échantillonnage et routage

| Variable | build.yml | Code | Description |
|----------|-----------|------|-------------|
| `OD_SAMPLE_INTERVAL_M` | 100 | 100 | Intervalle entre points OD le long d'une rue (m) |
| `MIN_OD_DISTANCE_M` | 600 | 300 | Distance minimale d'une paire OD (m) |
| `MAX_OD_DISTANCE_KM` | 1 | 5 | Distance maximale d'une paire OD (km) |
| `MAX_OD_PAIRS` | 900 000 | 50 000 | Nombre de paires simulées |
| `MAX_SNAP_DISTANCE_M` | 150 | 150 | Au-delà, une adresse n'est pas accrochée au réseau |

### Flux et export

| Variable | build.yml | Code | Description |
|----------|-----------|------|-------------|
| `TOP_RANK_PCT` | 15 | 5 | Part des flux les plus forts gardée dans `forced_*` (%) |
| `MIN_FLOW_THRESHOLD` | 5 | 5 | Passages minimum pour qu'une arête entre dans `flow_edges` |

### Trottoirs d'un seul côté

| Variable | build.yml | Code | Description |
|----------|-----------|------|-------------|
| `SIDEWALK_GAP_OFFSET_M` | 7 | 7 | Distance à l'axe de la route où l'on cherche un trottoir (m) |
| `SIDEWALK_GAP_SEARCH_M` | 8 | 7 | Rayon de recherche autour de ce point (m) |
| `SIDEWALK_GAP_MAX_ANGLE` | 65 | 35 | Écart d'angle maximum avec la route (°) |
| `SIDEWALK_GAP_MIN_COVERAGE` | 0.4 | 0.4 | Part de la longueur à couvrir pour valider un côté |

### Traversées, îlots, kerbs

| Variable | build.yml | Description |
|----------|-----------|-------------|
| `CROSSING_NODE_ROAD_SEARCH_M` | 20 | Recherche de la route sous un nœud crossing (m) |
| `CROSSING_WAY_SEARCH_RADIUS_M` | 20 | Rayon de recherche d'un way `footway=crossing` (m) |
| `CROSSING_NODE_CONNECTED_M` | 3 | Distance en dessous de laquelle un footway est considéré relié (m) |
| `CROSSING_SIDEWALK_OFFSET_M` / `_SEARCH_M` / `_MAX_ANGLE` | 7 / 15 / 40 | Recherche des trottoirs de part et d'autre du crossing |
| `FOOTWAY_CONN_ENDPOINT_TOL_M` / `_TIP_MARGIN_M` / `_MAX_LEN_M` | 3 / 2 / 40 | Candidats `footway=crossing` |
| `ISLAND_UNJOINED_GAP_M` | 2 | Écart maximum pour classer un îlot en « jonction manquante » (m) |
| `ISLAND_PLATFORM_TOLERANCE_M` | 1 | Tolérance pour les quais de transport public (m) |
| `TACTILE_PAVING_WAY_MATCH_M` / `_KERB_MATCH_M` | 0.5 / 0.5 | Appariement crossing ↔ way ↔ kerb (m) |

## Coût des arêtes

Le poids d'une arête est sa longueur multipliée par ce facteur.

| Highway | Coût |
|---------|------|
| `pedestrian`, `footway` | 1.0 |
| `path`, `living_street`, `track`, `bridleway` | 1.2 |
| `cycleway` avec `foot=yes/designated/permissive` | 1.0 |
| `cycleway` sans accès piéton explicite | 1.8 |
| `steps` | 1.5 |
| `residential`, `service` | 2.0 |
| `unclassified` | 2.2 |
| `tertiary` | 3.5 |
| `secondary` | 5.0 |
| `primary` | 8.0 |
| autre | 2.5 |

## Interface

La légende regroupe les couches en trois sections.

Routage simulé : flux piéton (vert), flux sur cycleway (bleu avec `foot=yes`, violet sans), flux sur route (orange à rouge, plus épais sur les routes de rang supérieur).

Analyse spatiale et qualité : trottoir d'un seul côté, candidats `footway=crossing`, bandes podotactiles incohérentes, kerbs, traversées manquantes, îlots, tags sidewalk. Les trois dernières ont un filtre par type.

Réseau de base : les ways OSM par type de highway, masqués par défaut.

Le curseur « Flux route min » masque les flux sur route sous le seuil choisi, sans toucher aux flux piétons et cycleway. Le bouton Navigation calcule un itinéraire dans le navigateur à partir de `graph.json`. « Éditer dans OSM » s'active à partir du zoom 16.

## Données

Extrait OSM quotidien de la Région de Bruxelles-Capitale. Le build tourne chaque jour à 1 h UTC. Données © [contributeurs OpenStreetMap](https://www.openstreetmap.org/copyright), licence ODbL. Fond de carte : style Liberty d'[OpenFreeMap](https://openfreemap.org/).
