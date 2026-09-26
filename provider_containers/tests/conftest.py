import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
root_str = str(ROOT)

if root_str not in sys.path:
    sys.path.insert(0, root_str)

# `remote_agent/` is a sibling of `provider_containers/`, not a package inside it,
# so it is not importable from the suite's default sys.path. The two trees are
# deliberately independent (the agent ships as a standalone frozen binary), but
# server.py is worth testing here — it is where the download pipeline, the delete
# sweep and the validation predicates all meet.
REPO_ROOT = ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ...and it raises at IMPORT unless a token is set (remote_agent/server.py:23-24):
#
#     if not TOKEN and not ALLOW_INSECURE:
#         raise RuntimeError("REMOTE_AGENT_TOKEN must be set unless ...")
#
# so the test environment must supply one before any import. `setdefault`, never
# an assignment: a developer's real value is never overwritten, and the value
# below is an obvious placeholder, not a credential.
os.environ.setdefault("REMOTE_AGENT_TOKEN", "test-token")
