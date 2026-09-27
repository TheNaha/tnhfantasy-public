Operator-run Modal benchmarks, not part of the package: nothing imports or executes these, and `provider_containers` has to stay importable standalone (neither Dockerfile copies `backend_v2`).

Run from this directory with the provider venv active, e.g. `modal run bench_generate.py --suite lora`. `bench_volume_load.py` was deleted: it hardcoded a volume name (`comfy-storage-v2`) that appears nowhere else in the repo, so it could not have been measuring the deployed volume even when it was written — use `bench_generate.py` for an end-to-end wall-clock measurement against the real app.
