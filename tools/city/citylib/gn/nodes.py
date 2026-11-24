"""A small builder for Geometry Nodes trees written from Python (Blender 5.3).

Generators stay real node groups (they open and edit in Blender like hand-made ones); this module only saves
typing: `Tree.n()` adds a node and links or sets its inputs, the math helpers accept sockets or numbers, and
`set_inputs()` writes modifier inputs the 5.3 way (`mod.properties.inputs.<Socket_N>.value`, research 3.2,
`prototype/blender-gn-export-test`).
"""
from __future__ import annotations

import bpy

Sock = bpy.types.NodeSocket


def sock(sockets, name, kind=None):
    for s in sockets:
        if s.name == name and getattr(s, "enabled", True) and not getattr(s, "is_unavailable", False) \
                and (kind is None or s.type == kind):
            return s
    for s in sockets:  # unavailable sockets still accept defaults in some node types
        if s.name == name and (kind is None or s.type == kind):
            return s
    raise KeyError(f"socket {name} ({kind}) not in {[(s.name, s.type) for s in sockets]}")


class Tree:
    """One geometry node group under construction."""

    def __init__(self, name: str, modifier: bool = True):
        old = bpy.data.node_groups.get(name)
        if old is not None:
            bpy.data.node_groups.remove(old)
        self.ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
        self.ng.is_modifier = modifier
        self.nodes, self.links = self.ng.nodes, self.ng.links
        self.gin = self.nodes.new("NodeGroupInput")
        self.gout = self.nodes.new("NodeGroupOutput")

    # --- interface ---------------------------------------------------------------------------------
    def input(self, name, stype, default=None, **kw):
        s = self.ng.interface.new_socket(name=name, in_out="INPUT", socket_type=stype)
        if default is not None:
            s.default_value = default
        for k, v in kw.items():
            setattr(s, k, v)
        return s

    def output(self, name, stype):
        return self.ng.interface.new_socket(name=name, in_out="OUTPUT", socket_type=stype)

    def gi(self, name) -> Sock:
        return sock(self.gin.outputs, name)

    def result(self, value: Sock, name="Geometry") -> None:
        self.links.new(value, sock(self.gout.inputs, name))

    # --- nodes -------------------------------------------------------------------------------------
    def n(self, bl, inputs=None, **props):
        node = self.nodes.new(bl)
        for k, v in props.items():
            setattr(node, k, v)
        for k, v in (inputs or {}).items():
            kind = None
            if isinstance(k, tuple):
                k, kind = k
            s = sock(node.inputs, k, kind) if isinstance(k, str) else node.inputs[k]
            self.set(s, v)
        return node

    def set(self, s: Sock, v) -> None:
        if v is None:
            return
        if isinstance(v, bpy.types.NodeSocket):
            self.links.new(v, s)
        else:
            s.default_value = v

    @staticmethod
    def o(node, name=None, kind=None) -> Sock:
        return sock(node.outputs, name, kind) if name else node.outputs[0]

    def group(self, ng, inputs=None):
        node = self.nodes.new("GeometryNodeGroup")
        node.node_tree = ng
        for k, v in (inputs or {}).items():
            self.set(sock(node.inputs, k), v)
        return node

    # --- maths -------------------------------------------------------------------------------------
    def math(self, op, a, b=None, c=None) -> Sock:
        ins = {0: a}
        if b is not None:
            ins[1] = b
        if c is not None:
            ins[2] = c
        return self.o(self.n("ShaderNodeMath", ins, operation=op))

    def add(self, a, b):
        return self.math("ADD", a, b)

    def sub(self, a, b):
        return self.math("SUBTRACT", a, b)

    def mul(self, a, b):
        return self.math("MULTIPLY", a, b)

    def div(self, a, b):
        return self.math("DIVIDE", a, b)

    def madd(self, a, b, c):
        return self.math("MULTIPLY_ADD", a, b, c)

    def vec(self, x=0.0, y=0.0, z=0.0) -> Sock:
        return self.o(self.n("ShaderNodeCombineXYZ", {0: x, 1: y, 2: z}))

    def xyz(self, v):
        node = self.n("ShaderNodeSeparateXYZ", {0: v})
        return node.outputs[0], node.outputs[1], node.outputs[2]

    def vmath(self, op, a, b=None, scale=None) -> Sock:
        ins = {0: a}
        if b is not None:
            ins[1] = b
        if scale is not None:
            ins[("Scale", "VALUE")] = scale
        node = self.n("ShaderNodeVectorMath", ins, operation=op)
        return node.outputs["Value"] if op in ("DOT_PRODUCT", "LENGTH", "DISTANCE") else node.outputs["Vector"]

    def cmp(self, a, b, op="GREATER_THAN", kind="FLOAT", eps=None) -> Sock:
        ins = {0: a, 1: b}
        node = self.n("FunctionNodeCompare", ins, data_type=kind, operation=op)
        if eps is not None:
            sock(node.inputs, "Epsilon").default_value = eps
        return self.o(node)

    def bool(self, op, a, b=None) -> Sock:
        ins = {0: a}
        if b is not None:
            ins[1] = b
        return self.o(self.n("FunctionNodeBooleanMath", ins, operation=op))

    def switch(self, cond, false, true, kind="FLOAT") -> Sock:
        return self.o(self.n("GeometryNodeSwitch", {"Switch": cond, "False": false, "True": true}, input_type=kind))

    # --- geometry ----------------------------------------------------------------------------------
    def join(self, *geos) -> Sock:
        node = self.n("GeometryNodeJoinGeometry")
        for g in reversed([g for g in geos if g is not None]):
            self.links.new(g, node.inputs[0])
        return self.o(node)

    def named(self, name, kind="FLOAT") -> Sock:
        return self.o(self.n("GeometryNodeInputNamedAttribute", {"Name": name}, data_type=kind), "Attribute")

    def store(self, geo, name, value, kind="FLOAT", domain="POINT", selection=None) -> Sock:
        ins = {"Geometry": geo, "Name": name, "Value": value}
        if selection is not None:
            ins["Selection"] = selection
        return self.o(self.n("GeometryNodeStoreNamedAttribute", ins, data_type=kind, domain=domain))

    def position(self) -> Sock:
        return self.o(self.n("GeometryNodeInputPosition"))

    def normal(self) -> Sock:
        return self.o(self.n("GeometryNodeInputNormal"))

    def index(self) -> Sock:
        return self.o(self.n("GeometryNodeInputIndex"))

    def transform(self, geo, translation=None, rotation=None, scale=None) -> Sock:
        ins = {"Geometry": geo}
        if translation is not None:
            ins["Translation"] = translation
        if rotation is not None:
            ins["Rotation"] = rotation
        if scale is not None:
            ins["Scale"] = scale
        return self.o(self.n("GeometryNodeTransform", ins))

    def on_domain(self, value, domain="FACE", kind="FLOAT") -> Sock:
        return self.o(self.n("GeometryNodeFieldOnDomain", {0: value}, data_type=kind, domain=domain))


def set_inputs(mod, values: dict) -> None:
    """Blender 5.3: modifier inputs are RNA (mod.properties.inputs.<Socket_N>.value); mod["Socket_N"] raises."""
    found = set()
    for item in mod.node_group.interface.items_tree:
        if item.item_type == "SOCKET" and item.in_out == "INPUT" and item.name in values:
            getattr(mod.properties.inputs, item.identifier).value = values[item.name]
            found.add(item.name)
    missing = set(values) - found
    if missing:
        raise KeyError(f"{mod.node_group.name}: no inputs {sorted(missing)}")
