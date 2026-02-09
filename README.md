# Ziago Guess (Standalone)

A real-time multiplayer word guessing game inspired by Ziago.
No video call — only the game.

## Features
- Create/join rooms with a code
- Ready system + lobby
- Turn-based gameplay
- Before each turn: speaker chooses 1 category out of 2
- Simple guessing input (one guess at a time)
- Scoreboard (FFA + optional Team mode)
- Flask backend with Socket.IO
- Local JSON database (words.json)
- Dockerized
- Deployable on Railway

---

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

### changement : 

- data base not local
- Reconnect smart
