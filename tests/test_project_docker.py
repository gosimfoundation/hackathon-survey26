"""Actual container -> Python Runner -> simulator -> scorer integration.

Set OBSERVER_TEST_PYTHON_IMAGE / OBSERVER_TEST_RUST_IMAGE to resolved image
digests. CI supplies them after pulling the selected public test images.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from challenge.challenge_workflow import ChallengeWorkflow
from challenge.scenario_builder import generate_scenario
from challenge.scoring_core import score_files
from project_platform.docker_runtime import DockerWorkspace, RuntimeLimits
from project_platform.manifest import ProjectManifest


@pytest.fixture(scope="module")
def public_scenario(tmp_path_factory):
    root = tmp_path_factory.mktemp("project-public") / "scenario"
    generate_scenario(root, scenario_id="project-runtime-test", seed=71, days=7,
                      start_date="2026-10-05", global_wallclock_seconds=30)
    return root


def _run(workspace: Path, manifest: dict, scenario: Path, out: Path, env=None):
    parsed = ProjectManifest.parse(manifest)
    workflow = ChallengeWorkflow(scenario)
    with DockerWorkspace(workspace, parsed, parsed.image, limits=RuntimeLimits(build_seconds=90)) as runtime:
        try:
            runtime.build()
        except Exception as exc:
            pytest.fail(f"{exc}\n{runtime.build_log}")
        transport = runtime.start(env or {})
        result = workflow.run(transport, wallclock_seconds=30)
        runtime.close()
        log = transport.log
    workflow.write_outputs(out, result)
    scored = score_files(scenario, out / "decisions.csv", out / "score.json", result["termination_reason"])
    assert result["termination_reason"] == "survey_complete", (result.get("commit_log"), log)
    assert result["committed_action_count"] > 0
    assert scored["score"]["total"] == pytest.approx(result["score_report"]["score"]["total"])
    return result, log


@pytest.mark.skipif(not os.environ.get("OBSERVER_TEST_PYTHON_IMAGE"), reason="Explicit container test image required")
def test_python_project_isolated_from_hidden_files_and_host_credentials(tmp_path, public_scenario, monkeypatch):
    workspace = tmp_path / "project"
    workspace.mkdir()
    hidden = tmp_path / "not-mounted.txt"
    hidden.write_text("hidden scenario marker")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "host-only-secret")
    (workspace / "agent.py").write_text("""
import json, os, sys
print(json.dumps({'hidden_file_visible':os.path.exists(os.environ['PROBE_PATH']),
 'admin_key_visible':'SUPABASE_SERVICE_ROLE_KEY' in os.environ,
 'docker_socket_visible':os.path.exists('/var/run/docker.sock'),
 'scoped_token':os.environ.get('OBSERVER_RUN_TOKEN')}), file=sys.stderr, flush=True)
for line in sys.stdin:
 m=json.loads(line)
 if m['message_type']=='initialize': continue
 tiles=[t for t in m['payload']['candidate_tiles'] if t['effective_weather']['is_observable']]
 t=tiles[0] if tiles else None
 print(json.dumps({'protocol_version':m['protocol_version'],'message_type':'decision_response',
 'decision_sequence':m['decision_sequence'],'action':'observe' if t else 'wait',
 'tile_id':t['tile_id'] if t else '', 'program':'BACKUP' if t else ''}),flush=True)
""")
    manifest = {"schema_version": "observer-project-v1", "image": os.environ["OBSERVER_TEST_PYTHON_IMAGE"],
                "run": ["python3", "-u", "agent.py"], "environment": {"PROBE_PATH": str(hidden)}}
    result, log = _run(workspace, manifest, public_scenario, tmp_path / "result",
                       {"OBSERVER_RUN_TOKEN": "test-scoped-run-token"})
    probe = json.loads(next(line for line in log.splitlines() if line.startswith('{"hidden_file_visible"')))
    assert probe == {"hidden_file_visible": False, "admin_key_visible": False,
                     "docker_socket_visible": False, "scoped_token": "[REDACTED]"}
    assert result["score_report"]["completion"]["completed_tiles"]


@pytest.mark.skipif(not os.environ.get("OBSERVER_TEST_RUST_IMAGE"), reason="Explicit container test image required")
def test_complete_rust_project_builds_and_runs_under_python_runner(tmp_path, public_scenario):
    workspace = tmp_path / "project"
    workspace.mkdir()
    # No Python interpreter, generated Python agent, or third-party Rust package is needed.
    (workspace / "agent.rs").write_text(r'''
use std::io::{self, BufRead, Write};
fn main() {
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        if !line.contains("decision_request") { continue; }
        let after = line.split("\"decision_sequence\":").nth(1).unwrap();
        let seq: String = after.chars().take_while(|c| c.is_ascii_digit()).collect();
        println!("{{\"protocol_version\":\"participant-agent-protocol-v2\",\"message_type\":\"decision_response\",\"decision_sequence\":{},\"action\":\"wait\"}}", seq);
        io::stdout().flush().unwrap();
    }
}
''')
    manifest = {"schema_version": "observer-project-v1", "image": os.environ["OBSERVER_TEST_RUST_IMAGE"],
                "build": [["rustc", "agent.rs", "-o", "agent"]], "run": ["./agent"]}
    result, _ = _run(workspace, manifest, public_scenario, tmp_path / "result")
    assert result["committed_action_count"] >= len(ChallengeWorkflow(public_scenario).scorer.slots)


def _packed_kit(tmp_path: Path) -> Path:
    import subprocess
    import sys
    from project_platform.package import extract_project, read_project_zip
    root = Path(__file__).resolve().parents[1]
    out = tmp_path / "my-agent.zip"
    subprocess.run([sys.executable, str(root / "starter_kit" / "pack_agent.py"), "--out", str(out)], check=True,
                   capture_output=True)
    workspace = tmp_path / "kit-project"
    extract_project(read_project_zip(out.read_bytes()), workspace)
    return workspace


@pytest.mark.skipif(not os.environ.get("OBSERVER_TEST_PYTHON_IMAGE"), reason="Explicit container test image required")
def test_packed_starter_kit_runs_in_the_container_without_a_model_key(tmp_path, public_scenario):
    workspace = _packed_kit(tmp_path)
    manifest = json.loads((workspace / "observer.project.json").read_text())
    assert manifest["image"] == "python:3.12-slim"
    manifest["image"] = os.environ["OBSERVER_TEST_PYTHON_IMAGE"]  # the digest preparation would resolve
    _result, log = _run(workspace, manifest, public_scenario, tmp_path / "result",
                        {"OPENAI_BASE_URL": "http://127.0.0.1:9/v1", "OPENAI_API_KEY": "obs_test-run-credential"})
    assert "minimal-agent provider=deterministic" in log


@pytest.mark.skipif(not os.environ.get("OBSERVER_TEST_PYTHON_IMAGE"), reason="Explicit container test image required")
def test_starter_kit_model_build_step_from_the_readme_installs_and_starts(tmp_path, public_scenario):
    """The documented build step installs requirements as the non-root, read-only container user. The proxy
    address is unreachable here, so every model call falls back to the deterministic choice."""
    workspace = _packed_kit(tmp_path)
    manifest = json.loads((workspace / "observer.project.json").read_text())
    manifest.update({
        "image": os.environ["OBSERVER_TEST_PYTHON_IMAGE"],
        "build": [["python3", "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check",
                   "--target", ".deps", "-r", "requirements.txt"]],
        "environment": {"PYTHONPATH": ".deps", "PYTHONDONTWRITEBYTECODE": "1", "MODEL_PROVIDER": "openai",
                        "LLM_MAX_RETRIES": "0", "LLM_TIMEOUT_SECONDS": "2"},
    })
    parsed = ProjectManifest.parse(manifest)
    with DockerWorkspace(workspace, parsed, parsed.image, limits=RuntimeLimits(build_seconds=600)) as runtime:
        try:
            runtime.build()
        except Exception as exc:
            pytest.fail(f"{exc}\n{runtime.build_log}")
        transport = runtime.start({"OPENAI_BASE_URL": "http://127.0.0.1:9/v1", "OPENAI_API_KEY": "obs_test-run-credential"})
        result = ChallengeWorkflow(public_scenario).run(transport, wallclock_seconds=120)
        runtime.close()
    assert result["termination_reason"] == "survey_complete", (result.get("commit_log"), transport.log)
    assert "minimal-agent provider=openai" in transport.log
