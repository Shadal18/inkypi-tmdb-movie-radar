from __future__ import annotations

import hashlib
import io
import logging
from datetime import date
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

from plugins.base_plugin.base_plugin import BasePlugin


LOGGER = logging.getLogger(__name__)

TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"

BLACK = "black"
WHITE = "white"
BLUE = "#0066CC"
GREEN = "#009E60"
YELLOW = "#E6B800"
RED = "#D62828"
PALE_BLUE = "#E8F2FF"
PALE_GREEN = "#E7F6EC"
PALE_YELLOW = "#FFF5C2"
PALE_RED = "#FDE8E8"


class TmdbMovieRadar(BasePlugin):
    def __init__(self, config):
        super().__init__(config)

    def generate_image(self, settings, device_config, inky_display=None):
        api_key = device_config.load_env_key("TMDB_API_KEY")
        mode = (settings.get("mode") or "upcoming").strip().lower()
        selection = (settings.get("selection") or "daily").strip().lower()
        region = (settings.get("region") or "US").strip().upper()
        language = (settings.get("language") or "en-US").strip()
        timeout_seconds = self._as_int(settings.get("request_timeout"), 15, 5, 60)
        minimum_rating = self._as_float(settings.get("minimum_rating"), 0.0, 0.0, 10.0)
        minimum_votes = self._as_int(settings.get("minimum_votes"), 0, 0, 1_000_000)

        if not api_key:
            return self._error_image(device_config, "Missing API key\nTMDB_API_KEY")

        if mode not in {"upcoming", "now_playing", "popular", "top_rated"}:
            mode = "upcoming"

        try:
            session = self._create_session()
            movies = self._fetch_movies(session, api_key, mode, region, language, timeout_seconds)
            movies = self._filter_movies(movies, minimum_rating, minimum_votes)

            if not movies:
                return self._error_image(device_config, "No movies matched\nyour filters")

            movie = self._select_movie(movies, selection, mode, region)
            movie_id = self._as_int(movie.get("id"), 0)
            if movie_id <= 0:
                return self._error_image(device_config, "TMDb returned\ninvalid movie data")

            details = self._fetch_movie_details(session, api_key, movie_id, language, timeout_seconds)
            return self._movie_image(device_config, session, movie, details, mode, timeout_seconds)

        except requests.exceptions.Timeout:
            LOGGER.exception("TMDb request timed out")
            return self._error_image(device_config, "TMDb request\ntimed out")
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            LOGGER.exception("TMDb HTTP error: %s", status)
            if status in (401, 403):
                return self._error_image(device_config, "TMDb API key\nwas rejected")
            if status == 404:
                return self._error_image(device_config, "TMDb movie\nwas not found")
            return self._error_image(device_config, f"TMDb HTTP error\n{status}")
        except requests.exceptions.RequestException as exc:
            LOGGER.exception("TMDb connection error: %s", exc)
            return self._error_image(device_config, "Could not connect\nto TMDb")
        except Exception as exc:
            LOGGER.exception("TMDb Movie Radar plugin error: %s", exc)
            return self._error_image(device_config, "TMDb Movie Radar\nplugin error")

    @staticmethod
    def _create_session() -> requests.Session:
        session = requests.Session()
        session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "InkyPi-TMDb-Movie-Radar/1.0",
            }
        )
        return session

    def _fetch_movies(self, session, api_key, mode, region, language, timeout_seconds) -> list[dict[str, Any]]:
        endpoints = {
            "upcoming": "/movie/upcoming",
            "now_playing": "/movie/now_playing",
            "popular": "/movie/popular",
            "top_rated": "/movie/top_rated",
        }
        response = session.get(
            f"{TMDB_API_BASE}{endpoints[mode]}",
            params={
                "api_key": api_key,
                "language": language,
                "region": region,
                "page": 1,
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("results", []) if isinstance(payload, dict) else []
        return [movie for movie in results if isinstance(movie, dict)] if isinstance(results, list) else []

    def _fetch_movie_details(self, session, api_key, movie_id, language, timeout_seconds) -> dict[str, Any]:
        response = session.get(
            f"{TMDB_API_BASE}/movie/{movie_id}",
            params={"api_key": api_key, "language": language},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("TMDb returned an invalid details response")
        return payload

    @staticmethod
    def _filter_movies(movies, minimum_rating, minimum_votes) -> list[dict[str, Any]]:
        filtered = []
        for movie in movies:
            title = str(movie.get("title") or "").strip()
            rating = TmdbMovieRadar._as_float(movie.get("vote_average"), 0.0)
            votes = TmdbMovieRadar._as_int(movie.get("vote_count"), 0)
            if title and rating >= minimum_rating and votes >= minimum_votes:
                filtered.append(movie)
        return filtered

    @staticmethod
    def _select_movie(movies, selection, mode, region) -> dict[str, Any]:
        if selection == "first":
            return movies[0]
        salt = "random" if selection == "random" else f"{mode}-{region}"
        digest = hashlib.sha256(f"{date.today().isoformat()}-{salt}-{len(movies)}".encode()).digest()
        return movies[int.from_bytes(digest[:4], "big") % len(movies)]

    def _movie_image(self, device_config, session, movie, details, mode, timeout_seconds) -> Image.Image:
        canvas = Image.new("RGB", self._display_size(device_config), WHITE)
        draw = ImageDraw.Draw(canvas)
        width, height = canvas.size
        margin = max(16, min(width, height) // 26)
        footer_height = max(22, height // 30)
        content_top = margin
        content_bottom = height - margin - footer_height

        header_font = self._font(max(15, min(width, height) // 25), bold=True)
        title_font = self._font(max(24, min(width, height) // 13), bold=True)
        badge_font = self._font(max(11, min(width, height) // 32), bold=True)
        facts_font = self._font(max(14, min(width, height) // 25), bold=True)
        genre_font = self._font(max(13, min(width, height) // 28), bold=True)
        body_font = self._font(max(13, min(width, height) // 27))
        footer_font = self._font(max(9, min(width, height) // 44))

        poster_height = max(120, content_bottom - content_top)
        poster_width = max(120, min(int(poster_height / 1.48), int(width * 0.34)))
        poster_x = margin
        poster_y = content_top
        poster = self._fetch_poster(
            session,
            details.get("poster_path") or movie.get("poster_path"),
            poster_width,
            poster_height,
            timeout_seconds,
        )
        canvas.paste(poster, (poster_x, poster_y))
        draw.rectangle((poster_x, poster_y, poster_x + poster_width - 1, poster_y + poster_height - 1), outline=BLACK, width=3)

        left = poster_x + poster_width + margin
        right = width - margin
        content_width = max(1, right - left)
        y = content_top

        category = mode.replace("_", " ").upper()
        category_box = draw.textbbox((0, 0), category, font=badge_font)
        category_w = (category_box[2] - category_box[0]) + 18
        draw.rounded_rectangle((right - category_w, y, right, y + 26), radius=13, outline=BLUE, width=2)
        draw.text((right - category_w + 9, y + 6), category, fill=BLUE, font=badge_font)

        title = str(details.get("title") or movie.get("title") or "Unknown Movie")
        title_right = max(left, right - category_w - 16)
        title_width = max(1, title_right - left)
        y = self._draw_wrapped(draw, title, left, y + 1, title_width, title_font, BLACK, 3, 2)

        rule_y = y + max(7, height // 62)
        draw.line((left, rule_y, right, rule_y), fill=BLUE, width=3)
        y = rule_y + max(12, height // 40)

        release_date = str(details.get("release_date") or movie.get("release_date") or "")
        release_label, release_color = self._release_badge(release_date)
        badge_box = draw.textbbox((0, 0), release_label, font=badge_font)
        release_w = min(content_width, (badge_box[2] - badge_box[0]) + 20)
        release_h = (badge_box[3] - badge_box[1]) + 14
        draw.rounded_rectangle((left, y, left + release_w, y + release_h), radius=7, fill=release_color)
        draw.text((left + 10, y + 7), release_label, fill=BLACK if release_color == YELLOW else WHITE, font=badge_font)
        y += release_h + max(12, height // 38)

        rating = self._as_float(details.get("vote_average") or movie.get("vote_average"), 0.0)
        vote_count = self._as_int(details.get("vote_count") or movie.get("vote_count"), 0)
        runtime = self._as_int(details.get("runtime"), 0)
        runtime_text = f"{runtime // 60}h {runtime % 60}m" if runtime > 0 else "Runtime N/A"

        fact_items = [
            (f"★ {rating:.1f}/10", GREEN if rating >= 7 else BLACK),
            (f"{vote_count:,} votes", BLACK),
            (runtime_text, BLACK),
        ]
        fact_x = left
        for index, (fact, color) in enumerate(fact_items):
            draw.text((fact_x, y), fact, fill=color, font=facts_font)
            fact_w = draw.textbbox((0, 0), fact, font=facts_font)[2]
            fact_x += fact_w
            if index < len(fact_items) - 1:
                draw.text((fact_x + 10, y), "·", fill=BLUE, font=facts_font)
                fact_x += 28
        y += self._line_height(draw, "Ag", facts_font) + max(9, height // 45)

        genres = details.get("genres", [])
        genre_names = [str(item.get("name") or "").strip() for item in genres if isinstance(item, dict) and item.get("name")] if isinstance(genres, list) else []
        genre_text = "  ·  ".join(genre_names[:3]) or "Genre unavailable"
        draw.text((left, y), genre_text, fill=BLUE, font=genre_font)
        y += self._line_height(draw, genre_text, genre_font) + max(12, height // 38)

        overview = str(details.get("overview") or movie.get("overview") or "No overview is available for this movie.").strip()
        synopsis_bottom = max(y + 46, content_bottom)
        draw.rounded_rectangle((left, y, right, synopsis_bottom), radius=10, fill=PALE_BLUE, outline=BLUE, width=1)
        self._draw_wrapped(
            draw,
            overview,
            left + 14,
            y + 13,
            max(1, content_width - 28),
            body_font,
            BLACK,
            4,
            max(2, int((synopsis_bottom - y - 24) / max(1, self._line_height(draw, "Ag", body_font) + 4))),
        )

        footer_y = height - margin - footer_height + 5
        draw.line((margin, footer_y - 8, width - margin, footer_y - 8), fill=BLACK, width=1)
        footer = "Movie data and artwork: TMDB"
        footer_box = draw.textbbox((0, 0), footer, font=footer_font)
        draw.text((width - margin - (footer_box[2] - footer_box[0]), footer_y), footer, fill=BLACK, font=footer_font)
        return canvas

    def _fetch_poster(self, session, poster_path, width, height, timeout_seconds) -> Image.Image:
        placeholder = self._poster_placeholder(width, height)
        if not poster_path:
            return placeholder
        try:
            response = session.get(f"{TMDB_IMAGE_BASE}/w500{poster_path}", timeout=timeout_seconds)
            response.raise_for_status()
            poster = Image.open(io.BytesIO(response.content)).convert("RGB")
            return ImageOps.fit(poster, (width, height), method=Image.Resampling.LANCZOS)
        except Exception as exc:
            LOGGER.warning("Could not download TMDb poster: %s", exc)
            return placeholder

    def _poster_placeholder(self, width, height) -> Image.Image:
        image = Image.new("RGB", (width, height), WHITE)
        draw = ImageDraw.Draw(image)
        font = self._font(max(12, min(width, height) // 10), bold=True)
        draw.rectangle((0, 0, width - 1, height - 1), outline=BLACK, width=2)
        self._draw_centered(draw, "NO", width, max(10, height // 2 - 20), font, BLACK)
        self._draw_centered(draw, "POSTER", width, max(10, height // 2 + 4), font, BLACK)
        return image

    @staticmethod
    def _release_badge(release_date):
        if not release_date:
            return "RELEASE DATE UNAVAILABLE", BLUE
        try:
            release = date.fromisoformat(release_date)
        except ValueError:
            return f"RELEASE: {release_date}", BLUE
        days_until = (release - date.today()).days
        formatted = release.strftime("%b %-d, %Y")
        if days_until == 0:
            return f"IN THEATERS TODAY · {formatted}", RED
        if 0 < days_until <= 7:
            return f"RELEASES THIS WEEK · {formatted}", YELLOW
        if days_until > 7:
            return f"UPCOMING · {formatted}", BLUE
        return f"IN THEATERS · {formatted}", GREEN

    def _error_image(self, device_config, message) -> Image.Image:
        canvas = Image.new("RGB", self._display_size(device_config), WHITE)
        draw = ImageDraw.Draw(canvas)
        width, height = canvas.size
        title_font = self._font(max(18, min(width, height) // 15), bold=True)
        body_font = self._font(max(12, min(width, height) // 27))
        self._draw_centered(draw, "TMDb Movie Radar", width, max(18, height // 2 - 52), title_font, RED)
        y = height // 2
        for line in message.splitlines():
            self._draw_centered(draw, line, width, y, body_font, BLACK)
            y += self._line_height(draw, line, body_font) + 6
        return canvas

    def _display_size(self, device_config) -> tuple[int, int]:
        size = device_config.get_resolution()
        return size[::-1] if device_config.get_config("orientation") == "vertical" else size

    @staticmethod
    def _font(size, bold=False):
        paths = []
        if bold:
            paths.extend([
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            ])
        paths.extend([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ])
        for path in paths:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
        return ImageFont.load_default()

    @staticmethod
    def _as_int(value, default, minimum=None, maximum=None):
        try:
            number = int(float(str(value).strip()))
        except (TypeError, ValueError):
            number = default
        if minimum is not None:
            number = max(minimum, number)
        if maximum is not None:
            number = min(maximum, number)
        return number

    @staticmethod
    def _as_float(value, default, minimum=None, maximum=None):
        try:
            number = float(str(value).strip())
        except (TypeError, ValueError):
            number = default
        if minimum is not None:
            number = max(minimum, number)
        if maximum is not None:
            number = min(maximum, number)
        return number

    @staticmethod
    def _line_height(draw, text, font):
        box = draw.textbbox((0, 0), text or "Ag", font=font)
        return box[3] - box[1]

    @staticmethod
    def _draw_centered(draw, text, canvas_width, y, font, color):
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((canvas_width - (box[2] - box[0])) // 2, y), text, fill=color, font=font)

    def _draw_wrapped(self, draw, text, x, y, max_width, font, fill, line_gap=4, max_lines=99):
        words = str(text or "").split()
        if not words:
            return y
        lines = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            box = draw.textbbox((0, 0), candidate, font=font)
            if (box[2] - box[0]) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        line_height = self._line_height(draw, "Ag", font)
        for index, line in enumerate(lines[:max_lines]):
            if index == max_lines - 1 and len(lines) > max_lines:
                line = f"{line.rstrip(' .')}…"
            draw.text((x, y), line, fill=fill, font=font)
            y += line_height + line_gap
        return y
