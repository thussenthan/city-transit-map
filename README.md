# City Transit Map

Every scheduled bus, train and tram in a city, animated from its open GTFS timetable. One page, one tab per city:
**Tokyo, Hong Kong, London, Paris, Seoul, New York, Cairo, Taipei, Berlin, Vienna, Melbourne, Toronto, Jakarta, Chicago, Helsinki, Los Angeles, Boston, Philadelphia, Amsterdam, San Francisco, San Diego, Miami, Atlanta, Portland, Minneapolis** (tabs are ordered by rough annual ridership of each city's agencies, largest first; the ordering is approximate). The page opens on New York; the first city opens at its current local time, and switching tabs doesn't touch the clock (it keeps running from wherever it was).

Live: <https://thussenthan.github.io/city-transit-map/>

Pan and zoom, scrub or play through the service day (it opens at the city's current local time), filter by mode, toggle a density heatmap (`D`: vehicles running per area, coloured against that city's peak moment of the day), and hover or click any dot for its route. Deep links work (`#paris`). Keys: `space` play/pause, `[` `]` previous/next city.

Inspired by the Vienna "every scheduled vehicle" map on r/MapPorn. `media/philadelphia.mp4` is a 10-second video version of the same idea.

## How it works

Vehicle positions are interpolated along each route's shape between scheduled stop times (stops are projected onto the shape; feeds without usable shapes (Hong Kong buses, London rail) are snapped to the road or track network, and anything unroutable falls back to stop-to-stop lines; blank times are interpolated by distance; headway-based feeds are expanded into trips). Each city's trips and basemap are packed into `data/<city>.bin` (gzip JSON) and loaded when its tab is opened. Timetables are for a Tuesday (2026-10-20 where the feed covers it).

**Overlapping lines.** Metro, tram and rail lines that share a corridor are drawn side by side, one lane per colour, like a subway map (`bundle_lanes` in `tools/build_city.py`); vehicles ride their own lane. Buses are drawn in a muted indigo and regional rail in a muted teal, colours metro lines rarely use. Trip times are repaired so no vehicle teleports (feeds that round to the minute are spread by distance). Vehicles are white dots that ease out of and into every stop while still crossing each stop at its scheduled time.

## Data and caveats

| City | Feeds |
|---|---|
| Philadelphia | SEPTA bus/trolley/subway + Regional Rail |
| New York | MTA subway + five borough bus feeds + MTA Bus, NJ Transit bus and rail (no LIRR/Metro-North: feeds not publicly downloadable) |
| Boston | MBTA (subway, bus, commuter rail) |
| Chicago | CTA + Metra |
| Los Angeles | LA Metro bus and rail |
| San Francisco | SFMTA Muni (feed published only through Aug 2026, so Muni shows Tue 2026-08-25) + BART |
| San Diego | MTS |
| Portland | TriMet |
| Minneapolis | Metro Transit |
| Atlanta | MARTA |
| Miami | Miami-Dade Transit |
| Toronto | TTC |
| Tokyo | Everything open for the Kanto area: JR East, Tokyo Metro, Toei and ~40 private railways (community-built GTFS, mkuran.pl); Shinkansen and JR limited-express trains, Yurikamome, Disney Resort Line and Yokohama Subway (JR/JBB national feed, snapped to real track); Toei Bus; and ~40 municipal community-bus feeds (GTFS Data Repository Japan). The big private bus companies publish only behind keys, so they're missing |
| Seoul | Subway only, from the KTDB Korea GTFS (no shapes in the feed, so routes are snapped to real track from Overture) |
| Taipei | Taiwan TDX GTFS mirror, clipped to Taipei: MRT, rail and buses |
| Jakarta | KRL Commuter Line only, snapped to track |
| Cairo | Cairo Metro and Cairo's buses/paratransit (Transport for Cairo; both feeds are from 2025, so the page shows their own dates) |
| London | Buses from the DfT Bus Open Data Service; Tube, Overground, Elizabeth line, DLR, Tramlink and National Rail from the Great Britain GTFS (Transitous), clipped to London with `tools/clip_gtfs.py`; that feed's rail shapes are stop-to-stop chords, so rail/Tube/tram routes are snapped to real track geometry from Overture |
| Paris | Île-de-France Mobilités (metro, RER/Transilien, tram, bus) |
| Berlin | VBB |
| Vienna | Wiener Linien and regional operators (VOR) |
| Amsterdam | Dutch national GTFS (OVapi), clipped to the Amsterdam area |
| Helsinki | HSL |
| Hong Kong | Transport Department routes (KMB, Citybus, minibuses, trams) snapped to roads (no shapes in the feed) + MTR and Light Rail from the Hong Kong Community GTFS |
| Melbourne | PTV trains, trams, buses, SkyBus |

Not included: bus-only feeds (Istanbul) and cities with no open key-free GTFS (Washington DC, Singapore, Shanghai, Beijing, Guangzhou, Shenzhen, Moscow, Mexico City, São Paulo). Delhi and Madrid publish feeds but only behind a free API key. Many feeds only cover bus/tram/metro agencies that publish open data; commuter rail may be missing.
Scheduled service only, not real-time. Each city only covers the agencies listed above.

## Rebuild

```bash
# per city: basemap (Overture Maps; needs duckdb + shapely) then timetable (needs numpy, pandas, shapely)
python3 tools/fetch_base.py new-york --config tools/cities.json --work work
python3 tools/build_city.py new-york --config tools/cities.json --feeds FEEDS_DIR --work work --out data
python3 tools/make_manifest.py tools/cities.json data
python3 -m http.server   # the page needs http (it fetches data/*.bin)
```

`FEEDS_DIR` holds the GTFS zips named in `tools/cities.json` (download URLs are the agencies' public feeds). `tools/clip_gtfs.py` cuts a huge feed down to one city without extracting it (used for London). `tools/make_video_philadelphia.py` makes the video.

## Credits

Schedules: the agencies' open data (Tokyo rail GTFS by Mikołaj Kuranowski, KTDB, Taiwan TDX, KAI Commuter, Transport for Cairo, SEPTA, MTA, NJ Transit, MBTA, CTA, Metra, LA Metro, SFMTA, BART, San Diego MTS, TriMet, Metro Transit, MARTA, Miami-Dade Transit, TTC, Île-de-France Mobilités, VBB, Wiener Linien, OVapi, HSL, DfT Bus Open Data Service, Transitous/aubin.app (Great Britain), Hong Kong Transport Department, Hong Kong Community GTFS, Public Transport Victoria).
Basemap: © OpenStreetMap contributors, via Overture Maps Foundation (ODbL).
