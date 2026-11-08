"""GBoS GEOAI - Gambia Building Footprint Intelligence
Local Flask service for retrieving Google Open Buildings V3 polygons.
"""
from flask import Flask, request, jsonify, send_from_directory
import csv
import gzip
import io
import os
import time
import traceback
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from shapely.geometry import shape, mapping
from shapely import wkt
from shapely.ops import unary_union
from shapely.prepared import prep

app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # AOI request limit: 20 MB
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)

# Google's primary tile index and a publicly used mirror endpoint.
TILE_INDEX_URLS = [
    "https://sites.research.google/open-buildings/tiles.geojson",
    "https://openbuildings-public-dot-gweb-research.uw.r.appspot.com/public/tiles.geojson",
]

ADMIN_URLS = [
    "https://raw.githubusercontent.com/silkysingz94-oss/GAMBIA-BUILDING-INTELLIGENCE/main/Census_EAs_Geo.json",
    "https://raw.githubusercontent.com/silkysingz94-oss/GAMBIA-BUILDING-INTELLIGENCE/master/Census_EAs_Geo.json",
]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; GBoS-GEOAI-Building-Footprint-Research/2.0)",
    "Accept": "application/geo+json,application/json,text/csv,*/*",
})
_retry = Retry(
    total=4,
    connect=4,
    read=3,
    status=4,
    backoff_factor=1.2,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"]),
    raise_on_status=False,
)
_adapter = HTTPAdapter(max_retries=_retry, pool_connections=10, pool_maxsize=10)
SESSION.mount("https://", _adapter)
SESSION.mount("http://", _adapter)

tile_index_cache = None
tile_index_source = None


@app.get("/")
def home():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/favicon.ico")
def favicon():
    return "", 204


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "GBoS GEOAI Open Buildings proxy", "version": "2.0"})


@app.get("/api/diagnostics")
def diagnostics():
    """Check the tile index endpoints without downloading any building tile."""
    checks = []
    for url in TILE_INDEX_URLS:
        item = {"url": url}
        try:
            response = SESSION.get(url, timeout=(15, 45), stream=True)
            item["http_status"] = response.status_code
            item["content_type"] = response.headers.get("Content-Type", "")
            item["content_length"] = response.headers.get("Content-Length", "unknown")
            if response.ok:
                # Read only a small prefix; the index is small, but this avoids
                # downloading a response if an upstream endpoint misbehaves.
                prefix = response.raw.read(256)
                item["response_preview"] = prefix.decode("utf-8", errors="replace")[:180]
                item["ok"] = prefix.lstrip().startswith((b"{", b"["))
            else:
                item["ok"] = False
                item["error"] = f"HTTP {response.status_code} {response.reason}"
            response.close()
        except requests.RequestException as exc:
            item["ok"] = False
            item["error"] = f"{type(exc).__name__}: {exc}"
        checks.append(item)
    return jsonify({"tile_index_checks": checks, "cached": tile_index_cache is not None,
                    "cached_source": tile_index_source})


@app.get("/api/admin")
def admin():
    errors = []
    for url in ADMIN_URLS:
        try:
            r = SESSION.get(url, timeout=(15, 60))
            r.raise_for_status()
            data = r.json()
            if data.get("type") == "FeatureCollection" and isinstance(data.get("features"), list):
                return jsonify(data)
            raise ValueError("Response is not a GeoJSON FeatureCollection")
        except Exception as exc:
            errors.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
    return jsonify({"error": "Could not retrieve the administrative GeoJSON.", "details": errors}), 502


def get_tile_index(force=False):
    global tile_index_cache, tile_index_source
    if tile_index_cache is not None and not force:
        return tile_index_cache

    errors = []
    for url in TILE_INDEX_URLS:
        try:
            response = SESSION.get(url, timeout=(20, 90))
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("features"), list):
                raise ValueError("Tile index is not a GeoJSON FeatureCollection")

            parsed = []
            for feature in data["features"]:
                props = feature.get("properties") or {}
                geom_json = feature.get("geometry")
                tile_url = props.get("tile_url") or props.get("url")
                if not geom_json or not tile_url:
                    continue
                if urlparse(tile_url).scheme != "https":
                    continue
                try:
                    tile_geom = shape(geom_json)
                    if not tile_geom.is_empty:
                        parsed.append({
                            "geometry": tile_geom,
                            "url": tile_url,
                            "tile_id": str(props.get("tile_id", "unknown")),
                            "size_mb": props.get("size_mb"),
                        })
                except Exception:
                    continue
            if not parsed:
                raise ValueError("Tile index loaded but contained no usable tile geometries/URLs")
            tile_index_cache = parsed
            tile_index_source = url
            return parsed
        except Exception as exc:
            errors.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})

    raise RuntimeError(
        "Could not load Google's Open Buildings tile index from either endpoint. "
        "Check /api/diagnostics for endpoint status. Details: " + repr(errors)
    )


def feature_collection_geometry(geojson):
    if not isinstance(geojson, dict):
        raise ValueError("Selected area must be a GeoJSON object")
    kind = geojson.get("type")
    if kind == "Feature":
        if not geojson.get("geometry"):
            raise ValueError("Selected Feature has no geometry")
        return shape(geojson["geometry"])
    if kind == "FeatureCollection":
        geoms = [shape(f["geometry"]) for f in geojson.get("features", [])
                 if f.get("geometry")]
        if not geoms:
            raise ValueError("Selected FeatureCollection contains no geometries")
        return unary_union(geoms)
    if kind in ("Polygon", "MultiPolygon"):
        return shape(geojson)
    raise ValueError("AOI must be a GeoJSON Feature, FeatureCollection, Polygon or MultiPolygon")


def as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def open_tile_csv(response):
    """Return a streaming text reader for plain or gzip-compressed CSV."""
    response.raw.decode_content = False
    magic = response.raw.read(2)
    # Reattach the two consumed bytes without buffering the complete tile.
    stream = io.BufferedReader(_PrefixReader(magic, response.raw))
    if magic == b"\x1f\x8b":
        binary = gzip.GzipFile(fileobj=stream, mode="rb")
    else:
        binary = stream
    text_stream = io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
    return csv.DictReader(text_stream), text_stream


class _PrefixReader(io.RawIOBase):
    def __init__(self, prefix, raw):
        self.prefix = prefix
        self.raw = raw

    def readable(self):
        return True

    def readinto(self, buffer):
        if self.prefix:
            n = min(len(buffer), len(self.prefix))
            buffer[:n] = self.prefix[:n]
            self.prefix = self.prefix[n:]
            return n
        chunk = self.raw.read(len(buffer))
        if not chunk:
            return 0
        buffer[:len(chunk)] = chunk
        return len(chunk)


def extract_tile(tile, aoi, prepared_aoi, threshold, seen):
    """Download and process one tile in streaming mode; never hold full gzip in RAM."""
    response = SESSION.get(tile["url"], timeout=(25, 900), stream=True)
    try:
        response.raise_for_status()
        reader, text_stream = open_tile_csv(response)
        found = []
        try:
            for row in reader:
                confidence = as_float(row.get("confidence"), -1)
                if confidence < threshold:
                    continue
                wkt_text = row.get("geometry") or ""
                if not wkt_text:
                    continue
                try:
                    geom = wkt.loads(wkt_text)
                    if geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
                        continue
                    if not prepared_aoi.intersects(geom):
                        continue
                    key = geom.wkb
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append({
                        "type": "Feature",
                        "properties": {
                            "confidence": confidence,
                            "area_in_meters": as_float(row.get("area_in_meters")),
                            "latitude": as_float(row.get("latitude")),
                            "longitude": as_float(row.get("longitude")),
                            "full_plus_code": row.get("full_plus_code", ""),
                            "tile_id": tile["tile_id"],
                        },
                        "geometry": mapping(geom),
                    })
                except Exception:
                    # Ignore malformed individual rows, not the whole tile.
                    continue
        finally:
            text_stream.close()
        return found
    finally:
        response.close()


@app.post("/api/extract")
def extract():
    started = time.time()
    try:
        payload = request.get_json(silent=True) or {}
        aoi_json = payload.get("aoi")
        threshold = float(payload.get("confidence", 0.75))
        if not aoi_json:
            return jsonify({"error": "No selected area geometry was supplied."}), 400
        if not 0 <= threshold <= 1:
            return jsonify({"error": "Confidence must be between 0 and 1."}), 400

        aoi = feature_collection_geometry(aoi_json)
        if aoi.is_empty:
            return jsonify({"error": "Selected area geometry is empty."}), 400
        if not aoi.is_valid:
            try:
                aoi = aoi.buffer(0)
            except Exception:
                pass
        if aoi.is_empty:
            return jsonify({"error": "Selected area geometry could not be repaired."}), 400
        prepared_aoi = prep(aoi)

        try:
            tile_index = get_tile_index()
        except Exception as exc:
            app.logger.exception("Open Buildings tile-index retrieval failed")
            return jsonify({
                "error": "Google Open Buildings tile index could not be reached.",
                "details": str(exc),
                "hint": "Open http://127.0.0.1:5000/api/diagnostics to test both tile-index endpoints.",
            }), 502

        tiles = [tile for tile in tile_index if tile["geometry"].intersects(aoi)]
        if not tiles:
            return jsonify({
                "error": "No Google Open Buildings V3 tiles intersect the selected area.",
                "tile_index_source": tile_index_source,
                "hint": "The area may be outside processed Open Buildings coverage. Check the Google dataset explorer.",
            }), 404

        found, tile_errors, succeeded = [], [], 0
        seen = set()
        for index, tile in enumerate(tiles, start=1):
            try:
                app.logger.info("Downloading tile %s (%s/%s)", tile["tile_id"], index, len(tiles))
                found.extend(extract_tile(tile, aoi, prepared_aoi, threshold, seen))
                succeeded += 1
            except Exception as exc:
                error_text = f"{type(exc).__name__}: {exc}"
                app.logger.exception("Tile %s failed", tile["tile_id"])
                tile_errors.append({"tile_id": tile["tile_id"], "url": tile["url"], "error": error_text})

        if succeeded == 0:
            return jsonify({
                "error": "All intersecting Open Buildings tiles failed to download or parse.",
                "details": tile_errors[:10],
                "tile_index_source": tile_index_source,
                "hint": "Check internet access to storage.googleapis.com. Google tile files can be very large; the service now streams them instead of loading the full compressed file into memory.",
            }), 502

        result = {
            "type": "FeatureCollection",
            "name": "Selected area Google Open Buildings V3 footprints",
            "features": found,
        }
        elapsed = round(time.time() - started, 1)
        return jsonify({
            "geojson": result,
            "summary": {
                "footprints": len(found),
                "tiles_intersecting": len(tiles),
                "tiles_succeeded": succeeded,
                "tiles_failed": len(tile_errors),
                "confidence_threshold": threshold,
                "elapsed_seconds": elapsed,
                "tile_index_source": tile_index_source,
            },
            "tile_errors": tile_errors[:10],
        })
    except requests.RequestException as exc:
        app.logger.exception("Network request failed during extraction")
        return jsonify({
            "error": "A network request failed while retrieving Open Buildings data.",
            "details": f"{type(exc).__name__}: {exc}",
        }), 502
    except Exception as exc:
        app.logger.exception("Unexpected extraction failure")
        return jsonify({"error": "Unexpected extraction error.",
                        "details": f"{type(exc).__name__}: {exc}"}), 500


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "Selected AOI request is larger than 20 MB. Select a smaller area or simplify the boundary."}), 413


if __name__ == "__main__":
    print("GBoS GEOAI Building Footprint Dashboard - version 2.0")
    print("Open http://127.0.0.1:5000 in your browser")
    print("Diagnostics: http://127.0.0.1:5000/api/diagnostics")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
