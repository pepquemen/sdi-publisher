"""
Shared GeoServer layer inventory.

Both the GeoNode tab and the Sync tab need "every published GeoServer layer,
with whether it's registered in GeoNode". This is the single source of that
list so the two tabs don't each keep their own copy.

Each item: {workspace, datastore, layer, in_geoserver, in_geonode}
  - layer is the published featuretype name (== the GeoServer layer name),
    which is also what GeoNode uses as 'alternate' (workspace:layer) and what
    the GeoServer REST reset/recalculate endpoints address.
  - in_geonode is True/False, or None when no GeoNode connection was given.
"""


def full_inventory(gs_conn, geonode_conn=None):
    gn_alternates = geonode_conn.list_alternates() if geonode_conn else None
    items = []
    for ws in gs_conn.list_workspaces():
        for ds in gs_conn.list_datastores(ws):
            for layer in gs_conn.list_featuretypes(ws, ds):
                alt = f"{ws}:{layer}"
                items.append({
                    "workspace": ws,
                    "datastore": ds,
                    "layer": layer,
                    "in_geoserver": True,
                    "in_geonode": (alt in gn_alternates) if gn_alternates is not None else None,
                })
    return items
