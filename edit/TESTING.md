# Tests de l'édition des trottoirs

Ce fichier n'est pas publié sur le site (`build_site.py` ignore les `*.md` des dossiers copiés).

## Environnements

| Environnement | Page | API | Page de retour OAuth |
|---|---|---|---|
| `dev` | `test-api/devtest.html` | `https://master.apis.dev.openstreetmap.org` | `test-api/land.html` |
| `prod` | à venir (P4) | `https://api.openstreetmap.org` | `land.html` |

L'environnement d'une page est fixé par l'attribut `data-edit-env` de `<html>`, posé par `build_site.py`. La configuration vit dans `edit/env.js`.

## Enregistrer l'application OAuth dev

Le serveur dev est réinitialisé périodiquement, applications OAuth comprises. Si la connexion dev échoue d'un coup (`invalid_client`, page d'erreur OSM dans la popup), refaire cette procédure.

1. Se connecter (ou recréer un compte) sur https://master.apis.dev.openstreetmap.org.
2. Ouvrir « Mes paramètres » → « Applications OAuth 2 » → « Enregistrer une nouvelle application ».
3. Remplir :
   - Nom : `Brussels Pedestrian Network (devtest)`
   - URI de redirection, une par ligne :
     - `https://pasloin.github.io/Brussels-Pedestrian-Network/test-api/land.html`
     - `http://127.0.0.1:8000/test-api/land.html`
   - Application confidentielle : **décochée** (client public, PKCE, aucun secret).
   - Permissions : « Lire les préférences de l'utilisateur » (`read_prefs`) et « Modifier la carte » (`write_api`), rien d'autre.
4. Copier l'identifiant client dans `edit/env.js`, champ `ENVS.dev.clientId`. Ne jamais copier de secret : il n'y en a pas pour un client public.
5. Commit, push, attendre le déploiement de `site.yml`.

L'URI de redirection doit correspondre exactement, slash final et protocole compris.

## Jeu de test sur le serveur dev

Les données du serveur dev disparaissent aussi aux réinitialisations, et leurs IDs n'ont rien à voir avec la production ni avec les PMTiles.

1. Ouvrir iD sur le serveur dev : https://master.apis.dev.openstreetmap.org/edit?editor=id#map=17/50.8283/4.5923
2. Créer au moins :
   - trois `highway=residential` sans aucun tag `sidewalk*` (candidats) ;
   - une `highway=residential` avec `sidewalk:both=separate` (non candidate) ;
   - une `highway=tertiary` sans tag `sidewalk*` (non candidate, hors liste blanche).
3. Noter les IDs des ways dans le tableau ci-dessous pour la checklist.

| Rôle | Way ID dev |
|---|---|
| Candidat 1 | |
| Candidat 2 | |
| Candidat 3 | |
| Residential déjà taguée | |
| Tertiary sans tag | |

## Tester en local

```
python3 build_site.py --out _site
cd _site && python3 -m http.server 8000 --bind 127.0.0.1
```

Ouvrir `http://127.0.0.1:8000/test-api/devtest.html#17/50.8283/4.5923`. Les PMTiles ne sont pas présentes en local : le fond s'affiche, les couches du réseau non, la couche des candidats si.

## Checklist manuelle P1

À rejouer deux fois de suite avant de passer la porte de P1.

- [ ] La console ne montre aucune violation CSP au chargement de `devtest.html`.
- [ ] Sous le zoom 17, le panneau indique de zoomer et aucune requête `map` ne part vers le serveur dev.
- [ ] Au zoom 17 sur le jeu de test, les trois candidats apparaissent en magenta, les deux non candidats non.
- [ ] Un clic sur un candidat affiche ID, version, dernier auteur, tags, et « éditable ».
- [ ] Après avoir ajouté `sidewalk:both=no` sur un candidat dans iD dev, un nouveau clic affiche « déjà corrigé depuis » (la couche se met à jour au prochain déplacement).
- [ ] « Se connecter à OSM » ouvre la popup du serveur dev ; après autorisation, le panneau affiche le pseudo dev.
- [ ] Refuser l'autorisation dans la popup affiche « connexion échouée ou annulée », sans blocage.
- [ ] Fermer la popup sans terminer, puis « Relancer la connexion », fonctionne sans attendre.
- [ ] Ouvrir `test-api/land.html?code=x` directement affiche « aucune connexion n'a été lancée ».
- [ ] Garde R1 : se connecter sur `devtest.html`, puis écrire à la main `localStorage["bpn.authEnv"] = "prod"` et recharger ; la session doit avoir disparu.
- [ ] « Se déconnecter » vide `__osmAuth` et `bpn.authEnv`.
