# Changelog

## 2026-04-24

### Refactoring

- **Code modulaire** : le script Python inline de ~400 lignes dans `build.yml` est extrait en 7 modules dans `scripts/` : `config.py`, `clean_osm.py`, `build_graph.py`, `sample_od.py`, `routing.py`, `export.py`, `main.py`. ([#9](https://github.com/PasLoin/Brussels-Pedestrian-Network/issues/9))
- **Renommage `surface_cat` → `infra_type`** : évite la confusion avec le tag OSM `surface` (qui décrit le revêtement physique, pas le type d'infrastructure).

### Corrections d'algorithme

- **Cycleways avec `foot=yes`** : ne sont plus classés dans `forced_cycleway`. Nouveau type `cycleway_foot_yes` distinct de `cycleway_no_foot`, avec couche de flux unifiée (un seul toggle légende, deux couleurs). ([#6](https://github.com/PasLoin/Brussels-Pedestrian-Network/issues/6))
- **Préservation des tags OSMnx** : `foot`, `sidewalk`, `sidewalk:left`, `sidewalk:right` et `segregated` sont explicitement ajoutés à `useful_tags_way` pour survivre à la simplification du graphe. Correction de `_first_str()` pour gérer les `NaN` produits par la fusion de segments.
- **Adresses nœuds + ways** : extraction avec `nw/addr:housenumber` au lieu de `n/` seul. Les polygones de bâtiments (ways) sont convertis en centroïdes. Passe de 16 à 163 adresses pour l'Avenue de Messidor.

### Snapping et échantillonnage

- **Snapping par arête** : les points OD sont snappés sur l'arête la plus proche (distance point-segment) au lieu du nœud le plus proche. Résout les faux négatifs sur les rues avec un trottoir d'un seul côté. Fallback sur nearest-node si ambiguïté (>2 arêtes à distance quasi égale). ([#14](https://github.com/PasLoin/Brussels-Pedestrian-Network/issues/14))
- **Échantillonnage géographique** : remplace le fixe `POINTS_PER_SIDE=5` par un intervalle spatial configurable (`OD_SAMPLE_INTERVAL_M`, défaut 100 m). Un point par bin par côté de rue, indépendamment. Scale avec la longueur de la rue.

### Nouvelle couche : Sidewalk Gaps

- **Détection spatiale des trottoirs dessinés d'un seul côté** : pour chaque segment de route, vérifie la présence de footways parallèles (±35°) de chaque côté avec une couverture minimale de 40 %.
- Exclusion des `highway=service` et des routes avec tags `sidewalk:left`/`sidewalk:right` explicites.
- Déduplication des arêtes dirigées pour éviter les doublons dans l'export.
- Couche désactivée par défaut dans la légende (section "Analyse spatiale").

### Optimisation PMTiles

- **`MIN_FLOW_THRESHOLD=5`** : les arêtes avec moins de 5 passages sont exclues de `flow_edges`, réduisant le nombre de features.
- **Propriétés allégées** : `flow_edges` ne contient plus que `flow_pct` et `infra_type` (au lieu de 5 propriétés). Les couches `forced_*` gardent toutes leurs propriétés.
- **Adresses retirées** du PMTiles (utilisées uniquement pendant le build).
- **`MIN_ZOOM` passé de 8 à 9**.
- `--no-feature-limit` et `--no-tile-size-limit` rétablis après confirmation que la taille reste sous 100 MB.
- Résultat : ~58 MB au lieu de ~142 MB.

### Interface

- Popup des flux simplifié (infra + flux relatif uniquement).
- Popup des sidewalk gaps avec nom de rue.
- Légende réorganisée : sections "Routage simulé", "Analyse spatiale", "Réseau de base".
- Navigation client-side : surface category 3 (cycleway_foot_yes) coloré en bleu, comptabilisé comme piéton dans les stats d'itinéraire.
