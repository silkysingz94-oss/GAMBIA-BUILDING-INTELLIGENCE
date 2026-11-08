GBoS GEOAI - GAMBIA BUILDING FOOTPRINT INTELLIGENCE (UPDATED)

PACKAGE FILES
- app.py: Flask local service. Fetches the GitHub administrative GeoJSON and retrieves Google Open Buildings V3 tiles server-side.
- static/index.html: Three-column Leaflet dashboard with area selectors, map drawing, automatic extraction, analytics and exports.

INSTALLATION (WINDOWS)
1. Open Command Prompt in this folder.
2. Install dependencies:
   py -m pip install --upgrade flask requests shapely urllib3
3. Start the service:
   py app.py
4. Open in your browser:
   http://127.0.0.1:5000

HOW TO USE
- The administrative boundaries are loaded automatically from the GAMBIA-BUILDING-INTELLIGENCE GitHub repository.
- Select an administrative area and click USE SELECTED AREA. Extraction then starts automatically.
- Alternatively, draw a rectangle or polygon on the map. Extraction starts automatically when drawing is finished.
- No separate building GeoJSON or shapefile upload is needed.
- The EXTRACT FOOTPRINTS button can be used to rerun extraction after changing the confidence threshold.
- CSV, selected-area GeoJSON and building-footprint GeoJSON exports are provided.

TROUBLESHOOTING
- Keep the Command Prompt open while using the dashboard.
- Open http://127.0.0.1:5000/api/health to confirm the local service is running.
- Open http://127.0.0.1:5000/api/diagnostics to test the two Google tile-index endpoints. This does not download building tiles.
- The service retries temporary HTTP 429/5xx failures and tries a secondary public tile-index endpoint if the primary endpoint fails.
- Tile files are streamed during processing rather than loading the complete compressed tile into memory. A selected S2 tile can still be very large and take considerable time to process.
- If extraction fails, copy the complete error shown in the dashboard and the Command Prompt.

DATA LIMITATIONS
Google Open Buildings V3 contains model-detected building footprints inferred from imagery around May 2023. It is not an annual time series, a building-permit register, or a verified cadastral dataset. Coverage and detection quality vary by location. Use the confidence threshold as a model score filter, not as a guarantee of positional or thematic accuracy.

Produced by Ansu Singhateh
GIS Analyst | GIS / Cartography Unit | Gambia Bureau of Statistics
GBoS GEOAI - Research and educational use
