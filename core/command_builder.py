"""
Builds the `updatelayers` command lines the user runs on the GeoNode server.

updatelayers takes a single --workspace per call, so one line is emitted per
selected workspace. When a Docker container name is given, each line is
wrapped in `docker exec`.
"""

import shlex


def build_updatelayers_commands(workspaces, docker_container=None,
                                skip_registered=True, ignore_errors=True):
    lines = []
    for ws in workspaces:
        parts = ["python", "manage.py", "updatelayers", f"--workspace={shlex.quote(ws)}"]
        if skip_registered:
            parts.append("--skip-geonode-registered")
        if ignore_errors:
            parts.append("--ignore-errors")
        base_cmd = " ".join(parts)
        if docker_container:
            base_cmd = f"docker exec -it {shlex.quote(docker_container)} {base_cmd}"
        lines.append(base_cmd)
    return lines
