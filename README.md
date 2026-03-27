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
