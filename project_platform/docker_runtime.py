"""The production project launcher: bounded containers, with no host fallback."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .egress import NETWORK_PATTERN
from .manifest import ProjectError, ProjectManifest
from .transport import AGENT_LOG_BYTES, ExecutionError, JsonlTransport

_RESOLVED_IMAGE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/:-]*@sha256:[0-9a-f]{64}$")
_RUNTIME_ENV = {"OBSERVER_API_URL", "OBSERVER_RUN_TOKEN", "OBSERVER_RUN_ID",
                "OPENAI_BASE_URL", "OPENAI_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY"}


@dataclass(frozen=True)
class RuntimeLimits:
    memory_mb: int = 2048
    cpus: float = 2.0
    processes: int = 128
    build_seconds: int = 600

    def __post_init__(self):
        if not (128 <= self.memory_mb <= 8192 and 0.25 <= self.cpus <= 4 and
                16 <= self.processes <= 256 and 1 <= self.build_seconds <= 1800):
            raise ProjectError("Runtime limits are outside the platform's allowed range.")


class DockerWorkspace:
    """A disposable, already-extracted source tree; never a simulator directory."""

    def __init__(self, root: Path, manifest: ProjectManifest, resolved_image: str,
                 *, limits: RuntimeLimits | None = None):
        self.root = root.resolve(strict=True)
        self.manifest = manifest
        self.image = resolved_image
        self.limits = limits or RuntimeLimits()
        if not _RESOLVED_IMAGE.fullmatch(resolved_image):
            raise ProjectError("Formal runtime image must be resolved and approved by digest.")
        if manifest.image != resolved_image:
            raise ProjectError("Runtime image differs from the reviewed project manifest.")
        if not self.root.is_dir():
            raise ProjectError("Project workspace is not a directory.")
        workdir = self.root / manifest.working_directory
        if not workdir.is_dir() or not workdir.resolve().is_relative_to(self.root):
            raise ProjectError("Project working directory is missing or outside its workspace.")
        self.name = "observer-" + uuid.uuid4().hex
        # None: Docker's default bridge. Otherwise the per-run internal network of
        # project_platform.egress; only the run step joins it, a reviewed build
        # keeps the bridge (package registries).
        self.network: str | None = None
        self.transport: JsonlTransport | None = None
        self.build_log = ""
        # Only explicitly safe client settings reach the Docker CLI. They are not
        # passed into the participant container.
        self.client_env = {key: os.environ[key] for key in
                           ("PATH", "HOME", "TMPDIR", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG")
                           if key in os.environ}

    def _command(self, *, name: str, environment: Mapping[str, str], network: str = "bridge") -> list[str]:
        lim = self.limits
        args = [
            "docker", "run", "--rm", "--interactive", "--name", name,
            # Match the disposable workspace owner. With all capabilities
            # dropped, container root cannot write another UID's mode-0700
            # temporary directory on Linux (Docker Desktop can mask this bug).
            "--user", f"{self.root.stat().st_uid}:{self.root.stat().st_gid}",
            "--label", "observer.project-runtime=true",
            "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--memory", f"{lim.memory_mb}m", "--memory-swap", f"{lim.memory_mb}m",
            "--cpus", str(lim.cpus), "--pids-limit", str(lim.processes),
            "--ulimit", "nofile=512:512", "--ulimit", "fsize=268435456:268435456",
            "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=256m",
            "--network", network, "--log-driver", "none",
            "--mount", f"type=bind,src={self.root},dst=/workspace",
            "--workdir", "/workspace" + ("" if self.manifest.working_directory == "." else "/" + self.manifest.working_directory),
            "--entrypoint", "/bin/sh",
        ]
        for key in sorted(environment):
            args.extend(["--env", key])
        return args

    def build(self) -> str:
        if not self.manifest.build:
            return ""
        env = dict(self.manifest.environment)
        script = "set -eu\n" + "\n".join(shlex.join(command) for command in self.manifest.build)
        command = self._command(name=self.name + "-build", environment=env) + [self.image, "-c", script]
        # Disk output is bounded by the container's file ulimit only for its own
        # files; drain build stdout/stderr through the bounded transport buffer.
        transport = JsonlTransport(command, environment={**self.client_env, **env})
        try:
            # Build output is diagnostic, not a protocol response. Redirect stdout
            # to stderr inside the container, so the bounded stderr reader owns it.
            command[-1] = "exec 1>&2\n" + script
            transport.start()
            try:
                status = transport.process.wait(timeout=self.limits.build_seconds)
            except subprocess.TimeoutExpired as exc:
                raise ExecutionError("Project build exceeded the time limit.") from exc
            if status:
                raise ExecutionError("Project build failed; review the private build log.")
        finally:
            self._remove(self.name + "-build")
            transport.close(force=True)
            self.build_log = transport.log
        return self.build_log

    def pull(self) -> None:
        """Fetch exactly the reviewed digest without printing registry output."""
        # No project files or manifest environment are involved in this command.
        # Docker's progress output is drained into the same bounded log reader.
        command = ["docker", "pull", "--quiet", self.image]
        transport = JsonlTransport(command, environment=self.client_env)
        try:
            transport.start()
            try:
                code = transport.process.wait(timeout=300)
            except subprocess.TimeoutExpired:
                raise ExecutionError("Container image download exceeded the time limit.") from None
            if code:
                raise ExecutionError("The approved container image could not be downloaded.")
        finally:
            transport.close(force=True)

    def start(self, run_environment: Mapping[str, str]) -> JsonlTransport:
        if set(run_environment) - _RUNTIME_ENV:
            raise ProjectError("Only scoped execution and model-proxy credentials may reach the project.")
        if any(not isinstance(value, str) or "\x00" in value for value in run_environment.values()):
            raise ProjectError("Invalid runtime environment.")
        if self.network is not None and not NETWORK_PATTERN.fullmatch(self.network):
            raise ProjectError("Only a per-run restricted egress network may be selected.")
        env = {**dict(self.manifest.environment), **run_environment}
        command = self._command(name=self.name, environment=env, network=self.network or "bridge")
        command += [self.image, "-c", "exec " + shlex.join(self.manifest.run)]
        secrets = tuple(value for key, value in run_environment.items() if key.endswith(("TOKEN", "KEY")))
        self.transport = JsonlTransport(command, environment={**self.client_env, **env}, redactions=secrets,
                                        log_limit=AGENT_LOG_BYTES)
        return self.transport

    def _remove(self, name: str) -> None:
        try:
            subprocess.run(["docker", "rm", "--force", name], env=self.client_env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def close(self) -> None:
        # Killing the Docker client alone does not guarantee container termination.
        self._remove(self.name)
        if self.transport:
            self.transport.close(force=True)

    def __enter__(self) -> "DockerWorkspace":
        return self

    def __exit__(self, *_args) -> None:
        self.close()
