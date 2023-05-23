import os
import json
import httpx
import logging

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from starlette.responses import FileResponse
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel, conint
from starlette.responses import JSONResponse

# *****************************************************************************
#                  Some general constants and variables
# *****************************************************************************
NAME = 'Riverr API'
VERSION = '1.0.0'
DESCRIPTION = 'Backend for riverr'
URL_PREFIX: str = os.getenv("URL_PREFIX") or ""
SERVER_ADDRESS: str = os.getenv("SERVER_ADDRESS") or ""
EXPOSED_ADDRESS: str = "https://myserver.com/"

LOCAL_IP = "192.168.1.81"

RADARR_URL = f"http://{LOCAL_IP}:7878/api/v3"
RADARR_KEY = os.getenv("RADARR_KEY")

SONARR_URL = f"http://{LOCAL_IP}:8989/api/v3"
SONARR_KEY = os.getenv("SONARR_KEY")

TMDB_URL = "https://api.themoviedb.org/3"
TMDB_KEY = os.getenv("TMDB_KEY")
TMDB_POSTER_URL = "https://image.tmdb.org/t/p/original"

# *****************************************************************************
#                  FastAPI entry point declaration
# *****************************************************************************
rootapp = FastAPI()

app = FastAPI(openapi_url='/specification')
app.add_middleware(CORSMiddleware, allow_origins=["*"], 
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(title=NAME, version=VERSION, 
        description=DESCRIPTION, routes=app.routes,)
    if SERVER_ADDRESS != "":
        openapi_schema["servers"] = [
            {"url": EXPOSED_ADDRESS + URL_PREFIX, 
            "description": "Riverr API"},
        ]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi
rootapp.mount(URL_PREFIX, app)
logger = logging.getLogger("uvicorn.error")
logger.info('Starting app with URL_PREFIX=' + URL_PREFIX)

# *****************************************************************************
#                  The classes defining the API input and output models
# *****************************************************************************

class Media:
    def __init__(self, name, synopsis, rating, length, thumbnail, year, watched=True):
        self.name = name
        self.synopsis = synopsis 
        self.rating = rating
        self.length = length
        self.thumbnail = thumbnail
        self.watched = watched
        self.year = year

    def to_dict(self):
        return {
            "name": self.name,
            "synopsis": self.synopsis,
            "rating": self.rating,
            "length": self.length,
            "thumbnail": self.thumbnail,
            "watched": self.watched,
            "year": self.year,
        }

# *****************************************************************************
#                  Routes of the API
# *****************************************************************************

@app.on_event("startup")
def startup_event():
    pass
    
@app.get("/")
def info():
    return {'message': 'Welcome to the Riverr API.'}

@app.get("/getmovies")
async def get_radarr_movies():
    try:
        async with httpx.AsyncClient() as client:
            head = {"X-Api-Key": RADARR_KEY}
            response = await client.get(f"{RADARR_URL}/movie", headers=head)
            response.raise_for_status()
            movies_data = response.json()
            movies = [Media(str(m["title"]), 
                            str(m["overview"]), 
                            str(m["ratings"]["imdb"]["value"]), 
                            str(convert_runtime(m["runtime"])), 
                            str(retrieve_poster_url(m["images"])), 
                            str(m["year"])).to_dict() for m in movies_data]
            if not movies:
                return {"warning": "No movies found"}
            return movies
    except httpx.HTTPError as e:
        if e.response.status_code == 404:
            return {"warning": "Route not found"}
        else:
            return {"error": str(e)}
    except json.JSONDecodeError as e:
        return {"error": f"Failed to decode JSON: {str(e)}"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/gettv")
async def get_sonarr_series():
    try:
        async with httpx.AsyncClient() as client:
            head = {"X-Api-Key": SONARR_KEY}
            response = await client.get(f"{SONARR_URL}/series", headers=head)
            response.raise_for_status()
            series_data = response.json()
            series = [Media(str(s["title"]), 
                            str(s["overview"]), 
                            str(s["ratings"]["value"]), 
                            str(s["statistics"]["episodeCount"]),
                            str(retrieve_poster_url(s["images"])), 
                            str(s["year"])
                        ).to_dict() for s in series_data]
            if not series:
                return {"warning": "No series found"}
            return series
    except httpx.HTTPError as e:
        if e.response.status_code == 404:
            return {"warning": "Route not found"}
        else:
            return {"error": str(e)}
    except json.JSONDecodeError as e:
        return {"error": f"Failed to decode JSON: {str(e)}"}
    except Exception as e:
        return {"error": str(e)}
    
@app.get("/getmovies-reco") # TODO: Fix the issue where no length are found for movies
async def discover_radarr_movies():
    try:
        async with httpx.AsyncClient() as client:
            head = {"X-Api-Key": RADARR_KEY}
            response = await client.get(f"{RADARR_URL}/movie", headers=head)
            response.raise_for_status()
            movies_data = response.json()
            genre = retrieve_genre(movies_data)
            id = await get_tmdb_genre_from_name(genre)
            if id == -1:
                return {"warning": "No movies to recommend for: " + genre}
            else:
                movies_reco = await get_tmdb_recomendations(id, "movie")
                movies = [Media(str(m["original_title"]), 
                                str(m["overview"]), 
                                str(m["vote_average"]), 
                                str("N/A"), 
                                str(TMDB_POSTER_URL + m["poster_path"]), 
                                str(m["release_date"][:4]),
                                watched=False).to_dict() for m in movies_reco]
                if not movies:
                    return {"warning": "No movies to recommend for: " + genre}
                return movies
    except httpx.HTTPError as e:
        if e.response.status_code == 404:
            return {"warning": "Route not found"}
        else:
            return {"error": str(e)}
    except json.JSONDecodeError as e:
        return {"error": f"Failed to decode JSON: {str(e)}"}
    except Exception as e:
        return {"error": str(e)}

@app.get("/gettv-reco") # TODO: Fix the issue where no recommendations are found for tv
async def discover_sonarr_movies():
    try:
        async with httpx.AsyncClient() as client:
            head = {"X-Api-Key": SONARR_KEY}
            response = await client.get(f"{SONARR_URL}/series", headers=head)
            response.raise_for_status()
            series_data = response.json()
            genre = retrieve_genre(series_data)
            id = await get_tmdb_genre_from_name(genre)
            if id == -1:
                return {"warning": "No series to recommend for: " + genre}
            else:
                series_reco = await get_tmdb_recomendations(id, "tv")
                series = [Media(str(s["original_title"]), 
                                str(s["overview"]), 
                                str(s["vote_average"]), 
                                str("N/A"), 
                                str(TMDB_POSTER_URL + s["poster_path"]), 
                                str(s["release_date"][:4]),
                                watched=False).to_dict() for s in series_reco]
                if not series:
                    return {"warning": "No series to recommend for: " + genre}
                return series
    except httpx.HTTPError as e:
        if e.response.status_code == 404:
            return {"warning": "Route not found"}
        else:
            return {"error": str(e)}
    except json.JSONDecodeError as e:
        return {"error": f"Failed to decode JSON: {str(e)}"}
    except Exception as e:
        return {"error": str(e)}

# *****************************************************************************
#                  Utility functions
# *****************************************************************************

def convert_runtime(min: str):
    try:
        min = int(min)
        hours = min // 60
        minutes = min % 60
        return f"{hours}h {minutes}m"
    except:
        logger.error("Failed to convert runtime")
        return min

def retrieve_poster_url(images: list):
    for image in images:
        if image["coverType"] == "poster":
            return image["remoteUrl"]
    logger.error("No poster found")
    return None

def retrieve_genre(movies: list):
    genres = {}
    for movie in movies:
        for genre in movie["genres"]:
            if genre in genres:
                genres[genre] += 1
            else:
                genres[genre] = 1
    return max(genres, key=genres.get)

async def get_tmdb_genre_from_name(genre_name):
    try:
        async with httpx.AsyncClient() as client:
            head = {"Authorization": "Bearer " + TMDB_KEY,
            "accept": "application/json"}
            params = {"language": "en"}
            response = await client.get(f"{TMDB_URL}/genre/movie/list",
                                        headers=head, params=params)
            response.raise_for_status()
            
            genres = response.json()["genres"]
            for genre in genres:
                if genre["name"].lower() == genre_name.lower():
                    return genre["id"]
            return -1
    except Exception as e:
        logger.error(e)
        return -1
    
async def get_tmdb_recomendations(genre_id, type):
    try:
        async with httpx.AsyncClient() as client:
            url = f"https://api.themoviedb.org/3/discover/{type}"
            head = {"Authorization": "Bearer " + TMDB_KEY,
            "accept": "application/json"}
            params = {"with_genres": genre_id,
                      "language": "en",
                      "page": 2}
            response = await client.get(f"{TMDB_URL}/discover/{type}", 
                                        headers=head, params=params)
            response.raise_for_status()
            return response.json()["results"]
    except Exception as e:
        logger.error(e)
        return -1
    
# Routes Films
 # OK - Get la liste des films watched
 # OK - Get la liste des films recommandés
 # - Get la liste de résultat d'une recherche de films
 # - Ajouter un film à la liste des watch
 # - Retirer un film de la liste des watch

# Routes Series
 # OK - Get la liste des séries watched
 # PRESQUE - Get la liste des séries recommandés
 # - Get la liste de résultat d'une recherche de séries 
 # - Ajouter une séries à la liste des watch
 # - Retirer une séries de la liste des watch

# Route deluge
 # - Get les torrents et leurs états
 # - Modifier l'état d'un torrent (On va dire juste pause, delete)
 # - Ajouter un torrent depuis un lien magnet

#Route jackett (euh frérot jsp trop?)
 # - Get la liste des trackers
 # - Modifier l'url d'un tracker ?