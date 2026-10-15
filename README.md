# Philadelphia in Motion

Every scheduled SEPTA vehicle, animated from the GTFS timetable: buses, trolleys, Market-Frankford, Broad Street, Norristown High Speed Line and Regional Rail. Inspired by the Vienna "every scheduled vehicle" map on r/MapPorn.

- `philadelphia_transit.html`: interactive page (pan/zoom, time scrubber, speed, mode filters, hover/click a vehicle). Self-contained, open it in a browser.
- `philadelphia_transit.mp4`: 10-second 1080x1920 video of 08:00-08:20 on a Tuesday.

## How it works

Vehicle positions are interpolated along each route's shape between scheduled stop times (stops are projected onto the shape, dwell times are kept). The basemap is drawn from OpenStreetMap water, parks and major roads.

## Rebuild

Needs Python 3 with `numpy`, `pandas`, `shapely`, `pillow`, plus `ffmpeg` for the video.

1. Download SEPTA's GTFS from <https://github.com/septadev/GTFS/releases> (`gtfs_public.zip`), unzip it, then unzip `google_bus.zip` and `google_rail.zip` into folders of the same name inside one `GTFS_DIR`.
2. Make the video (this also downloads and caches the OSM basemap data from Overpass into `WORK_DIR`):

   ```bash
   python3 make_map.py GTFS_DIR WORK_DIR philadelphia_transit.mp4 [YYYYMMDD] [HH:MM]
   ```

3. Build the interactive page (reuses the cached OSM files):

   ```bash
   python3 build_web.py GTFS_DIR WORK_DIR web_template.html philadelphia_transit.html [YYYYMMDD]
   ```

The default date is Tuesday 2026-10-20; use a date inside the feed's validity window.

## Credits

Schedule data: SEPTA GTFS. Basemap: © OpenStreetMap contributors (ODbL).
