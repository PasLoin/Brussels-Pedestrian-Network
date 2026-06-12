# Changelog

## 2026-06-12

### Nouvelle couche : Traversées manquantes ([#36](https://github.com/PasLoin/Brussels-Pedestrian-Network/issues/36))

- **Détection des `highway=crossing` orphelins** : nouveau module `scripts/detect_missing_crossings.py` qui identifie les nœuds de traversée piétonne dépourvus de way `footway=crossing` correctement connecté. Le routeur n'utilise pas ces traversées, donc le flux piéton les ignore silencieusement — cette couche les rend visibles aux mappeurs.
- **Deux catégories distinguées par couleur** :
  - 🟠 **`missing_way`** (orange) — aucun way `highway=footway` ni `highway=pedestrian` ne passe à moins de 3 m du nœud → traversée pas mappée du tout.
  - 🟡 **`missing_tag`** (jaune) — un way piéton est connecté géométriquement (nœud partagé, distance ≈ 0) mais aucun way `footway=crossing` n'existe dans un rayon de 20 m → le tag `footway=crossing` manque sur le way connecté.
- **Filtres d'exclusion géométriques** pour limiter le bruit :
  - Trottoirs `footway=sidewalk` requis des **deux côtés** de la route au point du nœud (présence vérifiée dans une zone perpendiculaire de 15 m centrée à 7 m du centre de la route).
  - Filtre angulaire : seuls les trottoirs dont l'orientation diffère de la route de moins de 40° comptent. Évite les faux positifs aux intersections où le trottoir d'une rue qui croise déborde dans la zone de recherche.
  - Nœuds sur `highway=service`, `highway=cycleway` ou `highway=track` rejetés : ces voies n'ont par convention pas de way de traversée mappé. Le rejet utilise la distance comparative (si la way exclue est plus proche que la route éligible la plus proche, on saute).
  - Nœuds taggés `crossing:continuous=yes` exclus de `missing_tag` (plateaux/traversées surélevées : pas de way séparé attendu). `missing_way` reste signalé car la connectivité piétonne manque toujours.
- **Préservation tippecanoe** : build en deux passes pour garantir qu'aucun point ne soit perdu au zoom bas. Une archive PMTiles dédiée pour `missing_crossings` est produite avec `-r1 --no-tile-size-limit --no-feature-limit` (pas de drop par densité), puis fusionnée dans l'archive principale via `tile-join`. `--drop-densest-as-needed` opère par tuile et éjectait les points QA lorsque d'autres couches saturaient la tuile à z9–z11.
- **Interface** :
  - Layer visible dès z12, taille fixe 12 px du zoom 12 au zoom 18 pour être repérable de loin.
  - Toggle dans la légende ("Analyse spatiale et qualité") avec un sous-filtre multi-sélection : afficher uniquement `missing_way`, uniquement `missing_tag`, ou les deux.
  - Popup affichant le type de problème (way absent vs tag absent) et le nom de la rue.
- **Robustesse de lecture** : `_load_crossing_nodes` utilise `stdlib json` au lieu de `gpd.read_file` pour gérer le cas où `highways.geojson` mélange Points et LineStrings (que certaines versions de pyogrio refusent), et déballe automatiquement les structures de FeatureCollection imbriquées éventuellement produites par jq.
- **Correctif jq dans `build.yml`** : le step "Slim highways" produisait un `features: <FeatureCollection>` au lieu d'un tableau (suffixe `| {type, features: .}` redondant après `.features |= map(...)`). Tippecanoe tolérait, pyogrio plantait.
- **Tags préservés dans le slim** : `crossing:continuous` ajouté à la liste des propriétés conservées pour permettre la détection des traversées surélevées.

## 2026-06-01
 
### Fusion des couches "forced" dans flow_edges (issue #24)
 
- **Suppression des layers PMTiles `forced_segments` et `forced_cycleway`** : ces deux couches ne sont plus incluses dans l'archive PMTiles. L'information qu'elles portaient est désormais disponible via la propriété `highway=*` ajoutée à `flow_edges`, ce qui permet un rendu par type de route directement dans la couche de flux.
- **`flow_edges` enrichi** : la propriété `highway` (ex. `primary`, `residential`, `tertiary`…) est maintenant exportée dans `flow_edges.geojson`. Les propriétés de la couche PMTiles sont donc : `highway`, `flow_pct`, `infra_type`.
- **`forced_segments.geojson` / `forced_cycleway.geojson`** : toujours produits avec toutes leurs propriétés (`flow`, `length_m`…) et uploadés comme artifacts CI pour usage statistique. Ils ne sont simplement plus dans le PMTiles.
- **Épaisseur de ligne par type de route (`flow-road`)** : la largeur des segments de flux sur route varie désormais selon `highway=*` — les routes primaires apparaissent plus épaisses que les voiries résidentielles à flux équivalent, rendant la hiérarchie routière visible sans couche dédiée.
- **Slider "Flux route min"** : nouveau contrôle dans le panneau header permettant de masquer les segments `flow-road` dont le `flow_pct` est inférieur au seuil choisi (0–95 %, pas de 5 %). N'affecte pas `flow-ped` ni `flow-cycleway`.
  - le filtre du slider est toujours combiné avec `["==", infra_type, "road"]` pour éviter que les features piétonnes ne basculent dans la couche rouge lors de l'application du seuil.
- **Allègement du layer `highways`** : step `jq` ajouté dans `build.yml` pour ne conserver que les propriétés utiles au frontend (`highway`, `amenity`, `name`, `foot`, `bicycle`, `access`, `segregated`). Supprime les tags OSM non utilisés (surface, lit, tram, steps:count, etc.) et réduit la taille du PMTiles.

## 2026-04-28

### Ajout sidewalk* tags

- **Nouveau layer** : En plus de l'analyse spatiale qui identifie la présence d'un sidewalk séparé mappé on prend en compte la présence des tags de la route principale , l'outil permet de visualiser en combinaison avec les layers existant les lacunes et erreurs sur la carte

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
