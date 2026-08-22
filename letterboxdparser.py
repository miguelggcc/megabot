import urllib.request
import json
import re
import html
from html.parser import HTMLParser
import logging

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
WATCHLIST_CACHE = "letterboxd_cache.json"


class LetterboxdParser(HTMLParser):
    """Parser for Letterboxd - extracts data-item-name"""

    def __init__(self, user):
        super().__init__()
        self.user = user
        self.peliculas = []

    def save_cache(self, films):
        with open(WATCHLIST_CACHE, 'w') as c:
            json.dump(films, c)

    def add_to_cache(self, film):
        with open(WATCHLIST_CACHE, 'r') as c:
            films = json.load(c)
        with open(WATCHLIST_CACHE, 'w') as c:
            films.append(film)
            films_str = json.dumps(films, indent=2)
            c.write(films_str)

    def load_cache(self):
        try:
            with open(WATCHLIST_CACHE, 'r') as c:
                return json.load(c)
        except Exception as e:
            logging.error(f"Error in LetterboxdParser: {e}")

    def extract_watchlist(self):
        """Extract films from letterbooxd watchlist"""

        url = f"https://letterboxd.com/{self.user}/watchlist/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://letterboxd.com/'
        }

        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=15) as response:
                html_content = response.read().decode('utf-8')

            matches = re.findall(
                r'data-item-name="([^"]+\(\d{4}\))"', html_content)
            print(len(matches))
            films = [html.unescape(p) for p in reversed(matches)]
            return films

        except Exception as e:
            print(f"Error: {e}")
            return []

    def watchlist_new_films(self):
        watchlist = self.extract_watchlist()
        cache = self.load_cache()
        print(cache)
        new_films = [p for p in watchlist if p not in cache]

        return new_films
