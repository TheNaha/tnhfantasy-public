"""`provider_core` as the deployables found it, minus everything they never used.

`provider_core` used to live at `provider_containers/provider_core/`, a *sibling
of nothing in particular* that every worker imported by bare name: the Modal
apps, the Beam app and the container `worker.py` HTTP apps all relied on it
being importable as a top-level package from their own directory. Commit
`acc86aa3` ("Remove containerized provider workers; provider_core moves to
remote_agent") deleted every one of those consumers and moved the package to
`remote_agent/provider_core/`, where its only remaining consumer is
`remote_agent/server.py`. That slimming removed the worker-only modules
outright (`comfy_lifecycle`, `model_scan`) and cut the worker-only halves out of
the shared ones — `SharedHttpClient`/`get_http_client` went with the connection
pool the remote agent never used, `outcome()` went with the nine
`{"success": bool, ...}` returns it was invented to replace.

The cloud deployables in `deployables/` still need all of it, and they are not
served by the remote agent's copy: they are separate containers with separate
dependency sets, deployed from separate sources, and they will not import
anything from `remote_agent` at runtime. So this package restores exactly the
modules they import, at `acc86aa3^`, and nothing else.

It is a deliberate fork of two modules that still exist upstream:

* `http_client.py` vs `remote_agent/provider_core/http_client.py` — the live
  one is a 30-line stub holding only `get_file_size_cap`, which the remote agent
  still uses for `/get-file`.
* `responses.py` vs `remote_agent/provider_core/responses.py` — the live one
  kept `ok`/`failed`/`from_upstream` and dropped `outcome` and the LLM health
  helpers.

Both are recovered verbatim; the only edit is in `model_scan.py`, whose
`from .utils import is_model_file` had to become an absolute import because
this package is not the `provider_core` it was carved out of. `is_model_file`
itself survives in the live `provider_core.utils`, which is where the import
points now. If a bug is found in `get_safe_path`, `download_model_to_path` or
the response envelope, fix it in `remote_agent/provider_core/` and copy the
change here — the two copies no longer share a test suite.
"""