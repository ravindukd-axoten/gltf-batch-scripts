"""Batch Island city pipeline library (OSM -> layout -> per-cell glTF).

Pure-Python modules (geo, grid, rules, osm, kit) import nothing outside the standard library, so their
tests run with any system python3. layout and meshgen need Shapely; blender_scene needs bpy.
"""
