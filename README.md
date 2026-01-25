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
Stop
docker compose down

Restart
docker compose up

### idée pas importante :
- Change le bouton copy par le logo
- mettre mes cordonnées quelque part (credits)
- chnager les couleurs de UI (plus clair?)

### changement : 
- au lieu de mettre : Waiting for next describer to press Start Turn… met le nickname du describer à laplace du mot describer
