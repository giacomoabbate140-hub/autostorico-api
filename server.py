from __future__ import annotations

import sys
import server_core as _server_core

# Compatibility entrypoint for Render.
# When imported as `server`, expose the original API module unchanged so tests
# and patched_server keep working. When Render executes `python server.py`,
# launch the enhanced patched server even if the dashboard still has the old
# Start Command configured.
if __name__ == "__main__":
    import patched_server

    patched_server.server.main()
else:
    sys.modules[__name__] = _server_core
