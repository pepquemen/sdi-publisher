"""
Builds `sync_geonode_datasets` command lines to refresh GeoNode's derived
metadata (bbox, attributes, thumbnail) after a schema/geometry change.

sync_geonode_datasets filters by dataset name (--filter), so one line is
emitted per layer. The exact --filter semantics (full name vs plain name vs
substring) should be confirmed with `--help` on the server.
"""

import shlex


def build_sync_geonode_commands(layer_names, docker_container=None,
                                update_bbox=True, update_attributes=True,
                                update_thumbnails=False):
    lines = []
    for name in layer_names:
        # name comes as "workspace:layer"; sync_geonode_datasets expects the
        # dataset name (without the workspace prefix).
        dataset_name = name.split(":", 1)[-1]
        parts = ["python", "manage.py", "sync_geonode_datasets",
                 f"--filter={shlex.quote(dataset_name)}"]
        if update_bbox:
            parts.append("--updatebbox")
        if update_attributes:
            parts.append("--updateattributes")
        if update_thumbnails:
            parts.append("--updatethumbnails")
        base_cmd = " ".join(parts)
        if docker_container:
            base_cmd = f"docker exec -it {shlex.quote(docker_container)} {base_cmd}"
        lines.append(base_cmd)
    return lines
