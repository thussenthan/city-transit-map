# Transit in Motion

Every scheduled bus, train and tram in a city, animated from its open GTFS timetable. One page, one tab per city:
**Philadelphia, New York, Boston, Chicago, San Francisco, Paris, Berlin, Toronto, Hong Kong.**

Live: <https://thussenthan.github.io/philly-transit-map/>

Pan and zoom, scrub or play through the day (default: a 20-minute loop from 08:00), filter by mode, and hover or click any dot for its route. Deep links work (`#paris`). Keys: `space` play/pause, `[` `]` previous/next city.

Inspired by the Vienna "every scheduled vehicle" map on r/MapPorn. `media/philadelphia.mp4` is a 10-second video version of the same idea.

## How it works

Vehicle positions are interpolated along each route's shape between scheduled stop times (stops are projected onto the shape; feeds without shapes fall back to stop-to-stop lines; blank times are interpolated by distance; headway-based feeds are expanded into trips). Each city's trips and basemap are packed into `data/<city>.bin` (gzip JSON) and loaded when its tab is opened. Timetables are for a Tuesday (2026-10-20 where the feed covers it).

## Data and caveats

| City | Feeds |
|---|---|
| Philadelphia | SEPTA bus/trolley/subway + Regional Rail |
| New York | MTA subway + five borough bus feeds + MTA Bus (no LIRR/Metro-North: feeds not publicly downloadable) |
| Boston | MBTA (subway, bus, commuter rail) |
| Chicago | CTA + Metra |
| San Francisco | SFMTA Muni (feed published only through Aug 2026, so Muni shows Tue 2026-08-25) + BART |
| Paris | Île-de-France Mobilités (metro, RER/Transilien, tram, bus), no shapes in feed so lines are stop-to-stop |
| Berlin | VBB |
| Toronto | TTC |
| Hong Kong | Transport Department routes (KMB, Citybus, minibuses, etc.; no MTR in that feed) |

Not included: cities with no open key-free GTFS (Tokyo, Washington DC, Singapore, Shanghai, Beijing).
Scheduled service only, not real-time. Each city only covers the agencies listed above.

## Rebuild

```bash
# per city: basemap (Overture Maps; needs duckdb + shapely) then timetable (needs numpy, pandas, shapely)
python3 tools/fetch_base.py new-york --config tools/cities.json --work work
python3 tools/build_city.py new-york --config tools/cities.json --feeds FEEDS_DIR --work work --out data
python3 tools/make_manifest.py tools/cities.json data
python3 -m http.server   # the page needs http (it fetches data/*.bin)
```

`FEEDS_DIR` holds the GTFS zips named in `tools/cities.json` (download URLs are the agencies' public feeds). `tools/make_video_philadelphia.py` makes the video.

## Credits

Schedules: SEPTA, MTA, MBTA, CTA, Metra, SFMTA, BART, Île-de-France Mobilités, VBB, TTC and Hong Kong Transport Department open data.
Basemap: © OpenStreetMap contributors, via Overture Maps Foundation (ODbL).
