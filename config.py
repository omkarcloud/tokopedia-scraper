"""Configuration for the Tokopedia Scraper. Everything can be set with an environment
variable; the defaults work out of the box.

    PORT              port the API listens on (default 8000)
    TOKOPEDIA_PROXY   proxy URL for every request, e.g. http://user:pass@host:port
                      (default: none, requests go out from your own connection).
                      Your own connection is all Tokopedia needs: no proxy
                      required, so leave this unset.

Everything else below is a plain constant with a working default.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

TOKOPEDIA_PROXY = os.environ.get("TOKOPEDIA_PROXY") or None


# ---- what the code reads off config: defaults for a direct run ----
MAX_RETRIES = 3
RETRY_BACKOFF = 2
TOKOPEDIA_EXIT = TOKOPEDIA_PROXY      # the exit every session leaves through: your proxy, or direct
