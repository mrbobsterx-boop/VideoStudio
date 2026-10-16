"""Рендер 3D-моделей проекта (.glb / .gltf / .obj / .stl / .ply) через PyVista — только в «Подготовке».

Кадр сцены модель не считает: `model(...)` в kit читает готовые PNG из <проект>/cache/models/.
Здесь — «вертушка»: модель поворачивается вокруг вертикали, камера, свет (ключ / заполнение / контур) и пол
неподвижны. Тень на полу снимается «ловцом теней»: пол рендерится белым с тенями и без модели, разница
становится полупрозрачной чёрной тенью — фон кадра остаётся прозрачным.
"""
import json
import os
import time

import numpy as np

LIGHTS = {
    # (позиция в долях радиуса: вправо, к камере, вверх), цвет, яркость
    'studio': [((-1.2, 1.6, 1.8), '#ffffff', 1.0), ((1.6, 1.0, 0.7), '#8fb3ef', 0.45), ((0.3, -1.8, 1.2), '#ffd28a', 0.85)],
    'soft': [((-1.0, 1.6, 1.6), '#ffffff', 0.8), ((1.4, 1.2, 0.9), '#dfe8ff', 0.6), ((0.0, -1.6, 1.4), '#ffffff', 0.5)],
    'warm': [((-1.2, 1.6, 1.8), '#ffe2b8', 1.0), ((1.6, 1.0, 0.7), '#ffb37a', 0.35), ((0.3, -1.8, 1.2), '#ffcf70', 0.9)],
    'cool': [((-1.2, 1.6, 1.8), '#e6f0ff', 1.0), ((1.6, 1.0, 0.7), '#6fa0ff', 0.5), ((0.3, -1.8, 1.2), '#9fe7ff', 0.9)],
    'dramatic': [((-1.6, 0.8, 1.4), '#ffffff', 1.25), ((1.6, 1.0, 0.4), '#5a78b0', 0.15), ((0.2, -1.8, 1.6), '#ffd28a', 1.1)],
}


def _pv():
    import pyvista as pv
    pv.OFF_SCREEN = True
    return pv


def _rot_x90():
    """Y-up (glTF, OBJ) -> Z-up (PyVista/STL)."""
    return np.array([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], float)


def load_meshes(path, up=None):
    """Модель → список (pyvista-сетка, dict(texture=, color=, rgb=)), уже в системе «Z вверх»."""
    import trimesh
    pv = _pv()
    ext = os.path.splitext(path)[1].lower()
    up = up or ('z' if ext in ('.stl', '.ply') else 'y')
    sc = trimesh.load(path, force='scene')
    out = []
    for g in sc.dump() if hasattr(sc, 'dump') else [sc]:
        if not hasattr(g, 'faces') or len(g.faces) == 0:
            continue
        g = g.copy()
        if up == 'y':
            g.apply_transform(_rot_x90())
        m = pv.wrap(g)
        info = {}
        vis = getattr(g, 'visual', None)
        try:
            if vis is not None and vis.kind == 'texture' and vis.uv is not None:
                mat = vis.material
                img = getattr(mat, 'baseColorTexture', None) or getattr(mat, 'image', None)
                if img is not None:
                    m.active_texture_coordinates = np.asarray(vis.uv, np.float32)
                    info['texture'] = pv.Texture(np.array(img.convert('RGB')))
                fac = getattr(mat, 'baseColorFactor', None)
                if fac is not None and img is None:
                    info['color'] = tuple(np.asarray(fac[:3], float) / (255.0 if max(fac[:3]) > 1 else 1.0))
                mr = getattr(mat, 'metallicFactor', None)
                if mr is not None:
                    info['metallic'] = float(mr)
                rough = getattr(mat, 'roughnessFactor', None)
                if rough is not None:
                    info['roughness'] = float(rough)
            elif vis is not None and vis.kind in ('vertex', 'face'):
                vc = vis.vertex_colors if vis.kind == 'vertex' else vis.to_color().vertex_colors
                m.point_data['rgb'] = np.asarray(vc)[:, :3].astype(np.uint8)
                info['rgb'] = True
            elif vis is not None:
                mc = getattr(getattr(vis, 'material', None), 'main_color', None)
                if mc is not None:
                    info['color'] = tuple(np.asarray(mc[:3], float) / 255.0)
        except Exception:
            pass
        out.append((m, info))
    if not out:
        raise ValueError('В модели нет треугольников: %s' % os.path.basename(path))
    return out


class Turntable:
    """Одна модель в одной сцене PyVista — рендерит много ракурсов, не пересоздавая окно."""

    def __init__(self, path, size=1024, elevation=15.0, zoom=1.0, light='studio', shadow=True, floor=True,
                 up=None, fov=30.0):
        pv = _pv()
        import vtk
        self.vtk = vtk
        self.size = int(size)
        self.shadow = bool(shadow and floor)
        self.pl = pl = pv.Plotter(off_screen=True, window_size=(self.size, self.size), lighting='none')
        self.actors = []
        meshes = load_meshes(path, up)
        bounds = np.array([m.bounds for m, _ in meshes], float).reshape(-1, 3, 2)
        lo, hi = bounds[:, :, 0].min(0), bounds[:, :, 1].max(0)
        self.c = c = (lo + hi) / 2
        r = float(np.linalg.norm(hi - lo) / 2) or 1.0
        self.r = r
        for m, info in meshes:
            kw = dict(smooth_shading=True, specular=0.25, specular_power=24)
            if 'texture' in info:
                kw['texture'] = info['texture']
            elif info.get('rgb'):
                kw.update(scalars='rgb', rgb=True)
            else:
                kw['color'] = info.get('color', (0.85, 0.85, 0.85))
            try:
                self.actors.append(pl.add_mesh(m, **kw))
            except Exception:
                kw.pop('texture', None)
                self.actors.append(pl.add_mesh(m, color=info.get('color', (0.85, 0.85, 0.85)), smooth_shading=True))
        self.floor = None
        if floor:
            plane = pv.Plane(center=(c[0], c[1], lo[2] - r * 0.002), direction=(0, 0, 1), i_size=r * 10, j_size=r * 10)
            self.floor = pl.add_mesh(plane, color='white', ambient=0.0, diffuse=1.0, specular=0.0)
        preset = light if isinstance(light, (list, tuple)) else LIGHTS.get(light, LIGHTS['studio'])
        # камера смотрит вдоль +Y на модель (спереди у glTF — со стороны -Y после поворота)
        for (sx, sy, sz), col, it in preset:
            pos = c + np.array([sx, -sy, sz]) * r * 4
            pl.add_light(pv.Light(position=tuple(pos), focal_point=tuple(c), color=col, intensity=it,
                                  positional=True, cone_angle=75))
        if self.shadow:
            pl.enable_shadows()
            try:
                passes = pl.renderer._shadow_pass
                passes.GetShadowMapBakerPass().SetResolution(2048)
            except Exception:
                pass
        el = np.radians(float(elevation))
        dist = r / np.tan(np.radians(fov / 2)) * 1.05 / max(0.1, float(zoom))
        pl.camera.focal_point = tuple(c)
        pl.camera.position = tuple(c + np.array([0, -np.cos(el), np.sin(el)]) * dist)
        pl.camera.up = (0, 0, 1)
        pl.camera.view_angle = fov
        pl.camera.clipping_range = (dist * 0.05, dist * 20)
        try:
            pl.enable_anti_aliasing('ssaa')
        except Exception:
            pass
        pl.show(auto_close=False)
        self.ref = None
        if self.shadow:
            self._models(False)
            self.ref = self._shot().astype(np.float32)
            self._models(True)

    def _models(self, vis):
        for a in self.actors:
            a.SetVisibility(bool(vis))

    def _shot(self):
        self.pl.render()
        return self.pl.screenshot(transparent_background=True, return_img=True)

    def view(self, azimuth):
        """RGBA uint8 size×size: модель, повёрнутая на azimuth градусов, с тенью на прозрачном фоне."""
        vtk = self.vtk
        c = self.c
        for a in self.actors:
            tr = vtk.vtkTransform()
            tr.PostMultiply()
            tr.Translate(-c[0], -c[1], -c[2])
            tr.RotateZ(float(azimuth))
            tr.Translate(*c)
            a.SetUserTransform(tr)
        if self.floor is not None:
            self.floor.SetVisibility(False)
        img = self._shot()
        if self.floor is None:
            return img
        rgb = img[..., :3].astype(np.float32)
        al = img[..., 3:4].astype(np.float32) / 255
        out = np.zeros_like(img)
        if self.shadow and self.ref is not None:
            self.floor.SetVisibility(True)
            fl = self._shot().astype(np.float32)
            self.floor.SetVisibility(False)
            lum_ref = self.ref[..., :3].mean(-1) + 1.0
            lum = fl[..., :3].mean(-1) + 1.0
            sh = np.clip(1.0 - lum / lum_ref, 0, 1) * (self.ref[..., 3] > 0)
            import cv2
            sh = cv2.GaussianBlur(sh, (0, 0), max(1.0, self.size / 400))
            sh = np.clip(sh * 1.15, 0, 0.85)[..., None]
        else:
            sh = np.zeros_like(al)
        a_out = al + sh * (1 - al)
        out[..., :3] = np.clip(rgb * al / np.maximum(a_out, 1e-4), 0, 255).astype(np.uint8)
        out[..., 3] = np.clip(a_out[..., 0] * 255, 0, 255).astype(np.uint8)
        return out

    def close(self):
        try:
            self.pl.close()
        except Exception:
            pass


def render_spec(spec, out_dir, angles, log=print, cancel=None):
    """Отрендерить нужные ракурсы спецификации (из kit.model) в out_dir/a###.png. Возвращает число новых."""
    import cv2
    os.makedirs(out_dir, exist_ok=True)
    todo = [a for a in angles if not os.path.isfile(os.path.join(out_dir, 'a%03d.png' % a))]
    if not todo:
        return 0
    t0 = time.time()
    tt = Turntable(spec['path'], size=spec['size'], elevation=spec['elevation'], zoom=spec['zoom'],
                   light=spec['light'], shadow=spec['shadow'], floor=spec['floor'], up=spec.get('up'))
    try:
        for i, a in enumerate(todo):
            if cancel and cancel():
                break
            img = tt.view(a)
            p = os.path.join(out_dir, 'a%03d.png' % a)
            tmp = p + '.tmp.png'
            cv2.imwrite(tmp, cv2.cvtColor(img, cv2.COLOR_RGBA2BGRA), [cv2.IMWRITE_PNG_COMPRESSION, 3])
            os.replace(tmp, p)
            if i % 12 == 0 or i == len(todo) - 1:
                log('  %s: ракурс %d/%d (%.1f с)' % (os.path.basename(spec['path']), i + 1, len(todo), time.time() - t0))
    finally:
        tt.close()
    with open(os.path.join(out_dir, 'spec.json'), 'w', encoding='utf-8') as f:
        json.dump(dict(spec, done=sorted(int(x[1:4]) for x in os.listdir(out_dir) if x.startswith('a') and x.endswith('.png'))),
                  f, ensure_ascii=False)
    return len(todo)
