"""Finding 14: `scripts/preflight.sh` hard-failed on a commented-out service.

`scripts/preflight.sh:53-56` derived the required env-file list with

    provider_env_files=$(grep -oE '\\.env\\.[a-z0-9-]+' docker-compose.yml | sort -u)

grep does not know about YAML comments, and `docker-compose.yml` keeps the
`provider-remote-comfy` service block present but commented out, including its
`env_file: - .env.remote-comfy`. The raw extraction therefore demanded an env file
for a service compose will not start, so on a clean host preflight exited 1 —
while the comment right above the line claimed the list "cannot fall behind a new
provider", which is the thing it was actually protecting against.

Verified here WITHOUT running the script: `preflight.sh` may create Docker
networks or otherwise touch Docker, so it must not be executed. What is tested is
the extraction line in isolation, which is the whole of the bug.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
COMPOSE = REPO_ROOT / "docker-compose.yml"
PREFLIGHT = REPO_ROOT / "scripts/preflight.sh"

# Every `env_file:` that belongs to a service compose will actually start.
# One entry per provider container, because compose `env_file:` refuses to render
# without the file and EVERY service then fails to start. Adding a provider
# therefore means adding a line here, which is the point: a new provider that
# ships without its env file breaks the whole stack, not just itself.
REQUIRED = {
    ".env.modal-zetsuke",
    ".env.modal-stepmania",
    ".env.modal-hp196",
    ".env.tts-modal-hp196",
    ".env.llm-local",
    ".env.direct-url",
}
# Present in the file only as text — one inside a commented-out service block, one
# in a header comment.
COMMENT_ONLY = {".env.remote-comfy", ".env.example"}


def _compose_text() -> str:
    return COMPOSE.read_text()


class TestTheExtraction:
    def test_stripping_comments_yields_exactly_the_live_env_files(self):
        """The fix: drop `#`-leading lines before extracting."""
        stripped = "\n".join(
            line for line in _compose_text().splitlines() if not line.lstrip().startswith("#")
        )
        found = set(re.findall(r"\.env\.[a-z0-9-]+", stripped))
        assert found == REQUIRED, (
            f"the required set drifted. missing={REQUIRED - found} "
            f"unexpected={found - REQUIRED}"
        )

    def test_the_pre_rename_extraction_would_have_been_wrong(self):
        """The regression this guards: comment-blind grep."""
        naive = set(re.findall(r"\.env\.[a-z0-9-]+", _compose_text()))
        assert COMMENT_ONLY <= naive, (
            "this test is only meaningful while the naive extraction picks up "
            "comment-only names"
        )
        for name in COMMENT_ONLY:
            assert name not in REQUIRED

    def test_the_command_the_script_runs_is_the_fixed_one(self):
        """The script's own line, read rather than run."""
        source = PREFLIGHT.read_text()
        assert re.search(
            r"provider_env_files=\$\(sed -e 's/#\.\*//' docker-compose\.yml \| "
            r"grep -oE '\\\.env\\\.\[a-z0-9-\]\+' \| sort -u\)",
            source,
        ), (
            "preflight.sh must strip comments before extracting; the comment-blind "
            "grep demanded an env file for a commented-out service"
        )
        # And the plain comment-blind form must be gone.
        assert not re.search(
            r"provider_env_files=\$\(grep -oE", source
        ), "the comment-blind extraction is still in the script"

    def test_compose_still_mentions_the_commented_service(self):
        """The premise: the commented block must stay commented, not be deleted, so
        the test above is testing a real situation."""
        text = _compose_text()
        assert "# provider-remote-comfy:" in text
        assert "#     - .env.remote-comfy" in text


class TestTheExtractionRunsAsTheScriptWould:
    """The actual shell pipeline, in a temp copy, with no network, no Docker and
    no side effects. `docker compose config` is NOT invoked: it would need the real
    env files and would report a different failure."""

    def test_the_pipeline_output_matches_the_required_set(self, tmp_path):
        copy = tmp_path / "docker-compose.yml"
        copy.write_text(_compose_text())

        result = subprocess.run(
            f"sed -e 's/#.*//' {copy} | grep -oE '\\.env\\.[a-z0-9-]+' | sort -u",
            shell=True,
            capture_output=True,
            text=True,
            check=True,
        )
        found = {line for line in result.stdout.split() if line}
        assert found == REQUIRED

    def test_a_new_provider_with_an_env_file_is_picked_up(self):
        """The property the original comment claimed: the list cannot fall behind a
        new provider, provided the new provider is not commented out."""
        injected = _compose_text().replace(
            "  provider-direct-url:",
            "  provider-newthing:\n"
            "    env_file:\n"
            "      - .env.newthing\n"
            "\n"
            "  provider-direct-url:",
            1,
        )
        stripped = "\n".join(
            line for line in injected.splitlines() if not line.lstrip().startswith("#")
        )
        found = set(re.findall(r"\.env\.[a-z0-9-]+", stripped))
        assert ".env.newthing" in found

    def test_a_commented_out_new_provider_is_not_picked_up(self):
        """Which is the whole point."""
        injected = _compose_text().replace(
            "  provider-direct-url:",
            "  # provider-newthing:\n"
            "  #   env_file:\n"
            "  #     - .env.newthing\n"
            "\n"
            "  provider-direct-url:",
            1,
        )
        stripped = "\n".join(
            line for line in injected.splitlines() if not line.lstrip().startswith("#")
        )
        found = set(re.findall(r"\.env\.[a-z0-9-]+", stripped))
        assert ".env.newthing" not in found
        assert found == REQUIRED
