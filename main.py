import os
import json
import httpx
import aiohttp
import logging

from typing import Any, Dict
from fastapi import FastAPI, HTTPException
from fastapi.openapi.utils import get_openapi
from starlette.middleware.cors import CORSMiddleware

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

DELUGE_URL = f"http://{LOCAL_IP}:8112/json"
DELUGE_KEY = os.getenv("DELUGE_KEY")

JACKETT_API_URL = f"http://{LOCAL_IP}:9117/api/v2.0/indexers"
# f"http://{LOCAL_IP}:9117/api/v2.0/indexers/all/results/torznab" ??
JACKETT_KEY = os.getenv("JACKETT_KEY")

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
async def startup_event():
    result = await deluge_rpc("auth.login", DELUGE_KEY)
    if not result:
        raise Exception("Failed to authenticate to Deluge server")

@app.get("/")
def info():
    return {'message': 'Welcome to the Riverr API.'}

# *****************************************************************************
#                  Radarr routes
#
#   - Get la liste des films watched                        OK
#   - Get la liste des films recommandés                    OK
#   - Get la liste de résultat d'une recherche de films     OK
#   - Ajouter un film à la liste des watch                  OK
#   - Retirer un film de la liste des watch                 TEST

# curl -X GET "http://localhost:3000/getmovies"
@app.get("/getmovies")
async def get_radarr_movies():
    try:
        async with httpx.AsyncClient() as client:
            head = {"X-Api-Key": RADARR_KEY}
            response = await client.get(f"{RADARR_URL}/movie", headers=head)
            response.raise_for_status()
            m_data = response.json()
            movies = [Media(str(get_title(m)), 
                            str(get_overview(m)), 
                            str(get_rating(m["ratings"])), 
                            str(get_runtime(m["runtime"])), 
                            str(get_poster_url(m["images"])), 
                            str(get_year(m))).to_dict() for m in m_data]
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

# curl -X GET "http://localhost:3000/recomovies"
@app.get("/recomovies")
async def discover_radarr_movies():
    try:
        async with httpx.AsyncClient() as client:
            head = {"X-Api-Key": RADARR_KEY}
            response = await client.get(f"{RADARR_URL}/movie", headers=head)
            response.raise_for_status()
            m_data = response.json()
            genre = get_genre(m_data)
            id = await get_tmdb_genre_from_name(genre)
            if id == -1:
                return {"warning": "No movies to recommend for: " + genre}
            else:
                m_data = await get_tmdb_recomendations(id, "movie")
                movies = [Media(str(m["original_title"]), 
                                str(get_overview(m)), 
                                str(m["vote_average"]), 
                                str("N/A"), 
                                str(TMDB_POSTER_URL + m["poster_path"]), 
                                str(m["release_date"][:4]),
                                watched=False).to_dict() for m in m_data]
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

# curl -X GET -d '{"title":"Avengers"}' "http://localhost:3000/searchmovies"
@app.get("/searchmovies")
async def search_radarr_movies(title: str):
    try:
        async with httpx.AsyncClient() as client:
            head = {"X-Api-Key": RADARR_KEY}
            params = {"term": title}
            response = await client.get(f"{RADARR_URL}/movie/lookup", 
                                        headers=head, params=params)
            response.raise_for_status()
            m_data = response.json()
            movies = [Media(str(get_title(m)),
                            str(get_overview(m)),
                            str(get_rating(m["ratings"])),
                            str(get_runtime(m["runtime"])),
                            str(get_poster_url(m["images"])),
                            str(get_year(m)),
                            watched=False).to_dict() for m in m_data]
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

# curl -X POST -d '{"title":"Gladiator"}' "http://localhost:3000/addmovies"
@app.post("/addmovies")
async def add_radarr_movies(title: str):
    try:
        async with httpx.AsyncClient() as client:
            head = {"X-Api-Key": RADARR_KEY}
            data = {
                "title": title,
                "tmdbId": await get_tmdb_id_from_title(title),
                "qualityProfileId": 1,
                "rootFolderPath": "/movie",
                "monitored": True,
            }
            response = await client.post(f"{RADARR_URL}/movie", 
                                         headers=head, 
                                         json=data)
            if response.status_code == 201:
                return {"success": f"Movie {title} added to watchlist"}
            else:
                response.raise_for_status()
    except httpx.HTTPError as e:
        if e.response.status_code == 404:
            return {"warning": "Route not found"}
        if e.response.status_code == 400:
            return {"warning": "Movie already in watchlist or invalid title"}
        else:
            return {"error": str(e)}
    except json.JSONDecodeError as e:
        return {"error": f"Failed to decode JSON: {str(e)}"}
    except Exception as e:
        return {"error": str(e)}

# TODO: TEST WITH curl -X DELETE -d '{"title":"Gladiator"}' "http://localhost:3000/removemovies"
@app.delete("/removemovies")
async def remove_radar_movies_from_watch_list(title: str):
    try:
        async with httpx.AsyncClient() as client:
            head = {"X-Api-Key": RADARR_KEY}
            response = await client.get(f"{RADARR_URL}/movie", headers=head)
            response.raise_for_status()
            m_data = response.json()
            movie_id = None
            for movie in m_data:
                if get_title(movie).lower() == title.lower():
                    movie_id = movie["id"] # maybe not "id" to look for ?
                    break
            if movie_id is None:
                return {"warning": "Movie not found"}
            response = await client.delete(f"{RADARR_URL}/movie/{movie_id}",
                                           headers=head)
            response.raise_for_status()
            return {"success": "Movie removed from watch list"}
    except httpx.HTTPError as e:
        if e.response.status_code == 404:
            return {"warning": "Movie not found"}
        else:
            return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}

# *****************************************************************************
#                  Sonarr routes
# 
#   - Get la liste des séries watched                       OK
#   - Get la liste des séries recommandés                   NOK
#   - Get la liste de résultat d'une recherche de séries    OK
#   - Ajouter une séries à la liste des watch               ALMOST
#   - Retirer une séries de la liste des watch              TEST

# curl -X GET "http://localhost:3000/gettv"
@app.get("/gettv")
async def get_sonarr_series():
    try:
        async with httpx.AsyncClient() as client:
            head = {"X-Api-Key": SONARR_KEY}
            response = await client.get(f"{SONARR_URL}/series", headers=head)
            response.raise_for_status()
            s_data = response.json()
            series = [Media(str(get_title(s)), 
                            str(get_overview(s)), 
                            str(get_rating(s["ratings"])), 
                            str(s["statistics"]["episodeCount"]),
                            str(get_poster_url(s["images"])), 
                            str(get_year(s))
                        ).to_dict() for s in s_data]
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

# TODO: Fix the issue where no recommendations are found for tv
# curl -X GET "http://localhost:3000/recotv"
@app.get("/recotv")
async def discover_sonarr_series():
    try:
        async with httpx.AsyncClient() as client:
            head = {"X-Api-Key": SONARR_KEY}
            response = await client.get(f"{SONARR_URL}/series", headers=head)
            response.raise_for_status()
            s_data = response.json()
            genre = get_genre(s_data)
            id = await get_tmdb_genre_from_name(genre)
            if id == -1:
                return {"warning": "No series to recommend for: " + genre}
            else:
                s_data = await get_tmdb_recomendations(id, "tv")
                series = [Media(str(s["original_title"]), 
                                str(get_overview(s)), 
                                str(s["vote_average"]), 
                                str("N/A"), 
                                str(TMDB_POSTER_URL + s["poster_path"]), 
                                str(s["release_date"][:4]),
                                watched=False).to_dict() for s in s_data]
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

# curl -X GET -d '{"title":"Breaking Bad"}' "http://localhost:3000/searchtv"
@app.get("/searchtv")
async def search_sonarr_series(title: str):
    try:
        async with httpx.AsyncClient() as client:
            head = {"X-Api-Key": SONARR_KEY}
            params = {"term": title}
            response = await client.get(f"{SONARR_URL}/series/lookup", 
                                        headers=head, params=params)
            response.raise_for_status()
            s_data = response.json()            
            series = [Media(str(get_title(s)),
                           str(get_overview(s)),
                           str(get_rating(s["ratings"])),
                           str(s["statistics"]["episodeCount"]),
                           str(get_poster_url(s["images"])),
                           str(get_year(s)),
                           watched=False).to_dict() for s in s_data]
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
    pass

# curl -X POST -d '{"title":"Friends"}' "http://localhost:3000/addtv"
@app.post("/addtv") 
async def add_sonarr_series(title: str, year: int):
    try:
        async with httpx.AsyncClient() as client:
            head = {"X-Api-Key": SONARR_KEY}
            data = {
                "title": title,
                "tvdbId": await get_tvdb_id_from_title(title),
                "qualityProfileId": 1,
                "rootFolderPath": "/tv",
                "monitored": True,
                "seasonFolder": True,
                "addOptions": {
                    "ignoreEpisodesWithFiles": False,
                    "ignoreEpisodesWithoutFiles": False,
                    "searchForMissingEpisodes": True,
                },
                "images": [],
                "seasons": [],
                "path": "/tv/" + title,
                "seriesType": "standard",
                "network": "",
                "genre": [],
                "profileId": 1,
                "languageProfileId": 1,
                "runtime": 0,
            }
            response = await client.post(f"{SONARR_URL}/series", 
                                         headers=head, 
                                         json=data)
            if response.status_code == 201:
                return {"success": f"Serie {title} added to watchlist"}
            else:
                response.raise_for_status()
    except httpx.HTTPError as e:
        if e.response.status_code == 404:
            return {"warning": "Route not found"}
        if e.response.status_code == 400:
            return {"warning": "Serie already in watchlist or invalid title"}
        else:
            return {"error": str(e)}
    except json.JSONDecodeError as e:
        return {"error": f"Failed to decode JSON: {str(e)}"}
    except Exception as e:
        return {"error": str(e)}

# TODO: TEST WITH curl -X DELETE -d '{"title":"Friends"}' http://localhost:8000/removeseries
@app.delete("/removeseries")
async def remove_sonarr_series_from_watch_list(title: str):
    try:
        async with httpx.AsyncClient() as client:
            head = {"X-Api-Key": SONARR_KEY}
            response = await client.get(f"{SONARR_URL}/series", headers=head)
            response.raise_for_status()
            s_data = response.json()
            serie_id = None
            for serie in s_data:
                if get_title(serie).lower() == title.lower():
                    serie_id = serie["id"] # maybe not "id" to look for ?
                    break
            if serie_id is None:
                return {"warning": "Serie not found"}
            response = await client.delete(f"{SONARR_URL}/series/{serie_id}",
                                           headers=head)
            response.raise_for_status()
            return {"success": "Serie removed from watch list"}
    except httpx.HTTPError as e:
        if e.response.status_code == 404:
            return {"warning": "Serie not found"}
        else:
            return {"error": str(e)}
    except Exception as e:
        return {"error": str(e)}

# *****************************************************************************
#                  Deluge routes
# 
#   - Get les torrents et leurs états                       TEST
#   - Modifier l'état d'un torrent ( pause, delete)         TEST
#   - Ajouter un torrent depuis un lien magnet              TEST

# TODO: TEST WITH curl -X GET http://localhost:8000/gettorrents
@app.get("/gettorrents")
async def get_deluge_torrents():
    torrent_ids = await deluge_rpc("web.update_ui", [["id"], {}])
    torrent_lst = [{"id": torrent_id} for torrent_id in torrent_ids]
    torrents = await deluge_rpc("web.get_torrents_status", [torrent_lst, {}])
    return torrents

# TODO: TEST WITH curl -X GET http://localhost:8000/gettrackers
@app.get("/pausetorrents/{torrent_id}")
async def pause_deluge_torrent(torrent_id: str):
    result = await deluge_rpc("core.pause_torrent", [[torrent_id]])
    if not result:
        raise Exception("Failed to pause torrent")
    return {"status": "success"}

# TODO: TEST WITH curl -X DELETE -d '{"torrent_id":"..."}' http://localhost:8000/removetorrents
@app.delete("/removetorrents")
async def delete_deluge_torrent(torrent_id: str):
    # Remove with data = False. Change it to True to remove data as well.
    result = await deluge_rpc("core.remove_torrent", [torrent_id, False])  
    if not result:
        raise HTTPException(status_code=400, detail="Failed to delete torrent")
    return {"status": "success"}

# TODO: TEST WITH curl -X GET http://localhost:8000/gettrackers
@app.post("/addtorrents")
async def add_deluge_torrent(magnet_link: str):
    result = await deluge_rpc("core.add_torrent_magnet", [magnet_link, {}])
    if not result:
        raise HTTPException(status_code=400, detail="Failed to add torrent")
    return {"status": "success", "torrent_id": result}

# *****************************************************************************
#                  Jackett routes
#  
#   - Get la liste des trackers                             TEST
#   - Modifier l'url d'un tracker                           IMPOSSIBLE

# TODO: TEST WITH curl -X GET http://localhost:8000/gettrackers
@app.get("/gettrackers")
async def get_jackett_trackers():
    data = await jackett_rpc(JACKETT_API_URL, JACKETT_KEY)
    return [tracker['id'] for tracker in data]

# *****************************************************************************
#                  Utility functions
# *****************************************************************************

def get_runtime(min: str):
    try:
        min = int(min)
        hours = min // 60
        minutes = min % 60
        return f"{hours}h {minutes}m"
    except:
        return min

def get_poster_url(images: list):
    for image in images:
        if image["coverType"] == "poster":
            return image["remoteUrl"]
    return None

def get_genre(medias: list):
    genres = {}
    for m in medias:
        for genre in m["genres"]:
            if genre in genres:
                genres[genre] += 1
            else:
                genres[genre] = 1
    return max(genres, key=genres.get)

def get_rating(ratings: dict):
    if isinstance(ratings, dict):
        if "value" in ratings and isinstance(ratings["value"], float):
            return ratings["value"]
        else:
            for value in ratings.values():
                result = get_rating(value)
                if result is not None:
                    return result
    elif isinstance(ratings, list):
        for item in ratings:
            result = get_rating(item)
            if result is not None:
                return result
    return None

def get_title(media: dict):
    if "title" in media and isinstance(media["title"], str):
        return media["title"]
    else:
        return "No title found"

def get_year(media: dict):
    if "year" in media and isinstance(media["year"], str):
        return media["yeat"]
    else:
        return "No year found"

def get_overview(media: dict):
    if "overview" in media and isinstance(media["overview"], str):
        return media["overview"]
    else:
        return "No overview found"

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
                      "page": 2,
                      "sort_by": "popularity.desc"}
            response = await client.get(f"{TMDB_URL}/discover/{type}", 
                                        headers=head, params=params)
            response.raise_for_status()
            return response.json()["results"]
    except Exception as e:
        logger.error(e)
        return -1
    
async def get_tmdb_id_from_title(title: str):
    try:
        async with httpx.AsyncClient() as client:
            url = f"https://api.themoviedb.org/3/search/movie"
            head = {"Authorization": "Bearer " + TMDB_KEY,
                    "accept": "application/json"}
            params = {"query": title, "language": "en"}
            response = await client.get(url, headers=head, params=params)
            response.raise_for_status()
            results = response.json()["results"]
            if results:
                return results[0]["id"]
            else:
                logger.error("No results found for " + title)
                return ""
    except Exception as e:
        logger.error(e)
        return {"error": str(e)}

async def get_tvdb_id_from_title(title: str):
   # TODO: Get the TVDB ID from the title
   TVDB_KEY = "2e9b77b6-cabf-4a62-8a6d-8e9b68c9601c"
   pass
   
async def deluge_rpc(method, params=None):
    if params is None:
        params = [] 
    payload = {
        "id": 1,
        "method": method,
        "params": params
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(DELUGE_URL, 
                                headers= {"Content-Type": "application/json"}, 
                                data=json.dumps(payload)) as resp:
            data = await resp.json()
            if "result" in data:
                return data["result"]
            elif "error" in data:
                raise Exception(f"Deluge RPC Error: {data['error']['message']}")
    return None

async def jackett_rpc(url: str, api_key: str) -> Dict[str, Any]:
    headers = {"X-Api-Key": api_key}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                raise HTTPException(status_code=response.status, 
                                    detail="Failed to fetch data from Jackett")
            return await response.json()