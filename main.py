import os
import json
import httpx
import requests
import logging
import deluge_client
from typing import Any, Dict
from pydantic import BaseModel
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

DELUGE_PORT = 58846
DELUGE_KEY = os.getenv("DELUGE_KEY")

JACKETT_API_URL = f"http://{LOCAL_IP}:9117/api/v2.0/indexers"
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
    def __init__(self,name,synopsis,rating,length,thumbnail,year,watched=True):
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

class TrackerUpdate(BaseModel):
    url: str
    tracker_id: str

# *****************************************************************************
#                  Routes of the API
# *****************************************************************************

client = None

@app.on_event("startup")
async def startup_event():
    global client
    client = deluge_client.DelugeRPCClient(LOCAL_IP, 
                                           DELUGE_PORT, 
                                           'localclient', 
                                            DELUGE_KEY)
    client.connect()
    if client.connected:
        logger.info('Connected to Deluge')
    else:
        logger.info('Failed to connect to Deluge')

@app.get("/")
def info():
    return {'message': 'Welcome to the Riverr API.'}

# *****************************************************************************
#                  Radarr routes
#

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
            m_data = await get_tmdb_recomendations(genre, "movie")
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

# curl -X GET "http://localhost:3000/searchmovies?title=Avengers"
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

# curl -X POST "http://localhost:3000/addmovies?title=Gladiator"
@app.post("/addmovies")
async def add_radarr_movies(title: str):
    try:
        async with httpx.AsyncClient() as client:
            head = {"X-Api-Key": RADARR_KEY}
            data = {
                "title": title,
                "tmdbId": await get_tmdb_id_from_title(title, type="movie"),
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

# curl -X DELETE "http://localhost:3000/removemovies?title=Gladiator"
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
            s_data = await get_tmdb_recomendations(genre, "tv")
            series = [Media(str(s["original_name"]), 
                            str(get_overview(s)), 
                            str(s["vote_average"]), 
                            str("N/A"), 
                            str(TMDB_POSTER_URL + s["poster_path"]), 
                            str(s["first_air_date"][:4]),
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

# curl -X GET "http://localhost:3000/searchtv?title=Breaking%20Bad"
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

# curl -X POST "http://localhost:3000/addtv?title=Breaking%20Bad"
@app.post("/addtv") 
async def add_sonarr_series(title: str):
    id = await get_tmdb_id_from_title(title, type="tv")
    tvdb_id = await convert_tmdb_id_to_tvdb_id(id)
    try:
        async with httpx.AsyncClient() as client:
            head = {"X-Api-Key": SONARR_KEY}
            data = {
                "title": title,
                "tvdbId": tvdb_id,
                "qualityProfileId": 1,
                "rootFolderPath": "/tv",
                "monitored": True,
                "seasonFolder": True,
                "addOptions": {
                    "ignoreEpisodesWithFiles": False,
                    "ignoreEpisodesWithoutFiles": False,
                    "searchForMissingEpisodes": True,
                },
                "languageProfileId": 1,
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

# curl -X DELETE "http://localhost:3000/removeseries?title=Breaking%20Bad"
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

# curl -X GET "http://localhost:3000/gettorrents"
@app.get("/gettorrents")
async def get_deluge_torrents():
    if client.connected:
        torrents = client.call('core.get_torrents_status', 
                               {}, 
                               ['name', 
                                'state', 
                                'download_payload_rate', 
                                'upload_payload_rate', 
                                'progress'])
        torrent_list = []
        for torrent_id, torrent_info in torrents.items():
            name = torrent_info[b'name'].decode('utf-8')
            state = torrent_info[b'state'].decode('utf-8')
            download_speed = torrent_info[b'download_payload_rate']
            upload_speed = torrent_info[b'upload_payload_rate']
            progress = torrent_info[b'progress']

            torrent_data = {
                'torrent_id': torrent_id.decode('utf-8'),
                'name': name,
                'state': state,
                'download_speed': download_speed,
                'upload_speed': upload_speed,
                'progress': progress * 100
            }
            torrent_list.append(torrent_data)
        return torrent_list
    else:
        logger.error('Deluge not connected')

# curl -X GET "http://localhost:3000/pausetorrents?torrent_id=57e3303a91053e1ecf66e63e1b445caf79da1412"
@app.get("/pausetorrents")
async def pause_deluge_torrent(torrent_id: str):
    if client.connected:
        client.call('core.pause_torrent', torrent_id)
        return {"message": "Torrent paused successfully"}
    else:
        return {"message": "Deluge not connected"}

# curl -X GET "http://localhost:3000/resumetorrents?torrent_id=57e3303a91053e1ecf66e63e1b445caf79da1412"
@app.get("/resumetorrents")
async def resume_deluge_torrent(torrent_id: str):
    if client.connected:
        client.call('core.resume_torrent', torrent_id)
        return {"message": "Torrent resumed successfully"}
    else:
        return {"message": "Deluge not connected"}

# curl -X DELETE "http://localhost:3000/removetorrents?torrent_id=57e3303a91053e1ecf66e63e1b445caf79da1412"
@app.delete("/removetorrents")
async def delete_deluge_torrent(torrent_id: str):
    # Remove with data = False. Change it to True to remove data as well.
    if client.connected:
        client.call('core.remove_torrent', torrent_id, False)
        return {"message": "Torrent deleted successfully"}
    else:
        return {"message": "Deluge not connected"}

# curl -X GET "http://localhost:3000/addtorrents?magnet_link=..."
@app.post("/addtorrents")
async def add_deluge_torrent(magnet_link: str):
    if client.connected:
        result = client.call('core.add_torrent_magnet', magnet_link, {})
        if result:
            return {"message": "Torrent added successfully"}
        else:
            return {"message": "Failed to add torrent"}
    else:
        return {"message": "Deluge not connected"}

# *****************************************************************************
#                  Jackett routes
#

# curl -X GET "http://localhost:3000/gettrackers"
@app.get("/gettrackers")
async def get_jackett_trackers():
    headers = {'User-Agent': 'Mozilla/5.0', 'X-Api-Key': JACKETT_KEY}
    res = requests.get(JACKETT_API_URL, headers=headers)
    if res.status_code == 200:
        indexers = res.json()
        indexers = [{'name': idx['name'], 
                     'url': idx['site_link'], 
                     'id': idx['id']} for idx in indexers if idx['configured']]
        return indexers
    else:
        return {"message": f"Failed to retrieve indexers: {res.status_code}"}

# curl -X POST "http://localhost:3000/updatetrackerurl?url=...?tracker_id=..."
@app.put("/updatetrackerurl")
async def update_jackett_trackers(tracker_update: TrackerUpdate):
    headers = {'User-Agent': 'Mozilla/5.0', 'X-Api-Key': JACKETT_KEY}
    data = {'Url': tracker_update.url}
    res = requests.put(f"{JACKETT_API_URL}/{tracker_update.tracker_id}", 
                        headers=headers, 
                        json=data)
    # TODO: Find a valid way to update the tracker URL since the API doesn't
    if res.status_code == 200:
        return {"message": "Tracker URL modified successfully"}
    else:
        # Will always return 405 since the API doesn't support it
        return {"message": f"Failed to modify tracker URL: {res.status_code}"}

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

async def get_tmdb_recomendations(genre, type):
    try:
        async with httpx.AsyncClient() as client:
            head = {"Authorization": "Bearer " + TMDB_KEY,
            "accept": "application/json"}
            params = {"with_genres": genre,
                      "language": "en-US",
                      "page": 10,
                      "sort_by": "vote_count.desc",
                      "include_adult": "true",
                      "include_null_first_air_dates": "false"
                      }
            response = await client.get(f"{TMDB_URL}/discover/{type}", 
                                        headers=head, params=params)
            response.raise_for_status()
            return response.json()["results"]
    except Exception as e:
        logger.error(e)
        return -1
    
async def get_tmdb_id_from_title(title: str, type: str):
    try:
        async with httpx.AsyncClient() as client:
            head = {"Authorization": "Bearer " + TMDB_KEY,
                    "accept": "application/json"}
            params = {"query": title, "language": "en"}
            response = await client.get(f"{TMDB_URL}/search/{type}",
                                        headers=head,
                                        params=params)
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
  
async def convert_tmdb_id_to_tvdb_id(id: str):
    try:
        async with httpx.AsyncClient() as client:
            head = {"Authorization": "Bearer " + TMDB_KEY,
                    "accept": "application/json"}
            response = await client.get(f"{TMDB_URL}/tv/{id}/external_ids",
                                        headers=head)
            response.raise_for_status()
            results = response.json()
            if results:
                return results["tvdb_id"]
            else:
                logger.error("No results found for id: " + id)
                return ""
    except Exception as e:
        logger.error(e)
        return {"error": str(e)}
