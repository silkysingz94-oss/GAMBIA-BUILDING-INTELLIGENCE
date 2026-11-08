GBoS GEOAI - Gambia Building Footprint Dashboard

FILES
- app.py: local proxy/data service that downloads Google Open Buildings V3 tiles server-side.
- static/index.html: three-column Leaflet dashboard.

INSTALLATION (Windows)
1. Install Python 3.10 or newer.
2. Open Command Prompt in this folder.
3. Run:
   py -m pip install flask requests shapely
4. Run:
   py app.py
5. Open:
   http://127.0.0.1:5000

IMPORTANT
- Keep the Command Prompt window open while using the dashboard.
- Internet access is required.
- Select a region/LGA/district/ward/EA, or draw a rectangle/polygon.
- Click EXTRACT FOOTPRINTS.
- The local service downloads only Open Buildings V3 tiles intersecting the selected AOI, then filters individual building polygons against the AOI.
- If a selected tile is very large, extraction can take time.
- The service reports failed tile downloads in the dashboard and terminal.
- Open Buildings V3 is an inference dataset based on imagery from May 2023, not an annual time series or cadastral register.
