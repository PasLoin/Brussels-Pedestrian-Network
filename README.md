# Brussels Pedestrian Network

Application web destinée aux contributeurs OpenStreetMap confirmés pour analyser la continuité du réseau piéton à Bruxelles et identifier les ruptures de connectivité.

## Objectif

Cet outil aide à repérer les zones où le réseau piéton semble incomplet dans OpenStreetMap. L enjeu principal est de détecter les discontinuités qui empêchent une continuité logique entre rues, traversées, accès et espaces publics.

## Algorithme utilisé dans le GitHub Action

Le traitement principal est exécuté dans le workflow `.github/workflows/build.yml`.

### 1. Construction du graphe réseau

- Le workflow filtre un extrait OSM de Bruxelles avec une liste étendue de voies marchables et routières potentiellement praticables à pied.
- Les données filtrées sont converties en graphe avec OSMnx, puis reprojetées dans un système métrique pour les calculs de distance.
- Le graphe est converti en graphe orienté igraph pour accélérer le calcul d itinéraires.
- Chaque arête reçoit un coût pondéré égal à `longueur x pénalité` selon le type de voie.

Exemples de pondération utilisés:

- infrastructure piétonne dédiée comme footway ou pedestrian: coût faible
- steps et living_street: coût intermédiaire
- routes motorisées comme tertiary, secondary, primary: coût élevé
- cycleway sans autorisation piétonne explicite: coût pénalisé

Des exclusions sont aussi appliquées:

- arêtes avec `foot=no` retirées
- arêtes avec `access=no` retirées
- arêtes avec `access=private` conservées mais fortement pénalisées

### 2. Génération des demandes de déplacement

- Les points origine destination sont échantillonnés à partir des adresses OSM, rue par rue.
- Règle utilisée actuellement, en version simple:
  - rue avec peu d adresses, de 1 à 4: on prend une seule adresse, au milieu de la rue
  - rue avec 5 adresses ou plus: on prend trois adresses, une au début de la rue, une au milieu et une vers la fin
- Ce choix dépend du nombre d adresses disponibles par rue, pas de la longueur géométrique de la rue.
- Les points sont projetés sur le noeud de graphe le plus proche.
- Des paires origine destination aléatoires sont générées avec contrainte de distance à vol d oiseau.
- Le nombre de paires est plafonné pour maîtriser le temps de calcul.

Paramètres de configuration dans `.github/workflows/build.yml`:

- `MAX_OD_PAIRS`: nombre maximal de paires origine destination générées, valeur actuelle 50000
- `MAX_OD_DISTANCE_KM`: distance maximale à vol d oiseau entre origine et destination, valeur actuelle 5 km

### 3. Calcul des chemins et des flux

- Le routage est fait avec igraph en plus court chemin pondéré.
- Les paires sont regroupées par source pour lancer un Dijkstra par source au lieu d un Dijkstra par paire.
- Le passage sur chaque arête incrémente un compteur de flux.
- Les flux servent à repérer les segments non piétons mais utilisés par les trajets simulés.
- Le seuil de flux élevé est calculé sur le top `TOP_RANK_PCT` pour cent des arêtes non nulles, valeur actuelle 5 pour cent.

### 4. Sorties produites

Le workflow produit plusieurs couches GeoJSON ensuite intégrées dans `pedestrian.pmtiles`:

- `flow_edges.geojson`: intensité de flux par arête
- `forced_segments.geojson`: flux élevé sur routes non piétonnes classiques, par exemple tertiary ou primary
- `forced_cycleway.geojson`: flux élevé sur cycleways sans droit piéton explicite
- `street_scores.geojson`: score de marchabilité agrégé par rue

## Détection des trous dans le réseau

La détection des trous repose donc sur une lecture par flux et continuité topologique.

- Si de nombreux trajets pondérés passent par des segments non piétons, cela signale une absence probable de liaison piétonne mieux adaptée.
- Si la connectivité locale force des détours coûteux, cela peut indiquer un chaînon manquant dans le réseau.
- Les couches `forced_segments` et `forced_cycleway` sont les principaux indicateurs de trous potentiels à vérifier.
- La distinction entre les deux couches vient de la pondération et de la classification des arêtes:
  - route non piétonne classique: coût très élevé selon type routier, classée dans `forced_segments`
  - cycleway sans tag piéton explicite: coût pénalisé mais souvent inférieur à une route majeure, classée dans `forced_cycleway`

Cette détection produit des hypothèses de manque de données. Chaque signalement doit être validé avant modification.

## Ce que montre la carte

- Les segments piétons présents dans OpenStreetMap.
- Les flux de déplacement simulés sur le graphe de marche.
- Les zones où la continuité du réseau paraît interrompue.
- Les endroits à vérifier en priorité pour améliorer la complétude du graphe piéton.

## Pour qui

- Contributeurs OpenStreetMap confirmés.

## Utilisation

1. Ouvrir l application dans un navigateur.
2. Examiner les couches de flux et les segments signalés.
3. Vérifier localement ou avec des sources compatibles OpenStreetMap.
4. Corriger les données dans OpenStreetMap avec un commentaire de modification explicite.
5. Contrôler à nouveau la zone dans l application après mise à jour des données.

Lien public de l application:

https://pasloin.github.io/Brussels-Pedestrian-Network/

## Bonnes pratiques OpenStreetMap

- Respecter les règles de vérifiabilité et de traçabilité des modifications.
- Éviter les ajouts incertains sans confirmation terrain ou source autorisée.
- Documenter clairement les corrections liées aux discontinuités du réseau piéton.

## Limites de l algorithme

- Le modèle dépend des tags OSM présents. Une erreur de tag influence directement le graphe et les flux calculés.
- Les pondérations de coût sont des choix méthodologiques. Elles orientent les chemins simulés et peuvent sur ou sous estimer certaines pratiques piétonnes.
- L échantillonnage des origines destinations à partir des adresses ne représente pas tous les usages réels de la marche.
- Le plafonnement du nombre de paires origine destination améliore la performance mais réduit la couverture exhaustive du réseau.
- Les résultats peuvent contenir des faux positifs et des faux négatifs.
- Une rupture détectée ne signifie pas automatiquement une erreur. Elle peut provenir d un choix de modélisation légitime.
- La validation humaine reste indispensable avant toute édition.

## Licence

Programme: MIT License.

Texte complet: https://opensource.org/licenses/MIT

Données cartographiques: Open Database License ODbL.

Copyright des données: © OpenStreetMap contributors.
