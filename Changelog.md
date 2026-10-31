# Changelog

## 2026-10-28

### Kerbs absents : vérifiés sur toutes les traversées, quel que soit le `tactile_paving` du crossing (#60)

- La recherche de `barrier=kerb` absent se faisait dans la boucle de cohérence `tactile_paving`, qui ne voit que les nœuds `highway=crossing` tagués `yes`, `no` ou `incorrect`. Un crossing sans `tactile_paving` (ou avec une autre valeur) n'était donc jamais examiné. La présence des kerbs est maintenant vérifiée dans une boucle à part, sur tous les nœuds `highway=crossing` rattachés à un `footway=crossing`.
- Les points « kerb sans `tactile_paving` » restent limités aux crossings tagués `yes`, `no` ou `incorrect`.

## 2026-10-27

### Bandes podotactiles : deux `footway=crossing` contigus traités comme une seule traversée (#55)

- Quand l'extrémité d'un `footway=crossing` ne touche que l'extrémité d'un autre `footway=crossing` (pas de `barrier=kerb`, pas de nœud `highway=crossing`, aucun autre way à ce nœud), la jonction n'est plus prise pour une bordure. Les bordures sont vérifiées aux deux extrémités extérieures de la paire. C'est le cas d'une traversée coupée en deux entre la piste cyclable et la chaussée, ou à un changement de revêtement.
- Seules les paires sont fusionnées, pas les chaînes de trois tronçons ou plus.

## 2026-10-26

### Trottoir d'un seul côté : `highway=cycleway` + `foot=yes` compté comme trottoir (#54)

- Les ways `highway=cycleway` avec `foot=yes|designated|permissive` (tirées de `cycleways_raw.geojson`) sont indexées avec les footways. Une piste cyclable ouverte aux piétons le long de la route couvre ce côté, et la rue n'est plus signalée. On aurait pu exiger `is_sidepath=yes` pour confirmer, mais ce tag n'est pas encore utilisé à Bruxelles.
- Les cycleways sans accès piéton explicite ne comptent toujours pas comme trottoir.
- Stats : nouvelle part `cycleway (foot)` dans « Footways retenus (composition) » (`footway_filter.kept_cycleway_foot`).

## 2026-10-23

### Traversée manquante : ways de traversée taguées `footway=sidewalk` (#52)

- Quand un nœud `highway=crossing` situé sur la route est partagé par un way `highway=footway` + `footway=sidewalk`, le nœud est signalé avec le type `wrong_tag` (point rouge « Taguée footway=sidewalk » dans « Traversée manquante »). Jusqu'ici seuls les tags absents étaient vérifiés, pas les tags erronés.
- Les nœuds `crossing:continuous=yes` sont exclus, puisqu'un trottoir continu y est attendu.

## 2026-10-17

### Îlots déconnectés : discontinuités de niveau sur les escaliers (#50)

- Pour chaque `highway=steps` qui porte un `level=*`, on compare le niveau avec celui des ways raccordées directement à ses extrémités. Si le niveau d'une de ces ways ne recouvre pas celui de l'escalier, le nœud est signalé.
- Les jonctions entre ways qui ne sont pas des steps ne sont pas examinées.
- Le routage et la simulation ne changent pas ; c'est une couche QA seulement. Elle peut produire des faux positifs dans les stations complexes (train, métro), selon la façon dont les `level` y sont mappés.

## 2026-10-14

### Corrections

- `highway=track` fait partie du réseau piéton, sauf restriction explicite.
- Vérification de la présence d'un `highway=*` : on trouve parfois `foot=yes` sur des objets inattendus (`landuse`, par exemple).
- Îlots déconnectés : les footways et steps qui relient un `public_transport=platform` sont exclus.
- Trottoir d'un seul côté : `sidewalk=right`, `sidewalk=no`, etc. (ancien schéma, encore présent) sont pris en compte, ce qui retire des faux positifs.
- Portails bloquants malgré `foot=yes` : `clean_osm` coupait le graphe à tout `barrier=gate` avec `access=private` ou `no`, sans regarder `foot`. Corrigé.

## 2026-10-13

### Corrections

- Arêtes comptées deux fois. Le graphe OSMnx est construit avec `bidirectional=True`, donc chaque tronçon existe sous forme de deux arêtes dirigées. `export_flow_layers` et `compute_network_stats` les traitaient séparément : longueurs du réseau doublées dans `stats.json`, flux répartis sur deux lignes superposées qui portaient chacune environ la moitié du trafic, seuils `MIN_FLOW_THRESHOLD` et `TOP_RANK_PCT` appliqués à des flux par sens. La nouvelle fonction `undirected_edge_groups` regroupe les deux sens (clé : paire de nœuds, longueur, point à mi-longueur) ; les flux s'additionnent et les longueurs ne comptent qu'une fois. `graph.edges` compte maintenant les segments physiques et `graph.directed_edges` garde l'ancien chiffre.
- `MAX_OD_PAIRS` jamais atteint. Les paires OD étaient tirées au hasard puis rejetées si elles sortaient de l'anneau 600 m à 1 km, soit environ 1,5 % d'acceptation. La boucle s'arrêtait sur une limite cachée de 20 × `MAX_OD_PAIRS` tirages : 271 291 paires simulées au lieu des 900 000 configurées, pour 18 millions d'itérations Python. Les paires valides sont maintenant toutes énumérées via un index spatial (STRtree `dwithin`, par paquets), puis on en tire exactement `MAX_OD_PAIRS` avec une graine fixe. Les paires dont les deux points tombent sur le même nœud sont exclues et le sens origine/destination est tiré au hasard. `rejected_near` et `rejected_far` comptent toutes les paires hors de l'anneau, et non plus des tirages ratés.
- Historique : snapshots mensuels perdus (`history.yml`). Deux bugs se cumulaient. Une entrée était reconnue par sa seule date, si bien qu'une `daily` du 1er du mois masquait le snapshot publié ensuite à la même date ; et la fusion jq supprimait toutes les entrées `daily` à chaque ajout. Le snapshot 2026-09-01 manquait et 2026-10-01 était typé `daily`. Une entrée est maintenant identifiée par sa date et son type, et la fusion ne retire les autres `daily` que si la nouvelle entrée en est une. L'historique se répare au prochain run en mode `update`.
- Adresses accrochées à des îlots du graphe. Avec `retain_all=True`, les composantes déconnectées restent dans le graphe et l'accrochage pouvait y rattacher des points OD dont les trajets devenaient impossibles (environ 1,6 % des paires perdues sans message). L'accrochage, repli sur le nœud le plus proche compris, se limite maintenant au réseau principal (la plus grande composante). Une adresse à plus de `MAX_SNAP_DISTANCE_M` (150 m) de ce réseau est écartée. Nouveaux compteurs `points_redirected_from_islands` et `points_dropped_too_far` dans `stats.json`.
- Navigation : le nœud de départ ou d'arrivée choisi au clic ignore les îlots (composante principale calculée dans le navigateur). Les faux « Aucun itinéraire trouvé » disparaissent.

### Nouvelle couche : îlots déconnectés du réseau

- Nouveau module `scripts/detect_graph_islands.py`. Chaque composante non reliée au réseau principal est exportée comme une entité (MultiLineString) avec sa longueur, ses types de voies, les identifiants de ses ways OSM et sa distance au réseau principal.
- Deux catégories. `unjoined` : écart ≤ `ISLAND_UNJOINED_GAP_M` (2 m), le chemin touche presque le réseau et il manque sans doute un nœud commun. `isolated` : rien de proche, souvent à cause d'accès privés, de portails ou d'une cartographie incomplète.
- Interface : couche `graph-islands` visible dès z12, interrupteur « Îlot déconnecté du réseau » avec filtre par type, popup au clic avec écart, longueur, types, liens vers les ways OSM, lien JOSM (`load_and_zoom` cadré sur l'îlot, ways sélectionnées) et lien iD.
- Données : `graph_islands.geojson` ajouté aux artifacts CI et au PMTiles. `build_graph.py` garde les identifiants de ways OSM des arêtes (`edge_osm_ids`). Statistiques dans `stats.json` sous `graph.components`.
- Premier relevé (13/10/2026) : le réseau principal contient 98,6 % des nœuds ; 416 îlots (38,7 km), dont 66 jonctions manquantes et 350 îlots isolés ; 101 adresses redirigées vers le réseau principal.

### Paramètres

- Nouveaux : `MAX_SNAP_DISTANCE_M` (150), `ISLAND_UNJOINED_GAP_M` (2).
- Avec 900 000 trajets réellement simulés, le routage passe d'environ 5 à 7 minutes. Les seuils d'affichage (`flow_pct`) ne changent pas.

## 2026-08-10

### Nouvelle couche : `barrier=kerb` absent en bout de crossing way, et kerb sans information `tactile_paving`

## 2026-08-07

### Nouvelle couche : incohérences `tactile_paving` entre crossing et kerb

- Nouveau module `scripts/detect_tactile_paving_issues.py`. Pour chaque nœud `highway=crossing` tagué `tactile_paving=yes/no/incorrect`, on retrouve le way `footway=crossing` associé.
- Règle : `tactile_paving=yes` ou `no` sur le crossing attend la même valeur sur les deux kerbs ; `incorrect` attend un kerb `yes` et un kerb `no`. Seules les contradictions explicites sont signalées. Un kerb absent ou non tagué est une donnée manquante, pas une contradiction : il est compté dans les stats mais pas affiché.
- Interface : couche de points violets `tactile-paving-issues`, interrupteur dans « Analyse spatiale et qualité », popup avec liens OSM, JOSM et iD vers le nœud crossing et le way.

## 2026-07-05

### Fixed

- `sidewalk=separate` was classified as `unknown` and penalised. It now counts as sidewalk documented on both sides.
- The `sidewalk:left/right/both` scheme was ignored; it now feeds the sidewalk status along with the plain `sidewalk` tag.
- `oneway=yes` blocked pedestrian routing in the reverse direction. The OSMnx graph is now built with `bidirectional=True`.
- `access=private` roads were excluded even when `foot=yes` overrides them, as the OSM access hierarchy allows.
- OSMnx simplification could merge ways with different names or sidewalk tags through degree-2 nodes, so short connector ways picked up a neighbour's tags (small squares inheriting `sidewalk=both`, for example). Fixed with `edge_attrs_differ`.
- Street sidewalk status used a "best wins" rule: one tagged segment turned a whole multi-segment street into "Deux côtés". Status and penalty are now weighted by length, so undocumented segments lower the score in proportion.
- Untagged streets escaped `SIDEWALK_PENALTY_UNKNOWN` through a dead code branch, which gave walkability scores of 84 to 95 % with no sidewalk data at all. Every road street is now in the index.
- The `missing-crossings` popup closed on `mouseleave` before its OSM, JOSM and iD links could be clicked. It is now a click popup with a close button.
- "Infra piétonne" in the walkability popup showed metres accumulated over trips (up to 360 000 m for one street). It now shows mapped infrastructure within 500 m of the street centroid.

### Added

- Penalty for missing `surface=*` and `lit=*` tags: the walkability score is multiplied by `(1 − 0.15 × untagged_surface_share) × (1 − 0.10 × untagged_lit_share)`, measured on pedestrian infrastructure within 500 m. A street with a 100 % routed score and no surface or lit tags nearby now scores about 76 %.
- The walkability popup shows mapped infrastructure within 500 m, the share with `surface=*`, the share with `lit=*` and the share of road length with a sidewalk tag.
- Sidewalk status "non requis" for streets with no road edges (pedestrian ways, footpaths).
- `missing-crossings` detection writes `osm_id`, the distance to the nearest `footway=crossing` way and the search radius to the GeoJSON. The popup links to the node in OSM, JOSM (remote control) and iD.
- The osmium export uses `--attributes=type,id` so flagged crossing nodes keep their OSM id through the pipeline.
- Unit tests (`tests/`, 67 tests, about 10 s) for classification helpers, the spatial index, tag-completeness penalties, barrier splitting, OD sampling, geometry helpers and `build_graph` regressions.
- CI workflow (`.github/workflows/tests.yml`) that runs pytest on every push or PR touching `scripts/` or `tests/`.

### Removed

- The "Top 10 — rues à corriger" section of `stats.html`. A single factor drove the ranking, so it said little.

## 2026-06-12

### Nouvelle couche : traversées manquantes ([#36](https://github.com/PasLoin/Brussels-Pedestrian-Network/issues/36))

- Nouveau module `scripts/detect_missing_crossings.py`, qui repère les nœuds de traversée sans way `footway=crossing` correctement relié. Le routeur n'emprunte pas ces traversées et le flux piéton les ignore ; la couche les montre aux mappeurs.
- Deux catégories, par couleur. `missing_way` (orange) : aucun way `highway=footway` ni `highway=pedestrian` à moins de 3 m du nœud, la traversée n'est pas mappée. `missing_tag` (jaune) : un way piéton passe par le nœud mais aucun way `footway=crossing` n'existe dans un rayon de 20 m, le tag manque sur le way relié.
- Filtres pour limiter le bruit :
  - un `footway=sidewalk` doit exister des deux côtés de la route au droit du nœud (zone de 15 m centrée à 7 m de l'axe) ;
  - seuls comptent les trottoirs dont l'orientation diffère de moins de 40° de celle de la route, ce qui écarte aux carrefours le trottoir d'une rue perpendiculaire ;
  - les nœuds sur `highway=service`, `highway=cycleway` ou `highway=track` sont écartés, ces voies n'ayant pas de way de traversée par convention. Un nœud est écarté si la voie exclue est au moins aussi proche que la route éligible la plus proche ;
  - les nœuds `crossing:continuous=yes` sont exclus de `missing_tag` (plateaux, traversées surélevées : pas de way séparé attendu). `missing_way` reste signalé, car la liaison piétonne manque quand même.
- Build tippecanoe en deux passes pour ne perdre aucun point aux petits zooms. `missing_crossings` a sa propre archive PMTiles, construite avec `-r1 --no-tile-size-limit --no-feature-limit`, puis fusionnée avec `tile-join`. `--drop-densest-as-needed` agit tuile par tuile et supprimait les points QA quand d'autres couches remplissaient la tuile entre z9 et z11.
- Interface : couche visible dès z12, points de 12 px de z12 à z18, interrupteur dans « Analyse spatiale et qualité » avec un filtre `missing_way` / `missing_tag`, popup avec le type de problème et le nom de la rue.
- `_load_crossing_nodes` lit le fichier avec le module `json` plutôt qu'avec `gpd.read_file`, parce que `highways.geojson` mélange Points et LineStrings et que certaines versions de pyogrio le refusent. Il déballe aussi les FeatureCollection imbriquées que jq pouvait produire.
- Correction dans `build.yml` : l'étape « Slim highways » produisait `features: <FeatureCollection>` au lieu d'un tableau, à cause d'un suffixe `| {type, features: .}` en trop après `.features |= map(...)`. Tippecanoe l'acceptait, pyogrio non.
- `crossing:continuous` est ajouté aux propriétés conservées, pour détecter les traversées surélevées.

## 2026-06-01

### Fusion des couches « forced » dans `flow_edges` (#24)

- Les couches PMTiles `forced_segments` et `forced_cycleway` sont retirées. La propriété `highway=*`, ajoutée à `flow_edges`, porte la même information et permet de styler les flux par type de route.
- `flow_edges.geojson` exporte `highway` (`primary`, `residential`, `tertiary`…). La couche PMTiles contient donc `highway`, `flow_pct` et `infra_type`.
- `forced_segments.geojson` et `forced_cycleway.geojson` sont toujours produits avec toutes leurs propriétés (`flow`, `length_m`…) et publiés comme artifacts CI pour les statistiques, mais ne sont plus dans le PMTiles.
- L'épaisseur des flux sur route (`flow-road`) dépend de `highway=*` : à flux égal, une primaire est plus épaisse qu'une résidentielle.
- Curseur « Flux route min » dans l'en-tête : masque les segments `flow-road` dont le `flow_pct` est sous le seuil (0 à 95 %, pas de 5). Sans effet sur `flow-ped` et `flow-cycleway`. Le filtre est toujours combiné avec `["==", infra_type, "road"]`, sinon les segments piétons basculaient dans la couche rouge.
- Couche `highways` allégée : une étape `jq` dans `build.yml` ne garde que les propriétés utilisées par l'interface (`highway`, `amenity`, `name`, `foot`, `bicycle`, `access`, `segregated`). Les autres tags (surface, lit, tram, steps:count…) sortent du PMTiles.

## 2026-04-28

### Tags sidewalk

- Nouvelle couche. En plus de l'analyse spatiale, qui repère les trottoirs séparés mappés, on lit les tags sidewalk de la route elle-même. Combinée aux autres couches, elle montre les lacunes et les erreurs de tags.

## 2026-04-24

### Refactoring

- Le script Python d'environ 400 lignes intégré à `build.yml` est découpé en 7 modules dans `scripts/` : `config.py`, `clean_osm.py`, `build_graph.py`, `sample_od.py`, `routing.py`, `export.py`, `main.py` ([#9](https://github.com/PasLoin/Brussels-Pedestrian-Network/issues/9)).
- `surface_cat` devient `infra_type`, pour ne pas confondre avec le tag OSM `surface`, qui décrit le revêtement.

### Corrections d'algorithme

- Les cycleways avec `foot=yes` ne sont plus classées dans `forced_cycleway`. Nouveau type `cycleway_foot_yes`, distinct de `cycleway_no_foot`, dans une seule couche de flux (un interrupteur, deux couleurs) ([#6](https://github.com/PasLoin/Brussels-Pedestrian-Network/issues/6)).
- `foot`, `sidewalk`, `sidewalk:left`, `sidewalk:right` et `segregated` sont ajoutés à `useful_tags_way` pour survivre à la simplification OSMnx. `_first_str()` gère les `NaN` que produit la fusion de segments.
- Adresses : extraction avec `nw/addr:housenumber` au lieu de `n/`. Les bâtiments (ways) sont réduits à leur centroïde. L'avenue de Messidor passe de 16 à 163 adresses.

### Accrochage et échantillonnage

- Les points OD s'accrochent à l'arête la plus proche (distance point-segment) et non plus au nœud le plus proche. Cela corrige les faux négatifs sur les rues avec un trottoir d'un seul côté. Repli sur le nœud le plus proche si plus de deux arêtes sont à distance quasi égale ([#14](https://github.com/PasLoin/Brussels-Pedestrian-Network/issues/14)).
- `POINTS_PER_SIDE=5` est remplacé par un intervalle (`OD_SAMPLE_INTERVAL_M`, 100 m par défaut) : un point par intervalle et par côté de rue, donc un nombre de points proportionnel à la longueur de la rue.

### Nouvelle couche : trottoir d'un seul côté

- Pour chaque segment de route, on cherche de chaque côté des footways parallèles (±35°) qui couvrent au moins 40 % de la longueur.
- Les `highway=service` et les routes qui ont déjà `sidewalk:left` ou `sidewalk:right` sont exclues.
- Les arêtes dirigées sont dédoublonnées à l'export.
- Couche masquée par défaut, section « Analyse spatiale » de la légende.

### PMTiles

- `MIN_FLOW_THRESHOLD=5` : les arêtes avec moins de 5 passages sortent de `flow_edges`.
- `flow_edges` ne garde que `flow_pct` et `infra_type` (5 propriétés auparavant). Les couches `forced_*` gardent tout.
- Les adresses ne sont plus dans le PMTiles ; elles ne servent qu'au build.
- `MIN_ZOOM` passe de 8 à 9.
- `--no-feature-limit` et `--no-tile-size-limit` remis, la taille restant sous 100 MB.
- L'archive passe d'environ 142 MB à 58 MB.

### Interface

- Popup des flux réduit au type d'infrastructure et au flux relatif.
- Popup des trottoirs d'un seul côté avec le nom de la rue.
- Légende en trois sections : « Routage simulé », « Analyse spatiale », « Réseau de base ».
- Navigation dans le navigateur : la catégorie 3 (`cycleway_foot_yes`) est dessinée en bleu et comptée comme piétonne dans le résumé de l'itinéraire.
