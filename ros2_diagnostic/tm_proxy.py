#!/usr/bin/env python3
"""
Time Machine Web Proxy with Digest Authentication
Proxies HTTP requests to Time Machine (192.168.0.20) with automatic Digest auth

Note: This standalone proxy service uses Flask (not FastAPI) for simplicity
as a lightweight reverse proxy with digest auth forwarding.
"""

import sys
import os
from flask import Flask, request, Response, stream_with_context
import requests
from requests.auth import HTTPDigestAuth

# Configuration
TM_HOST = "192.168.0.20"
TM_PORT = 80
TM_USERNAME = os.getenv("TM_USERNAME", "admin")
TM_PASSWORD = os.getenv("TM_PASSWORD", "admin")
TM_REALM = os.getenv("TM_REALM", "Server authentication required")

app = Flask(__name__)

# Create a session with digest auth
session = requests.Session()
session.auth = HTTPDigestAuth(TM_USERNAME, TM_PASSWORD)


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'HEAD', 'OPTIONS'])
def proxy(path):
    """Proxy request to Time Machine with Digest authentication"""

    # Build target URL
    target_url = f"http://{TM_HOST}:{TM_PORT}/{path}"
    if request.query_string:
        target_url += f"?{request.query_string.decode()}"

    try:
        # Forward the request
        resp = session.request(
            method=request.method,
            url=target_url,
            headers={k: v for k, v in request.headers if k.lower() != 'host'},
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=False,
            stream=True,
            timeout=30
        )

        # Build response
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        response_headers = [(k, v) for k, v in resp.headers.items()
                           if k.lower() not in excluded_headers]

        return Response(
            stream_with_context(resp.iter_content(chunk_size=8192)),
            resp.status_code,
            response_headers
        )

    except requests.exceptions.RequestException as e:
        return f"Error connecting to Time Machine: {str(e)}", 503


if __name__ == '__main__':
    port = int(os.getenv("PORT", 8083))
    print(f"Starting Time Machine Proxy on port {port}")
    print(f"Forwarding to {TM_HOST}:{TM_PORT}")
    print(f"Using username: {TM_USERNAME}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
