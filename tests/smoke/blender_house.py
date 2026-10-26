import os, sys
from pathlib import Path
from onclick.config import Config
from onclick.context import Context
from onclick.tools import build_registry
ctx = Context(cfg=Config(api_key="x", blender_path=os.environ["BLENDER"]), workspace=Path("smoke-out"))
reg = build_registry(ctx)
script = '''
bpy.ops.object.select_all(action="SELECT"); bpy.ops.object.delete()
def mat(n,c):
    m=bpy.data.materials.new(n); m.use_nodes=True; m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value=(*c,1); return m
bpy.ops.mesh.primitive_plane_add(size=30); bpy.context.object.data.materials.append(mat("grass",(0.1,0.35,0.1)))
bpy.ops.mesh.primitive_cube_add(location=(0,0,1.5)); h=bpy.context.object; h.scale=(3,2,1.5); h.data.materials.append(mat("wall",(0.9,0.85,0.75)))
bpy.ops.mesh.primitive_cone_add(vertices=4,radius1=4.3,depth=2,location=(0,0,4)); r=bpy.context.object; r.rotation_euler[2]=math.radians(45); r.scale=(1,0.7,1); r.data.materials.append(mat("roof",(0.5,0.1,0.08)))
bpy.ops.mesh.primitive_cube_add(location=(0,-2.01,0.9)); d=bpy.context.object; d.scale=(0.5,0.05,0.9); d.data.materials.append(mat("door",(0.3,0.15,0.05)))
bpy.ops.object.light_add(type="SUN",rotation=(math.radians(50),0,math.radians(30))); bpy.context.object.data.energy=4
bpy.ops.object.camera_add(location=(10,-12,6),rotation=(math.radians(70),0,math.radians(40))); bpy.context.scene.camera=bpy.context.object
s=bpy.context.scene; s.render.engine="CYCLES"; s.cycles.samples=16; s.cycles.device="CPU"; s.render.resolution_x=800; s.render.resolution_y=500
s.world=bpy.data.worlds.new("w"); s.world.use_nodes=True; s.world.node_tree.nodes["Background"].inputs[0].default_value=(0.5,0.7,1,1)
'''
r = reg.get("blender_run_script").func(script=script, name="test_house", timeout=300)
print(r.text[:1500]); print("image:", bool(r.image_png))
sys.exit(0 if r.image_png and "Blender OK" in r.text else 1)
