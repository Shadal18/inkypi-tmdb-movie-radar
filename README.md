# TMDb Movie Radar

TMDb Movie Radar is an [InkyPi](https://github.com/fatihak/InkyPi) plugin that turns an e-paper display into a movie-release billboard. It highlights one featured movie with poster art, release status, rating, runtime, genres, and a short overview.

It supports upcoming releases, now-playing movies, popular movies, and top-rated movies from The Movie Database (TMDb).

> This product uses the TMDB API but is not endorsed or certified by TMDB.

## Features

- Large poster-first dashboard designed for color e-paper displays.
- Upcoming Releases, Now Playing, Popular, and Top Rated modes.
- Stable daily featured-movie selection, first-result selection, or a new random movie on each refresh.
- Country/region and language selection.
- Optional minimum-rating and minimum-vote filters.
- Poster artwork, title, release status, rating, vote count, runtime, genres, and overview.
- Clear release badges for today, this week, upcoming, and in-theater releases.
- Six-color friendly presentation: blue header, yellow imminent-release badge, red today badge, green in-theater/rating emphasis, black text, and white background.
- Friendly error display when the API key, network, or TMDb service is unavailable.

## Installation

Install this plugin in your InkyPi plugins folder as `tmdb_movie_radar`.

```text
tmdb_movie_radar/
├── tmdb_movie_radar.py
├── settings.html
├── plugin-info.json
└── icon.png
```

Restart InkyPi after copying the files:

```bash
sudo systemctl restart inkypi.service
```

## TMDb API setup

Movie Radar requires a free TMDb Developer Plan application and its **API Key**. This is a one-time setup.

### 1. Create or sign in to TMDb

1. Go to [themoviedb.org](https://www.themoviedb.org/) and sign in, or create a free TMDb account.
2. Open **Settings** from your profile menu.
3. Select **API** in the Settings sidebar.
4. If TMDb shows **Upgrade Subscription** or asks you to create an application, choose the free **Developer Plan** and continue.

### 2. Complete the Developer Plan form

TMDb asks for application and contact information before it issues credentials. For a personal InkyPi installation, enter the following:

| Form field | Suggested value |
|---|---|
| Application Name | `InkyPi TMDb Movie Radar` |
| Application URL | `http://localhost` |
| Type of Use | `Desktop Application` |
| Application Summary | `A personal, non-commercial InkyPi e-paper display plugin that shows upcoming and currently playing movie information from TMDb.` |
| First Name / Last Name | Your real name |
| Email Address | Your contact email; the account email is fine if it is pre-filled |
| Phone, address, city, state, ZIP, country | Your real contact details, as TMDb requires for the Developer Plan form |
| Terms checkbox | Read and accept the listed terms, privacy policy, and notice of collection |

Click **Subscribe** when the form is complete. TMDb should return you to the API settings page.

### 3. Find the correct credential

On **Settings → API**, TMDb displays two different credentials:

- **API Read Access Token**: a long token used with `Authorization: Bearer ...`. **Do not use this one** for the current version of this plugin.
- **API Key**: the shorter key shown in the section directly below the Read Access Token. **Use this one.**

Copy the value from the **API Key** field. Do not share it in screenshots, GitHub commits, issues, or chat messages. TMDb supports application-level API authentication and provides a key-validation endpoint if you need to verify your credentials. [web:61][web:65]

### 4. Add the key to InkyPi

1. Open the InkyPi web interface.
2. Click the **key icon** to open **API Keys**.
3. Create a new entry with this exact name:

```text
TMDB_API_KEY
```

4. Paste the TMDb **API Key** value—not the API Read Access Token—as the value.
5. Save the API key.
6. Open the TMDb Movie Radar plugin settings, choose your desired display options, and save.
7. Refresh the Movie Radar plugin from InkyPi.

The name `TMDB_API_KEY` is case-sensitive. The plugin reads it from InkyPi API Keys and does not store the credential in its settings page.

### API key troubleshooting

- **TMDb API key was rejected:** Confirm you copied the short value under **API Key**, not the long **API Read Access Token**.
- **Missing `TMDB_API_KEY`:** Open InkyPi API Keys and confirm the key name is exactly `TMDB_API_KEY` with no spaces.
- **No data or poster appears:** Confirm the InkyPi device can access the internet and increase the request timeout in plugin settings if needed.
- **New credentials do not work immediately:** Re-open the API settings page, verify the Developer Plan subscription is active, save the InkyPi key again, and refresh the plugin.
- **You exposed a credential:** Use TMDb's **Regenerate Key** option, then update the value saved under `TMDB_API_KEY` in InkyPi.

## Configuration

| Setting | Default | Purpose |
|---|---:|---|
| Radar mode | Upcoming releases | Select Upcoming, Now Playing, Popular, or Top Rated |
| Featured movie | Daily pick | Select daily, first result, or random-on-refresh behavior |
| Release region | US | Two-letter ISO country/region code, such as US, CA, GB, or AU |
| Language | en-US | TMDb language code, such as en-US or fr-FR |
| Minimum rating | 0 | Hide movies below this TMDb rating |
| Minimum vote count | 0 | Hide movies with fewer votes than this value |
| Request timeout | 15 seconds | Maximum time allowed for API and poster image requests |

## Display behavior

The plugin first requests a matching movie list from TMDb, then gets full details for the selected movie. It downloads the movie's poster, crops it to fit the e-paper layout, and renders the dashboard.

For **Daily pick**, the selected title is deterministic for the day, mode, and region. A normal display refresh will therefore keep the same film on screen that day instead of cycling unpredictably.

The footer contains the required TMDb attribution:

```text
Movie data and artwork: TMDB
```

## TMDb API endpoints

TMDb Movie Radar uses TMDb's movie list and detail endpoints:

```text
/movie/upcoming
/movie/now_playing
/movie/popular
/movie/top_rated
/movie/{movie_id}
```

Poster images are downloaded from TMDb's image service.

## Troubleshooting

### Movie data does not load

- Confirm the InkyPi device has internet access.
- Verify that `TMDB_API_KEY` is present in InkyPi API Keys.
- Confirm you used the short TMDb **API Key**, rather than the longer API Read Access Token.
- Verify the Developer Plan subscription is active in TMDb Settings → API.
- Increase the request timeout if the connection is slow.
- Check your selected region and language code.
- Lower rating and vote filters if they eliminate all returned movies.

### Poster does not load

The plugin still renders when poster download fails. It shows a `NO POSTER` placeholder instead. Check internet connectivity, DNS, firewall rules, and the timeout setting.

### Plugin does not appear or fails to load

Validate the Python source and restart InkyPi:

```bash
cd ~/InkyPi/src
python3 -m py_compile plugins/tmdb_movie_radar/tmdb_movie_radar.py
sudo systemctl restart inkypi.service
sudo journalctl -u inkypi.service -n 150 --no-pager
```

## Privacy and security

- The plugin sends requests only to TMDb's API and image endpoints.
- Your TMDb API key is read from InkyPi API Keys.
- The plugin does not send telemetry or movie data to another service.
- Treat the TMDb API key as a credential and do not publish it.

## License

MIT License. Movie data and artwork remain subject to TMDb's terms and attribution requirements.
