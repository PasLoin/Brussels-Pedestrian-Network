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
    analysis_boundary.poly ← BOUNDARY_POLY_URL   (zone d'analyse des couches QA)
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
| `analysis_boundary.py` | Lecture du polygone `.poly` de la zone d'analyse, filtrage et découpe des objets |
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

Tous les paramètres de calcul sont dans `scripts/config.py`, avec leur valeur de production. C'est la seule source de vérité : `build.yml` n'en contient aucun, et un test le vérifie. Pour adapter le projet à une autre ville, on modifie `config.py`, ainsi que l'URL du PBF, l'URL du polygone de la zone d'analyse (`BOUNDARY_POLY_URL`), les types de voies et les niveaux de zoom dans `build.yml`.

Pour lancer une simulation différente, on définit la variable d'environnement du même nom : elle l'emporte sur `config.py`, par exemple `MAX_OD_DISTANCE_KM=2 python3 scripts/main.py`.

### Échantillonnage et routage

| Variable | Valeur | Description |
|----------|--------|-------------|
| `OD_SAMPLE_INTERVAL_M` | 100 | Intervalle entre points OD le long d'une rue (m) |
| `POINTS_PER_SIDE` | 5 | Mode historique, si `OD_SAMPLE_INTERVAL_M` vaut 0 : points OD par côté de rue |
| `MIN_OD_DISTANCE_M` | 600 | Distance minimale d'une paire OD (m) |
| `MAX_OD_DISTANCE_KM` | 1 | Distance maximale d'une paire OD (km) |
| `MAX_OD_PAIRS` | 900 000 | Nombre de paires simulées |
| `MAX_SNAP_DISTANCE_M` | 150 | Au-delà, une adresse n'est pas accrochée au réseau (m) |

### Flux et export

| Variable | Valeur | Description |
|----------|--------|-------------|
| `TOP_RANK_PCT` | 15 | Part des flux les plus forts gardée dans `forced_*` (%) |
| `MIN_FLOW_THRESHOLD` | 5 | Passages minimum pour qu'une arête entre dans `flow_edges` |

### Trottoirs d'un seul côté

| Variable | Valeur | Description |
|----------|--------|-------------|
| `SIDEWALK_GAP_OFFSET_M` | 7 | Distance à l'axe de la route où l'on cherche un trottoir (m) |
| `SIDEWALK_GAP_SEARCH_M` | 8 | Rayon de recherche autour de ce point (m) |
| `SIDEWALK_GAP_MAX_ANGLE` | 65 | Écart d'angle maximum avec la route (°) |
| `SIDEWALK_GAP_MIN_COVERAGE` | 0.4 | Part de la longueur à couvrir pour valider un côté |

### Traversées

| Variable | Valeur | Description |
|----------|--------|-------------|
| `CROSSING_NODE_ROAD_SEARCH_M` | 20 | Recherche de la route sous un nœud crossing (m) |
| `CROSSING_WAY_SEARCH_RADIUS_M` | 3 | Rayon de recherche d'un way `footway=crossing` (m) |
| `CROSSING_NODE_CONNECTED_M` | 3 | Distance en dessous de laquelle un footway est considéré relié (m) |
| `CROSSING_SIDEWALK_OFFSET_M` | 7 | Distance au nœud où l'on cherche les trottoirs (m) |
| `CROSSING_SIDEWALK_SEARCH_M` | 15 | Rayon de recherche des trottoirs (m) |
| `CROSSING_SIDEWALK_MAX_ANGLE` | 40 | Écart d'angle maximum entre trottoir et route (°) |
| `CROSSING_WRONG_TAG_SNAP_M` | 0.5 | Un `footway=sidewalk` à moins de cette distance du nœud est une traversée mal taguée (m) |
| `FOOTWAY_CONN_ENDPOINT_TOL_M` | 3 | Candidats `footway=crossing` : distance max entre une extrémité et un trottoir (m) |
| `FOOTWAY_CONN_TIP_MARGIN_M` | 2 | Candidats `footway=crossing` : la route doit être croisée à plus de cette distance des extrémités (m) |
| `FOOTWAY_CONN_MAX_LEN_M` | 40 | Candidats `footway=crossing` : longueur maximale (m) |

### Îlots, niveaux, kerbs

| Variable | Valeur | Description |
|----------|--------|-------------|
| `ISLAND_UNJOINED_GAP_M` | 2 | Écart maximum pour classer un îlot en « jonction manquante » (m) |
| `ISLAND_PLATFORM_TOLERANCE_M` | 1 | Tolérance pour les quais de transport public (m) |
| `LEVEL_UNTAGGED_AS_GROUND` | 0 | Traiter un `level` absent comme le niveau du sol (1 = oui) |
| `TACTILE_PAVING_WAY_MATCH_M` | 0.5 | Appariement crossing ↔ way (m) |
| `TACTILE_PAVING_KERB_MATCH_M` | 0.5 | Appariement way ↔ kerb (m) |

### Outils de diagnostic

| Variable | Valeur | Description |
|----------|--------|-------------|
| `BENCH_N_SOURCES` | 1000 | `bench_dijkstra.py` : nombre de sources |
| `BENCH_N_TARGETS` | 50 | `bench_dijkstra.py` : cibles par source |

## Zone d'analyse

Les couches QA se limitent au polygone `analysis_boundary.poly` (Région de Bruxelles-Capitale, relation OSM 54094), téléchargé par le build depuis `BOUNDARY_POLY_URL`. Seuls les nœuds `highway=crossing` de la zone sont examinés, et les routes de `sidewalk_gaps` sont coupées à sa limite ; les données hors zone servent de contexte. Les objets écartés sont comptés dans `crossings_outside_boundary` et `roads_outside_boundary`. Sans ce fichier, aucune restriction n'est appliquée.

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
