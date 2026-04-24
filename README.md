# Brussels Pedestrian Network

Application web destinée aux contributeurs OpenStreetMap confirmés pour analyser la continuité du réseau piéton à Bruxelles et identifier les ruptures de connectivité.

## Objectif

Cet outil aide à repérer les zones où le réseau piéton semble incomplet dans OpenStreetMap. L'enjeu principal est de détecter les discontinuités qui empêchent une continuité logique entre rues, traversées, accès et espaces publics.

## Architecture du projet

Le traitement est organisé en modules Python dans le dossier `scripts/` :

| Fichier | Rôle |
|---|---|
| `config.py` | Paramètres configurables (lus depuis les variables d'environnement) |
| `clean_osm.py` | Nettoyage XML OSM : coupe les ways aux barrières bloquantes |
| `build_graph.py` | Construction du graphe OSMnx → igraph avec pondération |
| `sample_od.py` | Échantillonnage des adresses et snapping sur le graphe |
| `routing.py` | Génération des paires OD et routage Dijkstra |
| `export.py` | Export GeoJSON (flux, segments forcés, scores, graphe client) |
| `sidewalk_gap.py` | Détection spatiale des trottoirs dessinés d'un seul côté |
| `main.py` | Orchestrateur : enchaîne toutes les étapes |

Le workflow `.github/workflows/build.yml` exécute `python3 scripts/main.py` après les étapes d'extraction OSM.

## Algorithme

### 1. Construction du graphe réseau

Le workflow filtre un extrait OSM de Bruxelles avec une liste étendue de voies marchables et routières potentiellement praticables à pied. Les données filtrées sont converties en graphe avec OSMnx, puis reprojetées en Lambert belge (EPSG:31370) pour les calculs de distance. Le graphe est converti en graphe orienté igraph pour accélérer le calcul d'itinéraires.

Chaque arête reçoit un coût pondéré égal à `longueur × pénalité` selon le type de voie :

- Infrastructure piétonne dédiée (footway, pedestrian) : coût faible
- Steps et living_street : coût intermédiaire
- Routes motorisées (tertiary, secondary, primary) : coût élevé
- Cycleway avec `foot=yes/designated/permissive` : coût faible (traité comme infra piétonne)
- Cycleway sans autorisation piétonne explicite : coût pénalisé

Exclusions appliquées :

- Arêtes avec `foot=no` : retirées
- Arêtes avec `access=no` ou `access=private` : retirées
- Ways coupés aux barrières avec `barrier=gate` + `access=private` ou `access=no`

Les tags `foot`, `sidewalk`, `sidewalk:left` et `sidewalk:right` sont explicitement préservés lors de l'import OSMnx pour éviter leur perte pendant la simplification du graphe.

### 2. Échantillonnage des origines-destinations

Les points OD sont échantillonnés à partir des adresses OSM (nœuds **et** polygones de bâtiments, convertis en centroïdes). Pour chaque rue, les adresses sont séparées en côté pair et impair.

L'échantillonnage est **géographique** : les adresses de chaque côté sont projetées sur l'axe principal de la rue, puis découpées en bins de `OD_SAMPLE_INTERVAL_M` mètres (défaut : 100 m). Un point est choisi par bin par côté. Cela scale naturellement avec la longueur de la rue : une rue de 200 m donne ~2 points par côté, une avenue de 1,5 km donne ~15 points.

Chaque côté est échantillonné indépendamment : un bin avec 5 maisons paires et 0 impaires produit un point pair uniquement.

### 3. Snapping sur le graphe

Les points OD sont snappés sur l'**arête** la plus proche (distance point-segment) plutôt que sur le nœud le plus proche. Cela résout le problème des rues avec un trottoir dessiné d'un seul côté : une adresse au nord d'une route snappe sur l'arête route, tandis qu'une adresse au sud snappe sur le footway — purement par géométrie.

Si le résultat est ambigu (plus de 2 arêtes à distance quasi égale), le snapping retombe sur le nœud le plus proche.

### 4. Routage et flux

Le routage utilise igraph en plus court chemin pondéré. Les paires sont regroupées par source pour lancer un Dijkstra par source au lieu d'un Dijkstra par paire. Le passage sur chaque arête incrémente un compteur de flux.

Le seuil de flux élevé est calculé sur le top `TOP_RANK_PCT` % des arêtes non nulles. Les arêtes avec un flux inférieur à `MIN_FLOW_THRESHOLD` (défaut : 5) sont exclues de la sortie pour alléger le fichier PMTiles.

### 5. Classification des arêtes

Chaque arête reçoit un type d'infrastructure (`infra_type`) :

- `pedestrian` : infrastructure piétonne dédiée (footway, path, pedestrian…)
- `cycleway_foot_yes` : cycleway avec `foot=yes/designated/permissive`
- `cycleway_no_foot` : cycleway sans autorisation piétonne explicite
- `road` : route motorisée

Les cycleways avec `foot=yes` sont **exclus** de la couche `forced_cycleway` car ils sont praticables à pied par définition.

### 6. Détection des sidewalk gaps

Une analyse spatiale détecte les routes où un trottoir (footway) est dessiné d'un seul côté :

1. Pour chaque segment de route, la géométrie est décalée de 12 m à gauche et à droite
2. Dans chaque zone de recherche, seuls les footways **parallèles** à la route sont comptés (angle < 35°)
3. La longueur cumulée des footways parallèles doit couvrir au moins 40 % de la longueur du segment pour compter comme "trottoir présent"
4. Si un côté a un trottoir et l'autre non → gap détecté

Sont exclus de cette analyse :

- `highway=service` (allées, parkings)
- Les routes avec des tags explicites `sidewalk:left`, `sidewalk:right` ou `sidewalk` documentant la situation

Tous les paramètres (offset, rayon, angle, couverture) sont configurables dans le workflow.

### 7. Sorties produites

Le workflow produit plusieurs couches GeoJSON intégrées dans `pedestrian.pmtiles` :

- `flow_edges` : intensité de flux par arête (propriétés : `flow_pct`, `infra_type`)
- `forced_segments` : flux élevé sur routes non piétonnes (propriétés complètes)
- `forced_cycleway` : flux élevé sur cycleways sans droit piéton explicite
- `street_scores` : score de marchabilité agrégé par rue avec pénalité trottoir
- `sidewalk_gaps` : routes avec un trottoir dessiné d'un seul côté
- `highways` : réseau piéton de base (footway, cycleway, path…)

Un fichier `graph.json` est aussi produit pour la navigation client-side (Dijkstra dans le navigateur).

## Paramètres configurables

Tous les paramètres sont définis comme variables d'environnement dans `.github/workflows/build.yml` :

| Paramètre | Défaut | Description |
|---|---|---|
| `OD_SAMPLE_INTERVAL_M` | 100 | Un point OD tous les N mètres par côté de rue |
| `MIN_OD_DISTANCE_M` | 300 | Distance min entre paires OD |
| `MAX_OD_DISTANCE_KM` | 6 | Distance max entre paires OD |
| `MAX_OD_PAIRS` | 900000 | Nombre max de paires OD |
| `TOP_RANK_PCT` | 15 | Seuil de flux élevé (top N %) |
| `MIN_FLOW_THRESHOLD` | 5 | Flux min pour inclusion dans PMTiles |
| `WALK_SCORE_RADIUS_M` | 1000 | Rayon pour le score de marchabilité |
| `SIDEWALK_GAP_OFFSET_M` | 12 | Distance de recherche depuis l'axe de la route |
| `SIDEWALK_GAP_SEARCH_M` | 8 | Rayon autour de la ligne de recherche |
| `SIDEWALK_GAP_MAX_ANGLE` | 35 | Angle max pour considérer un footway parallèle |
| `SIDEWALK_GAP_MIN_COVERAGE` | 0.4 | Couverture min pour compter un trottoir |

## Ce que montre la carte

- Les segments piétons présents dans OpenStreetMap.
- Les flux de déplacement simulés sur le graphe de marche.
- Les zones où la continuité du réseau paraît interrompue.
- Les routes avec un trottoir dessiné d'un seul côté (sidewalk gaps).
- Les endroits à vérifier en priorité pour améliorer la complétude du graphe piéton.
- Un outil de navigation client-side pour visualiser les itinéraires piétons avec décomposition par type d'infrastructure.

## Pour qui

Contributeurs OpenStreetMap confirmés.

## Utilisation

1. Ouvrir l'application dans un navigateur.
2. Examiner les couches de flux et les segments signalés.
3. Activer la couche "Trottoir un seul côté" pour identifier les sidewalk gaps.
4. Vérifier localement ou avec des sources compatibles OpenStreetMap.
5. Corriger les données dans OpenStreetMap avec un commentaire de modification explicite.
6. Contrôler à nouveau la zone dans l'application après mise à jour des données.

Lien public de l'application :

https://pasloin.github.io/Brussels-Pedestrian-Network/

## Bonnes pratiques OpenStreetMap

- Respecter les règles de vérifiabilité et de traçabilité des modifications.
- Éviter les ajouts incertains sans confirmation terrain ou source autorisée.
- Documenter clairement les corrections liées aux discontinuités du réseau piéton.

## Limites de l'algorithme

- Le modèle dépend des tags OSM présents. Une erreur de tag influence directement le graphe et les flux calculés.
- Les pondérations de coût sont des choix méthodologiques. Elles orientent les chemins simulés et peuvent surestimer ou sous-estimer certaines pratiques piétonnes.
- L'échantillonnage des origines-destinations à partir des adresses ne représente pas tous les usages réels de la marche.
- Le plafonnement du nombre de paires OD améliore la performance mais réduit la couverture exhaustive du réseau.
- La détection des sidewalk gaps est géométrique : elle ne détecte pas les cas où un trottoir existe physiquement mais n'a pas été dessiné des deux côtés dans OSM.
- Les résultats peuvent contenir des faux positifs et des faux négatifs.
- Une rupture détectée ne signifie pas automatiquement une erreur. Elle peut provenir d'un choix de modélisation légitime.
- La validation humaine reste indispensable avant toute édition.

## Licence

Programme : [MIT License](https://opensource.org/licenses/MIT).

Données cartographiques : [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/).

© [OpenStreetMap contributors](https://www.openstreetmap.org/copyright).
