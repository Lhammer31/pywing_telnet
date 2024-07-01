from PyQt5 import QtCore
import numpy as np
from vispy import scene, gloo
from cuttingpathvisual import CuttingPathVisual
import triangle
from machine import SerialThread  # Assurez-vous que SerialThread est correctement importé
gloo.gl.use_gl('glplus')

def triangulate(path):
    if np.size(path, 1) > 2:
        dup_idx = np.argwhere(np.all(np.isclose(path[:,1:], path[:,:-1], atol=1e-3), axis=0)).flatten()
        if np.allclose(path[:,0], path[:,-1], atol=1e-3):
            dup_idx = np.append(dup_idx, 0)
        path = np.delete(path, dup_idx, axis=1).transpose()

        n = np.size(path, 0)
        segments = np.column_stack((np.arange(n), np.arange(1, n+1)))
        segments[-1][1] = 0

        result = triangle.triangulate({'vertices': path, 'segments': segments}, "p")
        return result['vertices'], result['triangles']

class GraphicView(QtCore.QObject):
    def __init__(self, cut_processor, machine, serial_thread):
        super().__init__()
        self.serial_thread = serial_thread

        self._cut_proc = cut_processor
        self._machine = machine
        
        self.serial_thread.position_changed.connect(self.update_position_display)

        # Initialisation de la scène Vispy
        self.canvas = scene.SceneCanvas(keys='interactive', size=(800, 600), show=True)
        self.camera = scene.cameras.TurntableCamera(fov=45.0, elevation=30.0, azimuth=30.0, roll=0.0, distance=None)
        self.view = self.canvas.central_widget.add_view(self.camera)

        # Configuration de la caméra
        self.camera.fov = 0.0

        # Initialisation des différents éléments visuels dans la scène
        self.plot_l = scene.LinePlot(width=2.0, color=(0.91, 0.31, 0.22, 1.0), parent=self.view.scene)
        self.plot_r = scene.LinePlot(width=2.0, color=(0.18, 0.53, 0.67, 1.0), parent=self.view.scene)
        self.mplot_l = scene.LinePlot(width=2.0, color=(1.0, 0.0, 0.0, 1.0), parent=self.view.scene)
        self.mplot_r = scene.LinePlot(width=2.0, color=(1.0, 0.0, 0.0, 1.0), parent=self.view.scene)
        self.face_l = scene.visuals.Mesh(color=(0.82, 0.28, 0.20, 1.0), mode='triangles', parent=self.view.scene)
        self.face_r = scene.visuals.Mesh(color=(0.16, 0.48, 0.60, 1.0), mode='triangles', parent=self.view.scene)

        CuttingPathNode = scene.visuals.create_visual_node(CuttingPathVisual)
        self.cutting_path = CuttingPathNode(color=(0.5, 0.5, 0.5, 1), parent=self.view.scene)

        # Ajout de la grille de la machine
        length, width, height = self._machine.get_dimensions()
        m_grid = machine_grid(length, width, height, 50)
        self.mgrid_visual = scene.visuals.Line(pos=m_grid, color=(0.8,0.8,0.8,0.5), connect='segments', antialias=True, parent=self.view.scene)

        # Initialisation des marqueurs pour les bras avec les couleurs spécifiées
        self.left_arm_point = scene.visuals.Markers(parent=self.view.scene, symbol='disc', size=30, face_color=(1, 0, 0, 1))  # Rouge
        self.right_arm_point = scene.visuals.Markers(parent=self.view.scene, symbol='disc', size=30, face_color=(0, 0, 1, 1))  # Bleu

        # Initialisation de la ligne de connexion entre les bras (en rouge)
        self.connection_line = scene.visuals.Line(parent=self.view.scene, color=(1, 0, 0, 1), width=2.0)

        # Parentage des marqueurs et de la ligne à la scène
        self.left_arm_point.parent = self.view.scene
        self.right_arm_point.parent = self.view.scene
        self.connection_line.parent = self.view.scene

        # Connexion des événements de la souris
        self.canvas.events.mouse_press.connect(self.on_mouse_press)
        self.canvas.events.mouse_wheel.connect(self.on_mouse_wheel)

        # Connexion de l'événement de mise à jour du processeur de coupe
        self._cut_proc.update.connect(self.draw)

    def update_position_display(self, mpos):
        # Mettre à jour les marqueurs pour les bras
        length, width, height = self._machine.get_dimensions()
        self.left_arm_point.set_data(pos=np.array([[mpos[0], 0, mpos[1]]]), face_color=(1, 0, 0, 1))  # Rouge
        self.right_arm_point.set_data(pos=np.array([[mpos[2], width, mpos[3]]]), face_color=(0, 0, 1, 1))  # Bleu

        # Mettre à jour la ligne de connexion entre les bras
        line_positions = np.array([[mpos[0], 0, mpos[1]], [mpos[2], width, mpos[3]]])
        self.connection_line.set_data(pos=line_positions)

        # Forcer la mise à jour de la vue
        self.canvas.update()

    def on_mouse_press(self, event):
        if event.button == 3:  # Bouton de la molette (index 2 pour la molette)
            dx, dy = event.delta[:2]  # Récupérer le déplacement x et y

            # Norme du vecteur de vue pour la gestion de la position de la caméra
            view_direction = self.camera.transform.forward[:3]
            view_up = self.camera.transform.up[:3]

            # Ajuster la cible de la caméra pour simuler un pan
            self.camera.center += view_up * dy * 0.1 + np.cross(view_up, view_direction) * dx * 0.1

            self.canvas.update()  # Mettre à jour la vue

    def on_mouse_wheel(self, event):
        delta = event.delta[1] * 0.1  # Facteur de zoom
        self.camera.scale_factor /= (1.0 + delta)  # Ajuster le facteur de zoom de la caméra
        self.canvas.update()  # Mettre à jour la vue

    def draw(self):
        # Dessiner les trajectoires de coupe gauche et droite
        path_l, path_r = self._cut_proc.get_paths()
        self.plot_l.set_data(path_l.transpose(), symbol=None)
        self.plot_r.set_data(path_r.transpose(), symbol=None)

        assert(not np.any(np.isnan(path_l)))
        assert(not np.any(np.isnan(path_r)))

        if path_l.size > 0:
            # Trianguler et dessiner la surface gauche
            v, f = triangulate(path_l[::2,1:-1])  # Supprimer les trajectoires de tête et l'axe Y pour la triangulation
            v = np.insert(v, 1, path_l[1][0], axis=1)  # Réinsérer l'axe Y
            self.face_l.set_data(vertices=v, faces=f)

        if path_r.size > 0:
            # Trianguler et dessiner la surface droite
            v, f = triangulate(path_r[::2,1:-1])  # Supprimer les trajectoires de tête et l'axe Y pour la triangulation
            v = np.insert(v, 1, path_r[1][0], axis=1)  # Réinsérer l'axe Y
            self.face_r.set_data(vertices=v, faces=f)

        if path_l.size > 0 and path_r.size > 0:
            # Dessiner le chemin de la machine entre les trajectoires gauche et droite
            mpath_l, mpath_r = self._cut_proc.get_machine_paths()
            self.mplot_l.set_data(mpath_l.transpose(), symbol=None)
            self.mplot_r.set_data(mpath_r.transpose(), symbol=None)

            vertices = np.hstack((path_l, path_r)).transpose()

            f = np.repeat(np.arange(0, np.size(path_l, 1)), 2)[1:-1]
            fc = f.copy() + np.size(path_l, 1)
            faces = np.empty(f.size * 2, dtype=np.int32)
            faces[0::2] = f
            faces[1::2] = fc
            faces = np.reshape(faces, (int(faces.size/4), 4))

            self.cutting_path.set_data(vertices=vertices, faces=faces)

# Fonction pour générer les lignes pour la grille de la machine
def lines(n, normal):
    alternate = np.empty((2*n,))
    alternate[::2] = 0
    alternate[1::2] = 1
    if normal == 'x':
        return np.vstack((np.zeros(2*n), np.repeat(np.arange(0, n, 1), 2), alternate))
    if normal == 'y':
        return np.vstack((np.repeat(np.arange(0, n, 1), 2), np.zeros(2*n), alternate))
    if normal == 'z':
        return np.vstack((np.repeat(np.arange(0, n, 1), 2), alternate, np.zeros(2*n)))

# Fonction pour générer la grille de la machine
def machine_grid(x, y, z, step):
    x_steps = int(x/step)+1
    y_steps = int(y/step)+1
    z_steps = int(z/step)+1

    xlines = lines(x_steps, 'z')
    ylines = lines(y_steps, 'z')
    ylines = np.take(ylines, [1,0,2], axis=0)
    gridxy = np.column_stack((xlines * np.array([[step], [y], [0]]),
                              ylines * np.array([[x], [step], [0]])))

    xlines = lines(x_steps, 'y')
    zlines = lines(z_steps, 'y')
    zlines = np.take(zlines, [2,1,0], axis=0)
    gridxz = np.column_stack((xlines * np.array([[step], [0], [z]]),
                              zlines * np.array([[x], [0], [step]])))

    return np.column_stack((gridxy, gridxz, gridxz + np.array([[0],[y],[0]]))).transpose()
