"""The Colab notebook's paths have to agree with where the code actually is.

The notebook was written for Colab, where the checkout lives under
`/content`. It was then run on Modal, where the checkout lives under
`/root` — and nothing in the notebook knew that.

The result was a **hard failure at cell 5**:

    ModuleNotFoundError: No module named 'ram_manager'

because cell 5 put `/content/tnhcomfy/remote_agent` on `sys.path` — the
Colab path — while cell 3 had cloned the repository to `/root/tnhcomfy`, and
`remote_agent` was not where anything was looking for it.

The subtle part is WHY the two disagreed. Cell 3 chose the workspace root by
asking "does `/content` exist?", and cell 4 MOUNTS Google Drive at
`/content/drive` — which CREATES `/content`. So the answer to that question
depended on which cell asked it and when. On Modal, cell 3 (before the
drive mount) saw no `/content` and cloned to `/root`; cell 5 (after it) saw
`/content` and looked there.

The rule is now the same in every cell, and it is derived from the
ENVIRONMENT — Colab gets `/content`, Modal gets `/root` — so it cannot
change under a cell's feet.

These tests pin that.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re

import pytest

from repo_paths import require_repo_root

ROOT = require_repo_root("the Colab notebook generator")

GENERATOR = ROOT / "scripts" / "update_colab_notebooks.py"

#: The Google Drive mount point. It is genuinely `/content/drive` on Colab
#: and is only ever used inside an `if is_colab` branch.
_GDRIVE = re.compile(r'["\'](/content/drive[^"\']*)["\']')

#: A path under /content that is NOT the Google Drive mount.
_HARD_CODED = re.compile(r'["\'](/content/(?!drive)[^"\']*)["\']')


def _load_generator():
    spec = importlib.util.spec_from_file_location("ucn_paths", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cells() -> dict[int, str]:
    module = _load_generator()
    return {i: "".join(getattr(module, f"build_cell_{i}_source")()) for i in range(1, 8)}


def _balanced_block(source: str, start: int) -> str:
    """The parenthesised block that starts at `start`."""
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "(":
            depth += 1
        elif source[index] == ")":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError("unbalanced parentheses")


def _normalise_rule(rule: str) -> str:
    """Collapse whitespace and the flag names, so two spellings of one rule compare equal."""
    rule = re.sub(r"\s+", " ", rule)
    rule = re.sub(r"\b_?IS_COLAB\b", "COLAB", rule)
    rule = re.sub(r"\b_?IS_MODAL\b", "MODAL", rule)
    return rule.strip()


def _workspace_rules() -> list[tuple[int, str]]:
    """Every workspace-root RULE in the notebook, normalised.

    A rule is the parenthesised conditional. A plain assignment
    (`workspace_root = WORKSPACE_ROOT`, in the cell that shares the name) is
    not a rule and is skipped.
    """
    found = []
    for index, source in _cells().items():
        for match in re.finditer(r"workspace_root = ", source):
            rest = source[match.end():]
            if not rest.lstrip().startswith("("):
                continue
            block = _balanced_block(source, match.end() + len(rest) - len(rest.lstrip()))
            found.append((index, _normalise_rule(block)))
    return found


class TestTheNotebookIsGenerated:
    def test_every_cell_is_valid_python(self):
        """A cell that does not parse is a notebook that fails on the first run."""
        for index, source in _cells().items():
            try:
                ast.parse(source)
            except SyntaxError as exc:
                pytest.fail(f"cell {index} does not parse: {exc}")

    def test_the_generator_is_the_source_of_truth(self):
        """The `.ipynb` files are OUTPUT. Editing them directly is overwritten.

        The generator writes the source of cells 1-7 into both copies, and only
        the markdown header (cell 0) is hand-maintained. A notebook that
        disagrees with its generator is a notebook whose fix does not survive
        the next regeneration.
        """
        module = _load_generator()
        for path in (
            ROOT / "TNHComfy_Colab_Worker.ipynb",
            ROOT / "remote_agent" / "TNHComfy_Colab_Worker.ipynb",
        ):
            if not path.exists():
                continue
            notebook = json.loads(path.read_text())
            for index in range(1, 8):
                expected = "".join(getattr(module, f"build_cell_{index}_source")())
                actual = "".join(notebook["cells"][index].get("source", []))
                assert actual == expected, (
                    f"{path.name} cell {index} differs from the generator. Edit "
                    f"scripts/update_colab_notebooks.py and regenerate."
                )


class TestTheWorkspaceRootIsEnvironmentDerived:
    def test_every_cell_that_needs_it_defines_it(self):
        """A cell that uses the root must define it.

        They are separate cells in a notebook: cell 5 does not inherit cell
        4's namespace, so each one that needs the root has to work it out
        again. That is why the rule is a fixed expression rather than a
        shared constant.
        """
        for index, source in _cells().items():
            if "WORKSPACE_ROOT" not in source:
                continue
            if "WORKSPACE_ROOT =" in source:
                continue
            pytest.fail(
                f"cell {index} uses WORKSPACE_ROOT but never defines it. A "
                f"notebook cell does not inherit the previous cell's names."
            )

    def test_the_rule_is_the_same_everywhere(self):
        """One rule, spelled the same in every cell.

        The cells disagreeing is the bug: cell 3 asked whether `/content`
        EXISTED, and cell 4 creates `/content` by mounting Google Drive on
        it, so the answer changed between them.
        """
        rules = _workspace_rules()
        assert rules, "no workspace-root rule was found at all"
        shapes = {rule for _index, rule in rules}
        assert len(shapes) == 1, (
            "the workspace-root rule is spelled differently in different "
            f"cells: {shapes}"
        )
        (rule,) = shapes
        assert '"/content"' in rule, "Colab's checkout lives under /content"
        assert '"/root"' in rule, "Modal's checkout lives under /root"
        assert "os.path.exists" in rule, (
            "the fallback for a host that is neither must be its home "
            "directory"
        )

    def test_it_does_not_ask_whether_a_content_directory_exists(self):
        """The rule must not depend on the filesystem.

        "Does /content exist?" is not a property of the backend; it is a
        property of what an earlier cell happened to do. Cell 4 mounts Google
        Drive at /content/drive, so the answer CHANGES under a later cell's
        feet.
        """
        for index, source in _cells().items():
            for rule_index, rule in _workspace_rules():
                if rule_index != index:
                    continue
                assert 'os.path.exists("/content")' not in rule, (
                    f"cell {index} decides the workspace root by asking "
                    f"whether /content exists"
                )


class TestNoHardcodedWorkspacePaths:
    """Every workspace path goes through the rule.

    The Google Drive mount point is the exception: it is genuinely
    `/content/drive` on Colab and is only used inside `if is_colab` branches.
    """

    def test_no_cell_hardcodes_a_content_path(self):
        offenders = []
        for index, source in _cells().items():
            for line in source.splitlines():
                if "WORKSPACE_ROOT" in line:
                    continue
                for match in _HARD_CODED.finditer(line):
                    offenders.append(f"cell {index}: {match.group(0)}")
        assert not offenders, (
            "these paths assume the Colab layout and will not exist on Modal:\n  "
            + "\n  ".join(offenders)
        )

    def test_the_google_drive_mount_is_the_only_exception(self):
        """And it is only MOUNTED where Google Drive is actually mounted.

        The mount is `/content/drive` on Colab, and the cells that use it
        are inside an `if is_colab` branch. A path that is merely PRINTED
        (the telemetry lines) is not a path.
        """
        for index, source in _cells().items():
            uses_mount = (
                'drive.mount("/content/drive")' in source
                or 'os.path.exists("/content/drive/MyDrive")' in source
            )
            if not uses_mount:
                continue
            assert "is_colab" in source or "IS_COLAB" in source, (
                f"cell {index} mounts Google Drive without a Colab guard"
            )

    def test_the_agent_dir_is_derived(self):
        """The one that broke the notebook."""
        for index, source in _cells().items():
            if "from ram_manager import" not in source:
                continue
            assert '"/content/tnhcomfy/remote_agent"' not in source, (
                f"cell {index} puts a hardcoded Colab path on sys.path"
            )
            assert "WORKSPACE_ROOT" in source or "workspace_root" in source, (
                f"cell {index} imports the ram manager without deriving the path"
            )


class TestTheLlamaServerIsVerified:
    """The notebook must not declare a provider healthy it cannot serve.

    The CUDA llama.cpp release is built for a specific Ubuntu and needs a
    glibc the container may not have — the b11647 CUDA 12.8 bundle wants
    GLIBC 2.38, and Modal's Debian 12 image has 2.36.

    The install used to be TRUSTED ON SIGHT: a cached bundle was restored
    from Google Drive and the notebook carried on. The binary could not
    start, the loader error scrolled past as a "device notice", and the
    notebook reported "Remote Agent is online and healthy" and "ComfyUI is
    online and healthy". The failure then surfaced much later, as a 503 from
    a provider that had been declared healthy — with nothing in the log to
    explain it.
    """

    def test_the_install_is_verified_by_running_the_binary(self):
        for index, source in _cells().items():
            if "_install_llama_server" not in source:
                continue
            assert "_llama_can_run(" in source, (
                f"cell {index} installs llama-server without checking that it "
                f"can run"
            )
            # And the check is a real run, not a file-exists test.
            assert '"--version"' in source, (
                f"cell {index} does not verify llama-server by running it"
            )

    def test_a_bundle_that_cannot_run_is_not_cached_again(self):
        """The cache is what made the failure permanent.

        The bundle was cached in Google Drive and restored on every run, so
        the same broken binary came back each time. A bundle that cannot run
        has to be discarded, not re-cached.
        """
        for index, source in _cells().items():
            if "_install_llama_server" not in source:
                continue
            body = source[source.index("def _install_llama_server"):]
            body = body[: body.index("\ndef ") if "\ndef " in body else len(body)]
            assert "os.remove(cached_bundle)" in body, (
                f"cell {index} keeps a bundle that cannot run, and restores "
                f"it on every run"
            )

    def test_there_is_a_source_build_fallback(self):
        """A prebuilt binary cannot be made to work on an older glibc.

        glibc cannot be swapped without breaking the rest of the container,
        so the only universal answer is to build against the toolchain that
        is there.
        """
        for index, source in _cells().items():
            if "_install_llama_server" not in source:
                continue
            assert "_build_llama_from_source" in source, (
                f"cell {index} has no source-build fallback"
            )
            assert "GGML_CUDA=ON" in source, (
                f"cell {index}'s source build is not a CUDA build"
            )

    def test_the_readiness_check_looks_at_the_llm(self):
        """In hybrid mode there is no LLM port to probe — it is Just-In-Time.

        So the only startup check for the LLM is that the BINARY can start.
        Without it, a provider that can never serve a completion is declared
        healthy.
        """
        for index, source in _cells().items():
            if "healthy_services = set()" not in source:
                continue
            assert '_llama_can_run(target_llama)' in source, (
                f"cell {index} declares the stack healthy without checking "
                f"that llama-server can run"
            )

    def test_a_loader_error_is_not_a_notice(self):
        """The GLIBC error was printed as a "device notice" and read as one.

        It is the entire explanation for a 503, so it has to be loud.
        """
        for index, source in _cells().items():
            if "llama-server device notice" not in source:
                continue
            around = source[max(0, source.index("llama-server device notice") - 900):]
            assert "could not start" in around, (
                f"cell {index} prints a loader error as a notice"
            )


class TestTheShmRemountIsGuarded:
    def test_it_only_runs_when_shm_is_too_small(self):
        """The remount needs CAP_SYS_ADMIN, which a container does not have.

        It ran unconditionally and printed the kernel's "mount: /dev/shm:
        permission denied" wherever the container had no privilege — on Modal,
        where /dev/shm is already 40 GB and the remount was never wanted.
        """
        remounts = 0
        for index, source in _cells().items():
            if "remount,size=" not in source:
                continue
            remounts += 1
            assert "current_shm_gb < target_shm_gb" in source, (
                f"cell {index} remounts /dev/shm without checking its size"
            )
            # And quietly: the kernel's error is not the operator's problem
            # to read.
            assert "stderr=subprocess.DEVNULL" in source, (
                f"cell {index} lets the kernel's mount error through"
            )
        assert remounts >= 1, "no remount was found at all"
