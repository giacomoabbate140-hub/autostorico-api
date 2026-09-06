from __future__ import annotations

import sys
import server_core as _server_core

# Compatibility entrypoint for Render.
# When imported as `server`, apply the lightweight runtime improvements first,
# then expose the original API module so patched_server keeps working. When
# Render executes `python server.py`, launch the enhanced patched server even if
# the dashboard still has the old Start Command configured.
if __name__ == "__main__":
    import patched_server

    patched_server.server.main()
else:
    import defect_search_patch  # noqa: F401 - applies safe server_core overrides

    sys.modules[__name__] = _server_core
