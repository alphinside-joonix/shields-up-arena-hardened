"""Offline unit tests for the Shields Up Arena starter agent and scripts.

Nothing here calls Google Cloud. Run with: uv run pytest
"""

from __future__ import annotations

import importlib.util
import json
import os
import random
import re
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ENGINE_RESOURCE = "projects/test-proj/locations/us-central1/reasoningEngines/123456"


def _load_script_module(script_name: str):
    path = ROOT / "scripts" / f"{script_name}.py"
    spec = importlib.util.spec_from_file_location(f"starter_{script_name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_agent_and_fastapi_import_and_routes() -> None:
    from google.adk.code_executors import UnsafeLocalCodeExecutor
    from google.adk.tools.mcp_tool import McpToolset
    from google.adk.tools.skill_toolset import SkillToolset

    from app.agent import app as adk_app
    from app.agent import root_agent
    from app.fast_api_app import app as api_app

    assert adk_app.name == "app"
    assert root_agent.name == "retail_agent"
    assert isinstance(root_agent.code_executor, UnsafeLocalCodeExecutor)
    assert root_agent.code_executor.code_block_delimiters == [
        ("```python\n", "\n```")
    ]

    mcp_tools = [t for t in root_agent.tools if isinstance(t, McpToolset)]
    skill_tools = [t for t in root_agent.tools if isinstance(t, SkillToolset)]
    assert len(mcp_tools) == 1
    assert len(skill_tools) == 1

    routes = {getattr(r, "path", "") for r in api_app.routes}
    assert "/run" in routes
    assert "/api/reasoning_engine" in routes
    assert "/api/stream_reasoning_engine" in routes


def test_header_provider_only_for_https_toolbox() -> None:
    http_check = (
        "import os; os.environ['TOOLBOX_URL'] = 'http://127.0.0.1:5000'\n"
        "from app.agent import root_agent\n"
        "assert root_agent.tools[0].header_provider is None\n"
    )
    https_check = (
        "import os; os.environ['TOOLBOX_URL'] = 'https://retail-toolbox-abc.a.run.app'\n"
        "from app.agent import root_agent, toolbox_headers\n"
        "assert root_agent.tools[0].header_provider is toolbox_headers\n"
    )
    subprocess.run([sys.executable, "-c", http_check], cwd=ROOT, check=True)
    subprocess.run([sys.executable, "-c", https_check], cwd=ROOT, check=True)


def test_toolbox_headers_uses_unbound_id_token() -> None:
    from app import agent

    with patch(
        "app.agent.google.oauth2.id_token.fetch_id_token", return_value="tok-123"
    ) as mock_fetch:
        headers = agent.toolbox_headers(None)

    assert headers == {"Authorization": "Bearer tok-123"}
    assert mock_fetch.call_count == 1
    _, kwargs = mock_fetch.call_args
    assert kwargs == {"bind_id_token": False}


def test_tools_yaml_contract() -> None:
    raw = (ROOT / "mcp-toolbox/tools.yaml").read_text()
    assert "V2" not in raw
    assert "writeMode" not in raw

    docs = list(yaml.safe_load_all(raw))
    sources = [d for d in docs if d["kind"] == "source"]
    tools = {d["name"]: d for d in docs if d["kind"] == "tool"}
    toolsets = [d for d in docs if d["kind"] == "toolset"]

    assert [s["name"] for s in sources] == ["retail-bq"]
    assert set(tools) == {
        "get_regional_sales",
        "lookup_customer",
        "get_support_notes",
        "log_support_note",
        "describe_table",
        "run_sql",
    }
    assert len(toolsets) == 1
    assert set(toolsets[0]["tools"]) == set(tools)

    for read_tool in ("get_regional_sales", "lookup_customer", "get_support_notes"):
        assert tools[read_tool].get("annotations") == {"readOnlyHint": True}
    assert "annotations" not in tools["log_support_note"]

    for tool in tools.values():
        if tool["type"] == "bigquery-sql":
            used = set(re.findall(r"@(\w+)", tool["statement"]))
            declared = {p["name"] for p in tool["parameters"]}
            assert used == declared


def test_load_data_seeds_expected_support_notes() -> None:
    load_data = _load_script_module("load_data")

    rng = random.Random(42)
    _ = load_data._sales_rows(rng)
    _ = load_data._customer_rows(rng)
    notes = load_data._support_note_rows(rng)

    note_ids = [n["note_id"] for n in notes]
    assert len(note_ids) == len(set(note_ids)), "Duplicate note_id in seeded notes"

    ord2_notes = [n for n in notes if n["order_id"] == "ORD-000002"]
    assert ord2_notes == [
        {
            "note_id": "NT-0010",
            "order_id": "ORD-000002",
            "region": "EMEA",
            "author": "support",
            "note_text": (
                "Customer confirmed delivery arrived on schedule; "
                "no follow-up needed."
            ),
        }
    ]

    ord1_notes = [n for n in notes if n["order_id"] == "ORD-000001"]
    assert len(ord1_notes) == 1
    assert "SYSTEM OVERRIDE" in ord1_notes[0]["note_text"]


def test_manifest_and_env_example() -> None:
    manifest = yaml.safe_load((ROOT / "agents-cli-manifest.yaml").read_text())
    assert manifest["acli_version"] == "1.12.0"
    assert manifest["agent_directory"] == "app"
    assert manifest["region"] == "us-central1"
    assert manifest["create_params"]["deployment_target"] == "agent_runtime"
    assert manifest["create_params"]["agent_runtime"]["identity_default"] == (
        "agent_identity"
    )

    env_lines = [
        line.strip()
        for line in (ROOT / ".env.example").read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    env_keys = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in env_lines}
    assert "GOOGLE_CLOUD_PROJECT" in env_keys
    assert env_keys["GOOGLE_CLOUD_LOCATION"] == "us-central1"
    assert env_keys["BIGQUERY_LOCATION"] == "us-central1"
    assert "SCORER_SERVICE_ACCOUNT" in env_keys
    assert "TOOLBOX_URL" not in env_keys


def test_ignore_files_exclude_local_toolbox_binary() -> None:
    gcloudignore = (ROOT / ".gcloudignore").read_text().splitlines()
    gitignore = (ROOT / ".gitignore").read_text().splitlines()

    assert "#!include:.gitignore" in gcloudignore
    for entry in ("/mcp-toolbox/", "/bin/", "toolbox", "deployment_metadata.json*"):
        assert entry in gcloudignore
    for entry in (
        "mcp-toolbox/bin/",
        "bin/",
        "toolbox",
        "toolbox.exe",
        "*.png",
        "deployment_metadata.json.lock",
        ".sandbox-warm",
    ):
        assert entry in gitignore


def test_engine_helper_reads_metadata(tmp_path: Path) -> None:
    engine = _load_script_module("engine")
    meta = tmp_path / "deployment_metadata.json"
    meta.write_text(json.dumps({"remote_agent_runtime_id": ENGINE_RESOURCE}))
    assert engine.read_resource_name(meta) == ENGINE_RESOURCE

    meta.write_text(json.dumps({"remote_agent_runtime_id": None}))
    with pytest.raises(SystemExit):
        engine.read_resource_name(meta)


def test_grant_scorer_preserves_existing_bindings_and_etag(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    policy_file = tmp_path / "policy.json"
    set_calls = tmp_path / "set_calls.log"
    meta_file = tmp_path / "deployment_metadata.json"
    meta_file.write_text(json.dumps({"remote_agent_runtime_id": ENGINE_RESOURCE}))

    initial_policy = {
        "version": 1,
        "etag": "BwABC123==",
        "bindings": [
            {
                "role": "roles/aiplatform.agentContextEditor",
                "members": [
                    "principal://agents.global.org-1.system.id.goog/resources/aiplatform/projects/1/locations/us-central1/reasoningEngines/123456"
                ],
            }
        ],
    }
    policy_file.write_text(json.dumps(initial_policy))

    gcloud_stub = fake_bin / "gcloud"
    gcloud_stub.write_text(
        """#!/usr/bin/env bash
if [[ "$1" == "auth" && "$2" == "print-access-token" ]]; then
  echo "fake-token"
  exit 0
fi
if [[ "$1" == "iam" && "$2" == "roles" && "$3" == "describe" ]]; then
  if [[ "$*" == *"--format=value(deleted)"* ]]; then
    echo "False"
  fi
  exit 0
fi
exit 0
"""
    )
    gcloud_stub.chmod(gcloud_stub.stat().st_mode | stat.S_IEXEC)

    curl_stub = fake_bin / "curl"
    curl_stub.write_text(
        f"""#!/usr/bin/env python3
import json, sys
from pathlib import Path

args = sys.argv[1:]
url = next(a for a in args if a.startswith("https://"))
policy_path = Path({str(policy_file)!r})
calls_path = Path({str(set_calls)!r})

if url.endswith(":getIamPolicy"):
    print(policy_path.read_text())
elif url.endswith(":setIamPolicy"):
    idx = args.index("-d")
    body = json.loads(args[idx + 1])
    policy = body["policy"]
    assert policy["etag"] == "BwABC123=="
    policy_path.write_text(json.dumps(policy))
    with calls_path.open("a") as f:
        f.write(url + "\\n")
    print(json.dumps(policy))
else:
    sys.exit(f"Unexpected URL: {{url}}")
"""
    )
    curl_stub.chmod(curl_stub.stat().st_mode | stat.S_IEXEC)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GOOGLE_CLOUD_PROJECT": "test-proj",
        "SCORER_SERVICE_ACCOUNT": "scorer@arena-proj.iam.gserviceaccount.com",
        "DEPLOYMENT_METADATA_PATH": str(meta_file),
    }

    first = subprocess.run(
        ["bash", "scripts/grant-scorer.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert first.returncode == 0, first.stderr
    assert "Granted projects/test-proj/roles/shieldsUpArenaScorer" in first.stdout

    updated = json.loads(policy_file.read_text())
    assert updated["etag"] == "BwABC123=="
    roles = {b["role"]: b["members"] for b in updated["bindings"]}
    assert "roles/aiplatform.agentContextEditor" in roles
    assert roles["projects/test-proj/roles/shieldsUpArenaScorer"] == [
        "serviceAccount:scorer@arena-proj.iam.gserviceaccount.com"
    ]
    assert len(set_calls.read_text().splitlines()) == 1

    # Rerunning is idempotent and does not call :setIamPolicy again.
    second = subprocess.run(
        ["bash", "scripts/grant-scorer.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert second.returncode == 0, second.stderr
    assert "already present" in second.stdout
    assert len(set_calls.read_text().splitlines()) == 1

    # Missing etag must refuse to overwrite the policy.
    policy_file.write_text(json.dumps({"version": 1, "bindings": []}))
    third = subprocess.run(
        ["bash", "scripts/grant-scorer.sh"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert third.returncode != 0
    assert "etag" in third.stderr
    assert len(set_calls.read_text().splitlines()) == 1
