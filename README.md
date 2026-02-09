## Local run (no Docker)

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py

### docker

Build
docker compose build

Stop
docker compose down

Restart
docker compose up

### Bonus :
- reduire la taille du bouton Leave
- logo in the ranking very ugly
- mettre mes cordonnées quelque part (credits)
- changer les couleurs de UI (plus clair?)
- enlever des detailles
- animations / micro-interactions mobile (haptics / vibration / sound)
- logs

### Obligatoire : 

- pagination
- vrai base de donnée
- API REST
- Deploiment