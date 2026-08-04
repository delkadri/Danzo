## Danzo

Danzo est un jeu de devinettes en temps reel qui se joue en equipes de 2. A chaque tour, un joueur fait deviner une liste de mots a son coequipier, qui doit les saisir le plus vite possible avant la fin du chrono. Le jeu gere les salons, les equipes, les scores et le classement en direct.

## Comment jouer

1. Un joueur cree une partie et partage le code du salon.
2. Les autres joueurs rejoignent le salon avec leur pseudo.
3. L'admin forme des equipes de 2 puis lance la partie.
4. A chaque tour, le joueur "Describer" choisit une categorie et une difficulte.
5. Le "Describer" voit les mots et doit les faire deviner oralement au "Guesser".
6. Le "Guesser" ecrit ses reponses dans les cases. Une reponse exacte donne plus de points, une reponse tres proche peut aussi rapporter des points.
7. Les tours s'enchainent entre les equipes jusqu'a ce qu'une equipe atteigne le score cible.

## Architecture

- `frontend/` : interface React + Socket.IO
- `backend/` : API Flask + Socket.IO
- `backend/main.py` : point d'entree du serveur
- `backend/app/realtime.py` : logique de jeu temps reel
- `backend/app/services/catalog_service.py` : service du catalogue de mots
- `backend/app/repositories/catalog_repository.py` : acces PostgreSQL

## Run avec Docker

```bash
docker compose up --build
```

Services :

- Frontend : `http://localhost:8080`
- Backend : `http://localhost:5000`
- Swagger : `http://localhost:5000/api/docs`
- PostgreSQL : `localhost:5432`

## Run local

### Base de donnees

```bash
docker compose up db -d
```

### Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Deploiement sur Vercel

Le depot contient une configuration Vercel multi-service :

- le frontend Vite est servi sur `/` ;
- l'API Flask est servie sur `/api` ;
- Socket.IO est servi sur `/socket.io`.

Dans Vercel, conserver le preset `Container`, le Root Directory `./` et laisser
Build Command, Output Directory et Install Command vides. Ajouter les variables
d'environnement suivantes avant le deploiement :

```env
SECRET_KEY=change_me
REST_ADMIN_TOKEN=change_me
DB_INIT_ON_STARTUP=false
REDIS_URL=rediss://default:password@host:port
REDIS_REQUIRED=true
ROOM_TTL_SECONDS=43200
```

`REDIS_URL` est obligatoire en production pour partager les salons et les
evenements Socket.IO entre les instances Vercel. Installer une integration
Redis (par exemple Upstash) depuis le Vercel Marketplace et connecter la base
au projet ; Vercel injecte alors `REDIS_URL`. Les salons expirent apres 12 heures
sans activite par defaut. `REDIS_REQUIRED=true` empeche la creation d'un salon
qui ne serait conserve que dans la memoire temporaire d'une instance Vercel.
Apres le deploiement, `GET /api/health` doit afficher `redis: "up"` et
`shared_rooms: true`.

Dans Vercel, la valeur de `REDIS_URL` doit normalement commencer par
`rediss://`. Ne pas inclure `redis-cli --tls -u` dans la variable. Le backend
accepte toutefois aussi la commande complete copiee depuis Upstash et en extrait
automatiquement l'URL TLS.

`DATABASE_URL` est facultative : sans base disponible, le jeu utilise
automatiquement `backend/data/words.json`. Pour utiliser PostgreSQL, ajouter
une URL hebergee (`postgresql://...`) et conserver `DB_INIT_ON_STARTUP=false`
sur Vercel afin de ne pas bloquer le demarrage du conteneur. Le service `db` de
`docker-compose.yml` est reserve au developpement local.

## APIs utiles

- `GET /api/health`
- `GET /api/meta`
- `GET /api/catalog/stats`
- `GET /api/words/{category}?difficulty=medium&count=20`
- `POST /api/admin/catalog/reseed`
