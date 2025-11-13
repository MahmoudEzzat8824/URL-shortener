import os
from flask import Flask, render_template_string, request, redirect, jsonify, send_file
from redis import Redis, RedisError
import logging

# --- Constants & Configuration ---

# The characters to use for the short ID, in Base62
BASE62_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = len(BASE62_CHARS)

# Allow hyphen and underscore in user-provided aliases for convenience
ALIAS_EXTRA_CHARS = "-_"
ALLOWED_ALIAS_CHARS = set(BASE62_CHARS + ALIAS_EXTRA_CHARS)

# Max length for a custom alias
MAX_ALIAS_LENGTH = 32

# Reserved single-segment names that shouldn't be allowed as aliases
RESERVED_ALIASES = {"api", "static", "favicon.ico"}

# The Redis key we use for our global counter
URL_COUNTER_KEY = "next_url_id"

# The prefix for the Redis key to look up a long URL
SHORT_TO_LONG_PREFIX = "short:"

# --- Flask & Redis Initialization ---

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

try:
    # Connect to Redis using environment variables or defaults
    redis_host = os.environ.get('REDIS_HOST', 'localhost')
    redis_port = int(os.environ.get('REDIS_PORT', 6379))
    
    redis_db = Redis(host=redis_host, port=redis_port, decode_responses=True)
    redis_db.ping()
    app.logger.info(f"Successfully connected to Redis at {redis_host}:{redis_port}")

except RedisError as e:
    app.logger.error(f"CRITICAL: Could not connect to Redis. {e}")
    redis_db = None

# --- Core Logic ---

def to_base62(num):
    """Encodes a positive integer into a Base62 string."""
    if num == 0:
        return BASE62_CHARS[0]
    
    arr = []
    while num:
        num, rem = divmod(num, BASE)
        arr.append(BASE62_CHARS[rem])
    arr.reverse()
    return "".join(arr)

def get_redis_key(short_id):
    """Helper function to get the full Redis key for a short_id."""
    return f"{SHORT_TO_LONG_PREFIX}{short_id}"

def is_valid_custom_alias(alias: str) -> (bool, str):
    """Validate a custom alias. Returns (is_valid, error_message)."""
    if not alias:
        return False, "Empty alias"
    if len(alias) > MAX_ALIAS_LENGTH:
        return False, f"Alias too long (max {MAX_ALIAS_LENGTH} characters)"
    if alias in RESERVED_ALIASES:
        return False, "That alias is reserved"
    for ch in alias:
        if ch not in ALLOWED_ALIAS_CHARS:
            return False, "Alias contains invalid characters (allowed: 0-9 a-z A-Z - _)"
    return True, ""

# --- Flask Routes ---

@app.route('/')
def index():
    """Serve the index.html file."""
    if not redis_db:
        return "<h1>Error: Redis connection not established.</h1>", 500
    return send_file('index.html')

@app.route('/api/create', methods=['POST'])
def create_short_url():
    """API endpoint to create a new short URL. Supports optional custom alias."""
    if not redis_db:
        return jsonify({"error": "Redis connection not established"}), 500

    data = request.get_json(silent=True) or {}
    long_url = (data.get('long_url') or "").strip()
    custom_alias = (data.get('custom_alias') or "").strip()

    if not long_url:
        return jsonify({"error": "No URL provided"}), 400
    
    # Basic check for a valid-looking URL
    if not (long_url.startswith('http://') or long_url.startswith('https://')):
        long_url = 'http://' + long_url

    try:
        # If a custom alias was provided, validate and try to create it atomically
        if custom_alias:
            is_valid, err_msg = is_valid_custom_alias(custom_alias)
            if not is_valid:
                return jsonify({"error": err_msg}), 400

            redis_key = get_redis_key(custom_alias)
            # NX option ensures we don't overwrite an existing alias
            created = redis_db.set(redis_key, long_url, nx=True)
            if created:
                short_url = f"{request.host_url}{custom_alias}"
                app.logger.info(f"Created custom alias {custom_alias} -> {long_url}")
                return jsonify({"short_url": short_url}), 201
            else:
                return jsonify({"error": "Alias already in use"}), 409

        # Otherwise, generate a new unique ID using the global counter
        new_id_int = redis_db.incr(URL_COUNTER_KEY)
        short_id = to_base62(new_id_int)
        redis_key = get_redis_key(short_id)
        redis_db.set(redis_key, long_url)
        short_url = f"{request.host_url}{short_id}"
        app.logger.info(f"Created auto alias {short_id} -> {long_url}")
        return jsonify({"short_url": short_url}), 201

    except RedisError as e:
        app.logger.error(f"Redis error during URL creation: {e}")
        return jsonify({"error": "Database error"}), 500
    except Exception as e:
        app.logger.error(f"Unknown error during URL creation: {e}")
        return jsonify({"error": "An internal error occurred"}), 500


@app.route('/<string:short_id>')
def redirect_to_long_url(short_id):
    """Handles the redirection for a short URL."""
    if not redis_db:
        return "Error: Redis connection not established.", 500

    try:
        # Look up the short_id in Redis
        redis_key = get_redis_key(short_id)
        long_url = redis_db.get(redis_key)

        if long_url:
            # Found it, redirect the user
            app.logger.info(f"Redirecting {short_id} -> {long_url}")
            return redirect(long_url, code=302)
        else:
            # Not found
            app.logger.warning(f"Short URL not found: {short_id}")
            return "<h1>URL not found</h1>", 404

    except RedisError as e:
        app.logger.error(f"Redis error during redirect: {e}")
        return "<h1>Database error</h1>", 500

# --- Run the App ---

if __name__ == "__main__":
    # Use PORT environment variable if available (for Heroku, Railway, etc.)
    port = int(os.environ.get('PORT', 5001))
    debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host="0.0.0.0", port=port, debug=debug)