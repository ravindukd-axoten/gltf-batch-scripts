"""Tiny Geometry Nodes builder for the frontage kit (P96), Blender 5.3.

Writes real node groups: `group(name, inputs, fn)` makes a node group whose interface sockets come from `inputs`
and whose body is `fn(tree, p)`; `p` holds the group-input sockets wrapped in `S`, so part code does arithmetic on
sockets (`p.Width / 2 + 0.1` makes Math nodes) or on plain numbers (folded in Python). `T.use(group, **values)`
places a group node in another tree. Nothing here makes vertices one by one: geometry comes from GN primitives,
transforms, booleans, instancing and curve sweeps.
"""
from __future__ import annotations

import bpy

TYPES = {float: "NodeSocketFloat", int: "NodeSocketInt", bool: "NodeSocketBool", "geo": "NodeSocketGeometry",
         "obj": "NodeSocketObject"}


class S:
    """A node output socket inside tree `t`, with arithmetic that builds Math nodes."""

    def __init__(self, t: "T", sock):
        self.t, self.s = t, sock

    def _m(self, op, other, rev=False):
        a, b = (other, self) if rev else (self, other)
        return self.t.math(op, a, b)

    def __add__(self, o): return self._m("ADD", o)
    def __radd__(self, o): return self._m("ADD", o, True)
    def __sub__(self, o): return self._m("SUBTRACT", o)
    def __rsub__(self, o): return self._m("SUBTRACT", o, True)
    def __mul__(self, o): return self._m("MULTIPLY", o)
    def __rmul__(self, o): return self._m("MULTIPLY", o, True)
    def __truediv__(self, o): return self._m("DIVIDE", o)
    def __rtruediv__(self, o): return self._m("DIVIDE", o, True)
    def __neg__(self): return self._m("MULTIPLY", -1.0)


class P:
    """Group inputs by name."""

    def __init__(self, d): self.__dict__.update(d)


class T:
    """Node tree builder."""

    def __init__(self, ng):
        self.ng, self.x = ng, 0

    def node(self, kind, **props):
        n = self.ng.nodes.new(kind)
        n.location = (self.x * 40 % 4000, -(self.x // 100) * 300)
        self.x += 1
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def set(self, sock, v):
        if isinstance(v, S):
            self.ng.links.new(v.s, sock)
        elif v is not None:
            sock.default_value = v

    def math(self, op, a, b):
        n = self.node("ShaderNodeMath", operation=op)
        self.set(n.inputs[0], a)
        self.set(n.inputs[1], b)
        return S(self, n.outputs[0])

    def vec(self, x, y, z):
        if not any(isinstance(c, S) for c in (x, y, z)):
            return (float(x), float(y), float(z))
        n = self.node("ShaderNodeCombineXYZ")
        for i, c in enumerate((x, y, z)):
            self.set(n.inputs[i], c)
        return S(self, n.outputs[0])

    # --- geometry -------------------------------------------------------------------------------------------
    def cube(self, x0, x1, y0, y1, z0, z1, verts=None):
        """Axis box from its min/max corners (numbers or sockets)."""
        n = self.node("GeometryNodeMeshCube")
        self.set(n.inputs["Size"], self.vec(x1 - x0, y1 - y0, z1 - z0))
        if verts:
            for i, a in enumerate("XYZ"):
                self.set(n.inputs[f"Vertices {a}"], verts[i])
        return self.move(S(self, n.outputs["Mesh"]), ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))

    def cyl(self, r, depth, at, axis="z", segs=12, r_scale=(1, 1, 1)):
        n = self.node("GeometryNodeMeshCylinder", fill_type="NGON")
        self.set(n.inputs["Vertices"], segs)
        self.set(n.inputs["Radius"], r)
        self.set(n.inputs["Depth"], depth)
        rot = {"z": (0, 0, 0), "y": (1.5707963, 0, 0), "x": (0, 1.5707963, 0)}[axis]
        return self.move(S(self, n.outputs["Mesh"]), at, rot, r_scale)

    def move(self, geo, t=(0, 0, 0), r=None, s=None):
        n = self.node("GeometryNodeTransform")
        self.set(n.inputs["Geometry"], geo)
        self.set(n.inputs["Translation"], self.vec(*t) if isinstance(t, tuple) else t)
        if r is not None:
            self.set(n.inputs["Rotation"], r)
        if s is not None:
            self.set(n.inputs["Scale"], s)
        return S(self, n.outputs["Geometry"])

    def join(self, *geos):
        n = self.node("GeometryNodeJoinGeometry")
        for g in reversed([g for g in geos if g is not None]):
            self.ng.links.new(g.s, n.inputs["Geometry"])
        return S(self, n.outputs["Geometry"])

    def boolean(self, a, cutters, op="DIFFERENCE"):
        n = self.node("GeometryNodeMeshBoolean", operation=op)
        try:
            n.solver = "MANIFOLD"
        except TypeError:
            n.solver = "EXACT"
        if op == "UNION":
            for g in [a] + list(cutters):
                self.ng.links.new(g.s, n.inputs["Mesh 2"])
        else:
            self.ng.links.new(a.s, n.inputs["Mesh 1"])
            for g in cutters:
                self.ng.links.new(g.s, n.inputs["Mesh 2"])
        return S(self, n.outputs["Mesh"])

    def switch(self, cond, false, true, kind="GEOMETRY"):
        n = self.node("GeometryNodeSwitch", input_type=kind)
        self.set(n.inputs["Switch"], cond)
        self.set(n.inputs["False"], false)
        self.set(n.inputs["True"], true)
        return S(self, n.outputs["Output"])

    def when(self, cond, geo):
        """geo if cond else nothing (cond: bool socket or Python bool)."""
        if isinstance(cond, bool):
            return geo if cond else None
        return self.switch(cond, None, geo)

    def cmp(self, a, b, op="EQUAL"):
        n = self.node("FunctionNodeCompare", data_type="INT", operation=op)
        ins = [i for i in n.inputs if i.enabled] if len(n.inputs) > 2 else list(n.inputs)
        ins = [i for i in ins if i.type == "INT"] or ins
        self.set(ins[0], a)
        self.set(ins[1], b)
        return S(self, n.outputs[0])

    def bnot(self, a):
        n = self.node("FunctionNodeBooleanMath", operation="NOT")
        self.set(n.inputs[0], a)
        return S(self, n.outputs[0])

    def band(self, a, b):
        n = self.node("FunctionNodeBooleanMath", operation="AND")
        self.set(n.inputs[0], a)
        self.set(n.inputs[1], b)
        return S(self, n.outputs[0])

    def tag(self, geo, trim, bevel=1.0):
        """Store the trim-sheet row id per face and the bevel weight per edge (read by kitbuild / Bevel)."""
        geo = self.store(geo, "trim", trim, "INT", "FACE")
        return self.store(geo, "bevel_weight_edge", float(bevel), "FLOAT", "EDGE")

    def store(self, geo, name, value, dtype, domain, sel=None):
        n = self.node("GeometryNodeStoreNamedAttribute", data_type=dtype, domain=domain)
        self.set(n.inputs["Geometry"], geo)
        self.set(n.inputs["Name"], name)
        self.set(n.inputs["Value"], value)
        if sel is not None:
            self.set(n.inputs["Selection"], sel)
        return S(self, n.outputs["Geometry"])

    def array(self, inst, count, step, start=(0, 0, 0)):
        """`count` copies of `inst` along `step` (Mesh Line points + Instance on Points + Realize)."""
        line = self.node("GeometryNodeMeshLine")
        self.set(line.inputs["Count"], count)
        self.set(line.inputs["Start Location"], self.vec(*start) if isinstance(start, tuple) else start)
        self.set(line.inputs["Offset"], self.vec(*step) if isinstance(step, tuple) else step)
        iop = self.node("GeometryNodeInstanceOnPoints")
        self.ng.links.new(line.outputs["Mesh"], iop.inputs["Points"])
        self.set(iop.inputs["Instance"], inst)
        rz = self.node("GeometryNodeRealizeInstances")
        self.ng.links.new(iop.outputs["Instances"], rz.inputs["Geometry"])
        return S(self, rz.outputs["Geometry"])

    def sweep(self, x0, x1, profile_obj, at_y=0.0, at_z=0.0, caps=True):
        """Profile curve object (in its local X=depth toward the street negative, Y=height) swept along +X."""
        line = self.node("GeometryNodeCurvePrimitiveLine")
        self.set(line.inputs["Start"], self.vec(x0, at_y, at_z))
        self.set(line.inputs["End"], self.vec(x1, at_y, at_z))
        oi = self.node("GeometryNodeObjectInfo", transform_space="ORIGINAL")
        oi.inputs["Object"].default_value = profile_obj
        c2m = self.node("GeometryNodeCurveToMesh")
        self.ng.links.new(line.outputs["Curve"], c2m.inputs["Curve"])
        self.ng.links.new(oi.outputs["Geometry"], c2m.inputs["Profile Curve"])
        c2m.inputs["Fill Caps"].default_value = caps
        return S(self, c2m.outputs["Mesh"])

    def use(self, group, **values):
        n = self.node("GeometryNodeGroup")
        n.node_tree = group
        for k, v in values.items():
            self.set(n.inputs[k], v)
        return S(self, n.outputs[0])


def group(name, inputs, fn):
    """Node group `name` with `inputs` [(name, type, default)], one Geometry output, body fn(T, P)."""
    ng = bpy.data.node_groups.get(name)
    if ng:
        bpy.data.node_groups.remove(ng)
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    for nm, kind, default in inputs:
        s = ng.interface.new_socket(nm, in_out="INPUT", socket_type=TYPES[kind])
        if default is not None:
            s.default_value = default
    t = T(ng)
    gi = t.node("NodeGroupInput")
    go = t.node("NodeGroupOutput")
    p = P({nm: S(t, gi.outputs[nm]) for nm, _, _ in inputs})
    out = fn(t, p)
    if out is not None:
        ng.links.new(out.s, go.inputs[0])
    return ng
