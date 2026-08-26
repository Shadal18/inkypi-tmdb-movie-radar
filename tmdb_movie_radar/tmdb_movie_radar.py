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


class TmdbMovieRadar(BasePlugin):
    def __init__(self, config):
        super().__init__(config)

    def generate_image(self, settings, device_config, inky_display=None):
        api_key = device_config.load_env_key("TMDB_API_KEY")
        mode = (settings.get("mode") or "upcoming").strip().lower()
        selection = (settings.get("selection") or "daily").strip().lower()
        region = (settings.get("region") or "US").strip().upper()
        language = (settings.get("language") or "en-US").strip()
        timeout_seconds = self._as_int(
            settings.get("request_timeout"),
            default=15,
            minimum=5,
            maximum=60,
        )
        minimum_rating = self._as_float(
            settings.get("minimum_rating"),
            default=0.0,
            minimum=0.0,
            maximum=10.0,
        )
        minimum_votes = self._as_int(
            settings.get("minimum_votes"),
            default=0,
            minimum=0,
            maximum=1_000_000,
        )

        if not api_key:
            return self._error_image(
                device_config,
                "Missing API key\nTMDB_API_KEY",
            )

        if mode not in {"upcoming", "now_playing", "popular", "top_rated"}:
            mode = "upcoming"

        try:
            session = self._create_session()
            movies = self._fetch_movies(
                session=session,
                api_key=api_key,
                mode=mode,
                region=region,
                language=language,
                timeout_seconds=timeout_seconds,
            )
            movies = self._filter_movies(
                movies,
                minimum_rating=minimum_rating,
                minimum_votes=minimum_votes,
            )

            if not movies:
                return self._error_image(
                    device_config,
                    "No movies matched\nyour filters",
                )

            movie = self._select_movie(
                movies=movies,
                selection=selection,
                mode=mode,
                region=region,
            )
            movie_id = self._as_int(movie.get("id"), default=0)

            if movie_id <= 0:
                return self._error_image(
                    device_config,
                    "TMDb returned\ninvalid movie data",
                )

            details = self._fetch_movie_details(
                session=session,
                api_key=api_key,
                movie_id=movie_id,
                language=language,
                timeout_seconds=timeout_seconds,
            )

            return self._movie_image(
                device_config=device_config,
                session=session,
                movie=movie,
                details=details,
                mode=mode,
                timeout_seconds=timeout_seconds,
            )

        except requests.exceptions.Timeout:
            LOGGER.exception("TMDb request timed out")
            return self._error_image(
                device_config,
                "TMDb request\ntimed out",
            )
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            LOGGER.exception("TMDb HTTP error: %s", status)

            if status in (401, 403):
                return self._error_image(
                    device_config,
                    "TMDb API key\nwas rejected",
                )

            if status == 404:
                return self._error_image(
                    device_config,
                    "TMDb movie\nwas not found",
                )

            return self._error_image(
                device_config,
                f"TMDb HTTP error\n{status}",
            )
        except requests.exceptions.RequestException as exc:
            LOGGER.exception("TMDb connection error: %s", exc)
            return self._error_image(
                device_config,
                "Could not connect\nto TMDb",
            )
        except Exception as exc:
            LOGGER.exception("TMDb Movie Radar plugin error: %s", exc)
            return self._error_image(
                device_config,
                "TMDb Movie Radar\nplugin error",
            )

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

    def _fetch_movies(
        self,
        session: requests.Session,
        api_key: str,
        mode: str,
        region: str,
        language: str,
        timeout_seconds: int,
    ) -> list[dict[str, Any]]:
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

        if not isinstance(results, list):
            return []

        return [movie for movie in results if isinstance(movie, dict)]

    def _fetch_movie_details(
        self,
        session: requests.Session,
        api_key: str,
        movie_id: int,
        language: str,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        response = session.get(
            f"{TMDB_API_BASE}/movie/{movie_id}",
            params={
                "api_key": api_key,
                "language": language,
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("TMDb returned an invalid details response")

        return payload

    @staticmethod
    def _filter_movies(
        movies: list[dict[str, Any]],
        minimum_rating: float,
        minimum_votes: int,
    ) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []

        for movie in movies:
            title = str(movie.get("title") or "").strip()
            rating = TmdbMovieRadar._as_float(
                movie.get("vote_average"),
                default=0.0,
            )
            votes = TmdbMovieRadar._as_int(
                movie.get("vote_count"),
                default=0,
            )

            if not title:
                continue

            if rating < minimum_rating:
                continue

            if votes < minimum_votes:
                continue

            filtered.append(movie)

        return filtered

    @staticmethod
    def _select_movie(
        movies: list[dict[str, Any]],
        selection: str,
        mode: str,
        region: str,
    ) -> dict[str, Any]:
        if selection == "first":
            return movies[0]

        if selection == "random":
            entropy = hashlib.sha256(
                f"{date.today().isoformat()}-{len(movies)}-random".encode()
            ).digest()
            index = int.from_bytes(entropy[:4], "big") % len(movies)
            return movies[index]

        digest = hashlib.sha256(
            f"{date.today().isoformat()}-{mode}-{region}".encode()
        ).digest()
        index = int.from_bytes(digest[:4], "big") % len(movies)
        return movies[index]

    def _movie_image(
        self,
        device_config,
        session: requests.Session,
        movie: dict[str, Any],
        details: dict[str, Any],
        mode: str,
        timeout_seconds: int,
    ) -> Image.Image:
        canvas = Image.new("RGB", self._display_size(device_config), WHITE)
        draw = ImageDraw.Draw(canvas)
        width, height = canvas.size

        margin = max(14, min(width, height) // 28)
        header_height = max(40, height // 11)

        title_font = self._font(max(19, min(width, height) // 16), bold=True)
        movie_title_font = self._font(max(20, min(width, height) // 15), bold=True)
        subtitle_font = self._font(max(12, min(width, height) // 28), bold=True)
        body_font = self._font(max(12, min(width, height) // 30))
        small_font = self._font(max(9, min(width, height) // 42))

        draw.rounded_rectangle(
            (margin, margin, width - margin, margin + header_height),
            radius=10,
            fill=BLUE,
        )

        draw.text(
            (margin + 13, margin + 9),
            "MOVIE RELEASE RADAR",
            fill=WHITE,
            font=title_font,
        )

        mode_label = mode.replace("_", " ").upper()
        mode_box = draw.textbbox((0, 0), mode_label, font=small_font)
        draw.text(
            (
                width - margin - (mode_box[2] - mode_box[0]) - 13,
                margin + 14,
            ),
            mode_label,
            fill=WHITE,
            font=small_font,
        )

        content_top = margin + header_height + max(10, height // 42)
        footer_height = max(18, height // 28)
        content_bottom = height - margin - footer_height

        poster_height = max(100, content_bottom - content_top)
        poster_width = max(
            100,
            min(
                int(poster_height / 1.48),
                int(width * 0.36),
            ),
        )

        poster_x = margin
        poster_y = content_top

        poster = self._fetch_poster(
            session=session,
            poster_path=details.get("poster_path") or movie.get("poster_path"),
            width=poster_width,
            height=poster_height,
            timeout_seconds=timeout_seconds,
        )
        canvas.paste(poster, (poster_x, poster_y))
        draw.rectangle(
            (
                poster_x,
                poster_y,
                poster_x + poster_width - 1,
                poster_y + poster_height - 1,
            ),
            outline=BLACK,
            width=2,
        )

        content_left = poster_x + poster_width + margin
        content_right = width - margin
        content_width = max(1, content_right - content_left)
        y = content_top

        title = str(details.get("title") or movie.get("title") or "Unknown Movie")
        y = self._draw_wrapped(
            draw=draw,
            text=title,
            x=content_left,
            y=y,
            max_width=content_width,
            font=movie_title_font,
            fill=BLACK,
            line_gap=4,
            max_lines=2,
        )

        y += max(7, height // 52)

        release_date = str(
            details.get("release_date")
            or movie.get("release_date")
            or ""
        )
        release_label, release_color = self._release_badge(release_date)

        badge_box = draw.textbbox((0, 0), release_label, font=subtitle_font)
        badge_width = min(
            content_width,
            (badge_box[2] - badge_box[0]) + 22,
        )
        badge_height = (badge_box[3] - badge_box[1]) + 14

        draw.rounded_rectangle(
            (
                content_left,
                y,
                content_left + badge_width,
                y + badge_height,
            ),
            radius=7,
            fill=release_color,
        )
        badge_text_color = BLACK if release_color == YELLOW else WHITE
        draw.text(
            (content_left + 10, y + 7),
            release_label,
            fill=badge_text_color,
            font=subtitle_font,
        )

        y += badge_height + max(11, height // 38)

        rating = self._as_float(
            details.get("vote_average") or movie.get("vote_average"),
            default=0.0,
        )
        vote_count = self._as_int(
            details.get("vote_count") or movie.get("vote_count"),
            default=0,
        )
        runtime = self._as_int(details.get("runtime"), default=0)

        facts = f"★ {rating:.1f}/10  ·  {vote_count:,} votes"
        if runtime > 0:
            facts += f"  ·  {runtime // 60}h {runtime % 60}m"

        draw.text(
            (content_left, y),
            facts,
            fill=GREEN if rating >= 7.0 else BLACK,
            font=subtitle_font,
        )
        y += self._line_height(draw, facts, subtitle_font) + max(8, height // 46)

        genres = details.get("genres", [])
        genre_names = []

        if isinstance(genres, list):
            genre_names = [
                str(genre.get("name") or "").strip()
                for genre in genres
                if isinstance(genre, dict) and genre.get("name")
            ]

        genre_text = " · ".join(genre_names[:3]) or "Genre unavailable"
        draw.text(
            (content_left, y),
            genre_text,
            fill=BLUE,
            font=subtitle_font,
        )
        y += self._line_height(draw, genre_text, subtitle_font) + max(10, height // 38)

        overview = str(
            details.get("overview")
            or movie.get("overview")
            or "No overview is available for this movie."
        ).strip()

        self._draw_wrapped(
            draw=draw,
            text=overview,
            x=content_left,
            y=y,
            max_width=content_width,
            font=body_font,
            fill=BLACK,
            line_gap=4,
            max_lines=8,
        )

        footer = "Movie data and artwork: TMDB"
        footer_box = draw.textbbox((0, 0), footer, font=small_font)
        draw.text(
            (
                width - margin - (footer_box[2] - footer_box[0]),
                height - margin - (footer_box[3] - footer_box[1]),
            ),
            footer,
            fill=BLACK,
            font=small_font,
        )

        return canvas

    def _fetch_poster(
        self,
        session: requests.Session,
        poster_path: Any,
        width: int,
        height: int,
        timeout_seconds: int,
    ) -> Image.Image:
        placeholder = self._poster_placeholder(width, height)

        if not poster_path:
            return placeholder

        try:
            response = session.get(
                f"{TMDB_IMAGE_BASE}/w500{poster_path}",
                timeout=timeout_seconds,
            )
            response.raise_for_status()

            poster = Image.open(io.BytesIO(response.content)).convert("RGB")
            return ImageOps.fit(
                poster,
                (width, height),
                method=Image.Resampling.LANCZOS,
            )
        except Exception as exc:
            LOGGER.warning("Could not download TMDb poster: %s", exc)
            return placeholder

    def _poster_placeholder(self, width: int, height: int) -> Image.Image:
        image = Image.new("RGB", (width, height), WHITE)
        draw = ImageDraw.Draw(image)
        font = self._font(max(12, min(width, height) // 10), bold=True)

        draw.rectangle((0, 0, width - 1, height - 1), outline=BLACK, width=2)
        self._draw_centered(
            draw,
            "NO",
            width,
            max(10, height // 2 - 20),
            font,
            BLACK,
        )
        self._draw_centered(
            draw,
            "POSTER",
            width,
            max(10, height // 2 + 4),
            font,
            BLACK,
        )
        return image

    @staticmethod
    def _release_badge(release_date: str) -> tuple[str, str]:
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

    def _error_image(self, device_config, message: str) -> Image.Image:
        canvas = Image.new("RGB", self._display_size(device_config), WHITE)
        draw = ImageDraw.Draw(canvas)
        width, height = canvas.size

        title_font = self._font(max(18, min(width, height) // 15), bold=True)
        body_font = self._font(max(12, min(width, height) // 27))

        self._draw_centered(
            draw,
            "TMDb Movie Radar",
            width,
            max(18, height // 2 - 52),
            title_font,
            RED,
        )

        y = height // 2
        for line in message.splitlines():
            self._draw_centered(
                draw,
                line,
                width,
                y,
                body_font,
                BLACK,
            )
            y += self._line_height(draw, line, body_font) + 6

        return canvas

    def _display_size(self, device_config) -> tuple[int, int]:
        size = device_config.get_resolution()
        return (
            size[::-1]
            if device_config.get_config("orientation") == "vertical"
            else size
        )

    @staticmethod
    def _font(size: int, bold: bool = False):
        font_paths = []

        if bold:
            font_paths.extend(
                [
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
                ]
            )

        font_paths.extend(
            [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            ]
        )

        for path in font_paths:
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass

        return ImageFont.load_default()

    @staticmethod
    def _as_int(
        value: Any,
        default: int,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> int:
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
    def _as_float(
        value: Any,
        default: float,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> float:
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
    def _line_height(draw, text: str, font) -> int:
        box = draw.textbbox((0, 0), text or "Ag", font=font)
        return box[3] - box[1]

    @staticmethod
    def _draw_centered(
        draw,
        text: str,
        canvas_width: int,
        y: int,
        font,
        color: str,
    ) -> None:
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(
            ((canvas_width - (box[2] - box[0])) // 2, y),
            text,
            fill=color,
            font=font,
        )

    def _draw_wrapped(
        self,
        draw,
        text: str,
        x: int,
        y: int,
        max_width: int,
        font,
        fill: str,
        line_gap: int = 4,
        max_lines: int = 99,
    ) -> int:
        words = str(text or "").split()
        if not words:
            return y

        lines: list[str] = []
        current = ""

        for word in words:
            candidate = f"{current} {word}".strip()
            box = draw.textbbox((0, 0), candidate, font=font)

            if (box[2] - box[0]) <= max_width:
                current = candidate
                continue

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