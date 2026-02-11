# Hocine Abed Portfolio

Portfolio personnel orienté **web scraping** et **backend FastAPI**, avec visualisation d'offres d'emploi (LinkedIn + Freework) stockées dans MongoDB.

## Points clés
- FastAPI + Jinja2 + MongoDB (Motor async)
- Pages jobs avec filtres, pagination et affichage de date relative (`Europe/Paris`)
- Design unifié (navbar/footer/pages)
- Optimisations de performance sur `/jobs/linkedin` et `/jobs/freework`
  - requêtes allégées
  - tri optimisé
  - filtres mis en cache en mémoire

## Routes principales
- `/` : page d'accueil
- `/intro` : intro landing page
- `/projects` : projets scraping
- `/resume` : CV
- `/contact` : contact
- `/jobs/linkedin` : offres LinkedIn
- `/jobs/freework` : offres Freework
- `/jobs/freework/{job_id}` : détail d'une offre Freework

## Stack
- Python 3.10+
- FastAPI, Uvicorn
- Motor (MongoDB async)
- Jinja2, Tailwind CSS

## Installation
```bash
git clone <your-repo-url>
cd Personal-Website
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/macOS
# source venv/bin/activate
pip install -r requirements.txt
```

## Variables d'environnement
Créer un fichier `.env` à la racine:

```env
MONGO_URI=mongodb+srv://<username>:<password>@<cluster>/<db>?retryWrites=true&w=majority
MONGO_DB=scraping
MONGO_COLLECTION_LINKEDIN=linkedin
MONGO_COLLECTION_FREEWORK=freework
MONGO_COLLECTION_EMAIL=emails

# optionnel (cache filtres jobs, en secondes)
LINKEDIN_FILTER_CACHE_TTL_SECONDS=300
FREEWORK_FILTER_CACHE_TTL_SECONDS=300
```

## Lancement local
```bash
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Puis ouvrir:
- http://127.0.0.1:8000/

## Index MongoDB recommandés
```js
db.linkedin.createIndex({ country: 1, continent: 1, source: 1, posting_time: -1 })
db.freework.createIndex({ remote_mode: 1, published_at: -1, id: 1 })
```

## Déploiement (Docker)
```bash
docker build -t hocine-abed-portfolio .
docker run --env-file .env -p 8000:8000 hocine-abed-portfolio
```

## Notes
- Les données jobs sont supposées déjà collectées dans MongoDB (ce repo affiche/filtre ces données).
- Le style est responsive desktop/mobile.
