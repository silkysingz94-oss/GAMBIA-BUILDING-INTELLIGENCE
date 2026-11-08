import csv
import gzip
import io
import os
import traceback

import requests
# pyrefly: ignore[missing-import]
from flask import Flask, jsonify, request, send_from_directory
from shapely import wkt
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

app = Flask(__name__, static_folder="static")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

TILE_INDEX_URL = "https://sites.research.google/open-buildings/tiles.geojson"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "GBoS-GEOAI-Building-Footprint-Research/1.0"})
tile_index_cache = None

ADMIN_URLS = [
    "https://raw.githubusercontent.com/silkysingz94-oss/GAMBIA-BUILDING-INTELLIGENCE/main/Census_EAs_Geo.json",
    "https://raw.githubusercontent.com/silkysingz94-oss/GAMBIA-BUILDING-INTELLIGENCE/master/Census_EAs_Geo.json",
]

@app.get("/")
def home():
    return send_from_directory(STATIC_DIR, "index.html")

@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "GBoS GEOAI Open Buildings proxy"})

@app.get("/api/admin")
def admin():
    errors = []
    for url in ADMIN_URLS:
        try:
            r = SESSION.get(url, timeout=40)
            r.raise_for_status()
            data = r.json()
            if data.get("type") == "FeatureCollection" and isinstance(data.get("features"), list):
                return jsonify(data)
            raise ValueError("Not a GeoJSON FeatureCollection")
        except Exception as e:
            errors.append(f"{url}: {e}")
    return jsonify({"error": "Could not retrieve the administrative GeoJSON.", "details": errors}), 502

def get_tile_index():
    global tile_index_cache
    if tile_index_cache is not None:
        return tile_index_cache
    r = SESSION.get(TILE_INDEX_URL, timeout=60)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        raise ValueError("Google tile index did not return a GeoJSON FeatureCollection.")
    features = []
    for f in data["features"]:
        props = f.get("properties") or {}
        geom = f.get("geometry")
        url = props.get("tile_url")
        if geom and url:
            features.append({"geometry": shape(geom), "url": url, "tile_id": props.get("tile_id", "")})
    tile_index_cache = features
    return features

def feature_collection_geometry(geojson):
    if geojson.get("type") == "Feature":
        return shape(geojson["geometry"])
    if geojson.get("type") == "FeatureCollection":
        geoms = [shape(f["geometry"]) for f in geojson.get("features", []) if f.get("geometry")]
        if not geoms:
            raise ValueError("Selected FeatureCollection contains no geometries.")
        return unary_union(geoms)
    if geojson.get("type") in ("Polygon", "MultiPolygon"):
        return shape(geojson)
    raise ValueError("AOI must be a GeoJSON Feature, FeatureCollection, Polygon or MultiPolygon.")

def as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

@app.post("/api/extract")
def extract():
    try:
        payload = request.get_json(force=True)
        aoi_json = payload.get("aoi")
        threshold = float(payload.get("confidence", 0.75))
        if not aoi_json:
            return jsonify({"error": "No selected area geometry was supplied."}), 400
        if not 0 <= threshold <= 1:
            return jsonify({"error": "Confidence must be between 0 and 1."}), 400

        aoi = feature_collection_geometry(aoi_json)
        if aoi.is_empty:
            return jsonify({"error": "Selected area is empty."}), 400

        tiles = [t for t in get_tile_index() if t["geometry"].intersects(aoi)]
        if not tiles:
            return jsonify({"error": "No Open Buildings V3 tiles intersect this selected area."}), 404

        found = []
        errors = []
        seen = set()
        for tile in tiles:
            try:
                resp = SESSION.get(tile["url"], timeout=(20, 240))
                resp.raise_for_status()
                raw = resp.content
                # Google serves gzip-compressed CSV tile files.
                if raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
                stream = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8-sig", newline="")
                reader = csv.DictReader(stream)
                for row in reader:
                    confidence = as_float(row.get("confidence"), -1)
                    if confidence < threshold:
                        continue
                    geom_text = row.get("geometry") or ""
                    if not geom_text:
                        continue
                    try:
                        geom = wkt.loads(geom_text)
                        if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
                            continue
                        if not geom.intersects(aoi):
                            continue
                        # De-duplicate by WKT normalized to a stable representation.
                        key = geom.wkb
                        if key in seen:
                            continue
                        seen.add(key)
                        props = {
                            "confidence": confidence,
                            "area_in_meters": as_float(row.get("area_in_meters")),
                            "latitude": as_float(row.get("latitude")),
                            "longitude": as_float(row.get("longitude")),
                            "full_plus_code": row.get("full_plus_code", ""),
                            "tile_id": tile["tile_id"],
                        }
                        found.append({"type": "Feature", "properties": props, "geometry": mapping(geom)})
                    except Exception:
                        continue
            except Exception as e:
                errors.append({"tile_id": tile["tile_id"], "error": str(e)})

        result = {
            "type": "FeatureCollection",
            "name": "Selected area Open Buildings V3 footprints",
            "features": found,
        }
        return jsonify({
            "geojson": result,
            "summary": {
                "footprints": len(found),
                "tiles_intersecting": len(tiles),
                "tiles_succeeded": len(tiles) - len(errors),
                "tiles_failed": len(errors),
                "confidence_threshold": threshold,
            },
            "tile_errors": errors[:10],
        })
    except requests.RequestException as e:
        return jsonify({"error": "Unable to retrieve Google Open Buildings data.", "details": str(e)}), 502
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("GBoS GEOAI Building Footprint Dashboard")
    print("Open http://127.0.0.1:5000 in your browser")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
