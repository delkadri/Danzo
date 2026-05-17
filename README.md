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

Le fichier `backend/data/words.json` n'est plus la base de donnees du projet. Il sert uniquement de seed initial pour PostgreSQL.

## Run avec Docker

```bash
docker compose up --build
```

Services :

- Frontend : `http://localhost:8080`
- Backend : `http://localhost:5000`
- Swagger : `http://localhost:5000/api/docs`
- PostgreSQL : `localhost:5432`

## Deploiement avec un seul domaine

En production, le frontend Nginx peut servir l'application sur un seul domaine public
et proxifier `/api` et `/socket.io` vers le backend en interne. Dans ce mode, il n'est
pas necessaire d'avoir un sous-domaine dedie pour l'API.

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

## APIs utiles

- `GET /api/health`
- `GET /api/meta`
- `GET /api/catalog/stats`
- `GET /api/words/{category}?difficulty=medium&count=20`
- `POST /api/admin/catalog/reseed`
