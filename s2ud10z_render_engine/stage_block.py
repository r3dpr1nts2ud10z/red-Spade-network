import os
import bpy

out_dir = os.environ.get("S2UD10Z_OUT_DIR", "/tmp/s2ud10z_blender")
fps = int(os.environ.get("S2UD10Z_FPS", "30"))
w = int(os.environ.get("S2UD10Z_W", "1920"))
h = int(os.environ.get("S2UD10Z_H", "1080"))

os.makedirs(out_dir, exist_ok=True)

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE_NEXT" if hasattr(bpy.types, "BLENDER_EEVEE_NEXT") else "BLENDER_EEVEE"
scene.render.fps = fps
scene.render.resolution_x = w
scene.render.resolution_y = h
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"

if scene.frame_end < scene.frame_start:
    scene.frame_start = 1
    scene.frame_end = 30

scene.render.filepath = os.path.join(out_dir, "block_")
bpy.ops.render.render(animation=True)
