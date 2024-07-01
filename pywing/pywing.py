#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from PyQt5 import QtCore, QtGui, QtOpenGL
import pyqtgraph as pg
import numpy as np
import pickle
import sys, math

from machine import *
from foamblock import *
from position import *
from cutparameters import *
from graphicview import *

from pathmanager import PathManager, PathManagerWidget
#from machine import SerialThread  # Assurez-vous que vous importez SerialThread correctement


class CutProcessor(QtCore.QObject):
    update = QtCore.pyqtSignal()

    def __init__(self, machine_model, path_manager_l, path_manager_r, abs_pos_model, rel_pos_model, foam_block_model, cut_param_model):
        super().__init__()
        self._machine_model = machine_model

        self.path_manager_l = self.rel_path_manager = path_manager_l
        self.path_manager_r = self.abs_path_manager = path_manager_r

        self.abs_on_right = True

        self.foam_block = foam_block_model
        self.cut_param = cut_param_model

        self.abs_pos = abs_pos_model
        self.rel_pos = rel_pos_model
        self.abs_pos.import_tuple((self.abs_pos.name,
                                   self.abs_pos.r,
                                   [100.0 + self.cut_param.lead, 0.0]))
        self._apply_transform()

        self._path_l = self._path_r = np.array([[],[],[]])
        self._machine_path_l = self._machine_path_r = np.array([[],[],[]])

        self.path_manager_l.gen_update.connect(self._generate_paths)
        self.path_manager_r.gen_update.connect(self._generate_paths)
        self.path_manager_l.sync_update.connect(self._connect_paths)
        self.path_manager_r.sync_update.connect(self._connect_paths)

        self.abs_pos.update.connect(self._apply_transform)
        self.rel_pos.update.connect(self._apply_transform)
        self.cut_param.update.connect(self._apply_transform)
        self.foam_block.update.connect(self._connect_paths)

    def _generate_paths(self):
        self.path_manager_l.generate()
        self.path_manager_r.generate()

        self._path_l = np.insert(self.path_manager_l.path.get_path(), 1, self.foam_block.offset + self.foam_block.width, axis=0)
        self._path_r = np.insert(self.path_manager_r.path.get_path(), 1, self.foam_block.offset, axis=0)

        if self.is_synced():
            # gen machine path
            #TODO to be cleaned
            width = self._machine_model.get_width()
            left = self._path_l
            right = self._path_r
            self._machine_path_l = np.vstack(((left[0]-right[0])/(left[1]-right[1])*(width-left[1])+left[0], (left[2]-right[2])/(left[1]-right[1])*(width-left[1])+left[2]))
            self._machine_path_l = np.insert(self._machine_path_l, 1, width, axis=0)
            self._machine_path_r = np.vstack(((right[0]-left[0])/(right[1]-left[1])*(0.0-right[1])+right[0], (right[2]-left[2])/(right[1]-left[1])*(0.0-right[1])+right[2]))
            self._machine_path_r = np.insert(self._machine_path_r, 1, 0.0, axis=0)

        self.update.emit()

    def _connect_paths(self):
        PathManager.synchronize(self.path_manager_l, self.path_manager_r)
        self._generate_paths()

    def generate_gcode(self):
        gcode = list()
        if(self.path_manager_l.loaded and self.path_manager_r.loaded):
            prev_pos = (self._machine_path_r[0][0],
                        self._machine_path_r[2][0],
                        self._machine_path_l[0][0],
                        self._machine_path_l[2][0])
            prev_pos_s = (self._path_r[0][0],
                          self._path_r[2][0],
                          self._path_l[0][0],
                          self._path_l[2][0])
            gcode.append("G01 F%.3f X%.3f Y%.3f Z%.3f A%.3f\n" % ((self.cut_param.feedrate,) + prev_pos))


            for i in range(1, len(self._path_r[0])):
                new_pos = (self._machine_path_r[0][i],
                           self._machine_path_r[2][i],
                           self._machine_path_l[0][i],
                           self._machine_path_l[2][i])
                new_pos_s = (self._path_r[0][i],
                             self._path_r[2][i],
                             self._path_l[0][i],
                             self._path_l[2][i])
                machine_diff = np.array(new_pos) - np.array(prev_pos)
                synced_diff = np.array(new_pos_s) - np.array(prev_pos_s)
                m_square = np.square(machine_diff)
                s_square = np.square(synced_diff)
                m_dist = max(math.sqrt(m_square[0]+m_square[1]), math.sqrt(m_square[2]+m_square[3]))
                s_dist = max(math.sqrt(s_square[0]+s_square[1]), math.sqrt(s_square[2]+s_square[3]))

                #TODO do a real gcode post proc
                if s_dist == 0.0:
                    continue

                prev_pos = new_pos
                prev_pos_s = new_pos_s
                gcode.append("G01 F%.3f X%.3f Y%.3f Z%.3f A%.3f\n" % ((m_dist / s_dist * self.cut_param.feedrate,) + new_pos))

        program = str()
        #TODO repair
        # program += ";Left  airfoil: " + self.path_manager_l.name
        # program += (" | S: %.2f R: %.2f TX: %.2f TY: %.2f K: %.2f\n" %
        #         (self.path_manager_l.s,
        #         self.path_manager_l.r,
        #         self.path_manager_l.t[0],
        #         self.path_manager_l.t[1],
        #         self.path_manager_l.k))
        # program += ";Right airfoil : " + self.path_manager_r.name
        # program += (" | S: %.2f R: %.2f TX: %.2f TY: %.2f K: %.2f\n" %
        #         (self.path_manager_r.s,
        #         self.path_manager_r.r,
        #         self.path_manager_r.t[0],
        #         self.path_manager_r.t[1],
        #         self.path_manager_r.k))

        for command in gcode:
            program += command

        return program

    def is_synced(self):
        return self.path_manager_l.loaded and self.path_manager_r.loaded

    def get_path_colors(self):
        return (self.path_manager_l.color, self.path_manager_r.color)

    def get_paths(self):
        return (self._path_l, self._path_r)

    def get_machine_paths(self):
        return (self._machine_path_l, self._machine_path_r)

    def get_synced_boundaries(self):
        bounds_r = self.path_manager_r.get_boundaries()
        bounds_l = self.path_manager_l.get_boundaries()
        return np.concatenate((np.minimum(bounds_r[:2], bounds_l[:2]), np.maximum(bounds_r[2:], bounds_l[2:])))

    def get_machine_boundaries(self):
        m_r = np.delete(self._machine_path_r, 1, 0)
        m_l = np.delete(self._machine_path_l, 1, 0)
        bounds_r = np.concatenate((np.amin(m_r, axis=1), np.amax(m_r, axis=1)))
        bounds_l = np.concatenate((np.amin(m_l, axis=1), np.amax(m_l, axis=1)))
        return np.concatenate((np.minimum(bounds_r[:2], bounds_l[:2]), np.maximum(bounds_r[2:], bounds_l[2:])))

    def _apply_transform(self):
        self.abs_path_manager.blockSignals(True)
        self.rel_path_manager.blockSignals(True)

        self.abs_path_manager.set_lead_size(self.cut_param.lead)
        self.rel_path_manager.set_lead_size(self.cut_param.lead)

        self.abs_path_manager.rotate(self.abs_pos.r)
        self.rel_path_manager.rotate(self.abs_pos.r + self.rel_pos.r)

        self.abs_path_manager.translate_x(self.abs_pos.t[0])
        self.abs_path_manager.translate_y(self.abs_pos.t[1])
        rrad = self.abs_pos.r / 180 * math.pi
        c = math.cos(rrad)
        s = math.sin(rrad)
        x = self.rel_pos.t[0] * c - self.rel_pos.t[1] * s
        y = self.rel_pos.t[0] * s + self.rel_pos.t[1] * c
        self.rel_path_manager.translate_x(self.abs_pos.t[0] + x)
        self.rel_path_manager.translate_y(self.abs_pos.t[1] + y)

        self.abs_path_manager.blockSignals(False)
        self.rel_path_manager.blockSignals(False)
        self.abs_path_manager.gen_update.emit()
        self.rel_path_manager.gen_update.emit()

    def is_abs_on_right(self):
        return self.abs_on_right

    def reverse(self):
        # exchange content of left and right paths
        tmp = self.path_manager_l.export_tuple()
        self.path_manager_l.import_tuple(self.path_manager_r.export_tuple())
        self.path_manager_r.import_tuple(tmp)

        # switch absolute side between left and right
        self.abs_on_right = not self.abs_on_right
        if self.abs_on_right:
            self.rel_path_manager = self.path_manager_l
            self.abs_path_manager = self.path_manager_r
        else:
            self.abs_path_manager = self.path_manager_l
            self.rel_path_manager = self.path_manager_r

        # apply relative and absolute position to paths
        self._apply_transform()

        # reverse block offset
        self.foam_block.reverse()

    def align(self):
        if(self.is_synced()):
            margin = 5
            bndr = self.get_machine_boundaries()
            self.abs_pos.import_tuple(
                (self.abs_pos.name,
                self.abs_pos.r,
                [self.abs_pos.t[0]-bndr[0] + margin,
                 self.abs_pos.t[1]-bndr[1] + margin]))
            self._apply_transform()

    def save(self, filename):
        fp = open(filename,'wb+')

        pickle.dump(self.abs_on_right, fp)
        pickle.dump(self.cut_param.export_tuple(), fp)
        pickle.dump(self.foam_block.export_tuple(), fp)
        pickle.dump(self.abs_pos.export_tuple(), fp)
        pickle.dump(self.rel_pos.export_tuple(), fp)
        pickle.dump(self.path_manager_l.export_tuple(), fp)
        pickle.dump(self.path_manager_r.export_tuple(), fp)

        fp.close()

    def load(self, filename):
        fp = open(filename, 'rb')

        self.abs_on_right = pickle.load(fp)
        self.cut_param.import_tuple(pickle.load(fp))
        self.foam_block.import_tuple(pickle.load(fp))
        self.abs_pos.import_tuple(pickle.load(fp))
        self.rel_pos.import_tuple(pickle.load(fp))
        self.path_manager_l.import_tuple(pickle.load(fp))
        self.path_manager_r.import_tuple(pickle.load(fp))

        fp.close()

        if self.abs_on_right:
            self.rel_path_manager = self.path_manager_l
            self.abs_path_manager = self.path_manager_r
        else:
            self.abs_path_manager = self.path_manager_l
            self.rel_path_manager = self.path_manager_r
        self._apply_transform()

class CuttingProcessorWidget(QtGui.QWidget):

    def __init__(self, cut_processor, machine,serial_thread):
        super().__init__()

        self._cut_proc = cut_processor
        self._machine = machine
        self.serial_thread = serial_thread
        #self.serial_thread = SerialThread(machine)
       # print("starting serial_thread")
      # self.serial_thread.start()


        self.serial_thread.connection_changed.connect(self.on_connection_change)
        self.serial_thread.position_changed.connect(self.update_position_display)  # Connecter le signal position_changed

        self.reverse_btn = QtGui.QPushButton("Reverse")
        self.reverse_btn.clicked.connect(self.on_reverse)
        self.align_btn = QtGui.QPushButton("Auto align")
        self.align_btn.clicked.connect(self.on_align)
        self.save_btn = QtGui.QPushButton("Save project")
        self.save_btn.clicked.connect(self.on_save)
        self.load_btn = QtGui.QPushButton("Load project")
        self.load_btn.clicked.connect(self.on_load)
        self.connect_btn = QtGui.QPushButton("Connect")
        self.connect_btn.clicked.connect(self.on_connect)
        self.play_btn = QtGui.QPushButton("play")
        self.play_btn.clicked.connect(self.on_play)
        self.stop_btn = QtGui.QPushButton("stop")
        self.stop_btn.clicked.connect(self.on_stop)
        self.reset_btn = QtGui.QPushButton("Reset")
        self.reset_btn.clicked.connect(self.on_reset)
 # Jog buttons
        self.jog_x_pos_btn = QtGui.QPushButton("X+")
        self.jog_x_pos_btn.clicked.connect(lambda: self.jog_axis('X', 1))
        self.jog_x_neg_btn = QtGui.QPushButton("X-")
        self.jog_x_neg_btn.clicked.connect(lambda: self.jog_axis('X', -1))
        self.jog_y_pos_btn = QtGui.QPushButton("Y+")
        self.jog_y_pos_btn.clicked.connect(lambda: self.jog_axis('Y', 1))
        self.jog_y_neg_btn = QtGui.QPushButton("Y-")
        self.jog_y_neg_btn.clicked.connect(lambda: self.jog_axis('Y', -1))
        self.jog_z_pos_btn = QtGui.QPushButton("Z+")
        self.jog_z_pos_btn.clicked.connect(lambda: self.jog_axis('Z', 1))
        self.jog_z_neg_btn = QtGui.QPushButton("Z-")
        self.jog_z_neg_btn.clicked.connect(lambda: self.jog_axis('Z', -1))
        self.jog_a_pos_btn = QtGui.QPushButton("A+")
        self.jog_a_pos_btn.clicked.connect(lambda: self.jog_axis('A', 1))
        self.jog_a_neg_btn = QtGui.QPushButton("A-")
        self.jog_a_neg_btn.clicked.connect(lambda: self.jog_axis('A', -1))
        self.zero_1_btn = QtGui.QPushButton("set zero1")
        self.zero_1_btn.clicked.connect(lambda: self.setzero(1))
        self.zero_2_btn = QtGui.QPushButton("set zero2")
        self.zero_2_btn.clicked.connect(lambda: self.setzero(2))
        self.gotoz_btn = QtGui.QPushButton("gotoz")
        self.gotoz_btn.clicked.connect(lambda: self.gotozero())

      
        # Step size and feedrate input
        self.step_size_label = QtGui.QLabel("Step Size:")
        self.step_size_input = QtGui.QDoubleSpinBox()
        self.step_size_input.setRange(0.01, 100.0)
        self.step_size_input.setValue(1.0)  # default step size

        self.feedrate_label = QtGui.QLabel("Feedrate:")
        self.feedrate_input = QtGui.QDoubleSpinBox()
        self.feedrate_input.setRange(1, 10000)
        self.feedrate_input.setValue(300.0)  # default feedrate  
        self.feedrate_input.setSingleStep(100)  # default stepfeedrate size      
    
        self.serial_text_item = QtGui.QTextEdit()
        self.serial_data = ""


        self.x_label = QtGui.QLabel("X: 0.000")
        self.y_label = QtGui.QLabel("Y: 0.000")
        self.z_label = QtGui.QLabel("Z: 0.000")
        self.a_label = QtGui.QLabel("A: 0.000")

# Set fixed size for jog buttons
        button_size = QtCore.QSize(50, 50)
        self.jog_x_pos_btn.setFixedSize(button_size)
        self.jog_x_neg_btn.setFixedSize(button_size)
        self.jog_y_pos_btn.setFixedSize(button_size)
        self.jog_y_neg_btn.setFixedSize(button_size)
        self.jog_z_pos_btn.setFixedSize(button_size)
        self.jog_z_neg_btn.setFixedSize(button_size)
        self.jog_a_pos_btn.setFixedSize(button_size)
        self.jog_a_neg_btn.setFixedSize(button_size)
        self.zero_1_btn.setFixedSize(button_size)
        self.zero_2_btn.setFixedSize(button_size)


 

        layout = QtGui.QGridLayout()
        layout.addWidget(self.reverse_btn, 0, 0)
        layout.addWidget(self.align_btn, 1, 0)
        layout.addWidget(self.save_btn, 2, 0)
        layout.addWidget(self.load_btn, 3, 0)
        layout.addWidget(self.serial_text_item, 0, 1, 4, 1)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 5)
        layout.addWidget(self.connect_btn, 1, 6)
        layout.addWidget(self.play_btn, 2, 6)
        layout.addWidget(self.stop_btn, 3, 6)
        layout.addWidget(self.reset_btn, 4, 6)
        layout.addWidget(self.gotoz_btn, 4, 7)

        # Jog button layout
        jog_layout = QtGui.QGridLayout()
        jog_layout.addWidget(self.jog_y_pos_btn, 0, 1)  # Y+
        jog_layout.addWidget(self.jog_x_neg_btn, 1, 0)  # X-
        jog_layout.addWidget(self.zero_1_btn, 1, 1)  # X-

        jog_layout.addWidget(self.jog_x_pos_btn, 1, 2)  # X+
        jog_layout.addWidget(self.jog_y_neg_btn, 2, 1)  # Y-

        jog_layout.addWidget(self.jog_a_pos_btn, 0, 4)  # A+
        jog_layout.addWidget(self.jog_z_neg_btn, 1, 3)  # Z-
        jog_layout.addWidget(self.zero_2_btn, 1, 4)  # X-

        jog_layout.addWidget(self.jog_z_pos_btn, 1, 5)  # Z+
        jog_layout.addWidget(self.jog_a_neg_btn, 2, 4)  # A-
        
        # Add step size and feedrate inputs to the layout
        layout.addWidget(self.step_size_label, 5, 0)
        layout.addWidget(self.step_size_input, 5, 1)
        layout.addWidget(self.feedrate_label, 6, 0)
        layout.addWidget(self.feedrate_input, 6, 1)
        layout.addLayout(jog_layout, 4, 0, 1, 2)

        position_layout = QtGui.QVBoxLayout()
        position_layout.addWidget(self.x_label)
        position_layout.addWidget(self.y_label)
        position_layout.addWidget(self.z_label)
        position_layout.addWidget(self.a_label)
        layout.addLayout(position_layout, 0, 7, 4, 1)

        self.setLayout(layout)
    def update_position_display(self, mpos):
        self.x_label.setText(f"X: {mpos[0]:.3f}")
        self.y_label.setText(f"Y: {mpos[1]:.3f}")
        self.z_label.setText(f"Z: {mpos[2]:.3f}")
        self.a_label.setText(f"A: {mpos[3]:.3f}")

    def jog_axis(self, axis, direction):
        step_size = self.step_size_input.value()
        feedrate = self.feedrate_input.value()
        command = f"$J=G91 {axis}{direction * step_size} F{feedrate}"  # Example jog command for GRBL
        #self.serial_thread.send_command(command)
        self.serial_thread.play(command)

    def on_reset(self):
        self.reset_components()
    def reset_components(self):
        # Reset machine model
        self.serial_thread = SerialThread(machine)



    def gotozero(self):
        command = "G0 X0 Y0 Z0 A0"  # Example jog command for GRBL
        #self.serial_thread.send_command(command)
        self.serial_thread.play(command)


    def setzero(self, axis):
        if axis == 1:
            command = "G92 X0 Y0"  # Example jog command for GRBL
            #self.serial_thread.send_command(command)
            self.serial_thread.play(command)
        else:
            command = "G92 Z0 A0"  # Example jog command for GRBL
            #self.serial_thread.send_command(command)
            self.serial_thread.play(command)


    def on_connection_change(self):
        if(self.serial_thread.connecting):
            text = "Connecting..."
            self.connect_btn.setFlat(True)
        elif(self.serial_thread.connected):
            text = "Disconnect"
            self.connect_btn.setFlat(False)
        else:
            text = "Connect"
            self.connect_btn.setFlat(False)

        self.connect_btn.setText(text)

   
    def on_stop(self):
        self.serial_thread.stop()
        self.serial_thread.start()

    def on_connect(self):
        if(self.serial_thread.connected):
            self.serial_thread.disconnect()
        else:
            self.serial_thread.connect()

    def on_save(self):
        filename, _ = QtGui.QFileDialog.getSaveFileName(self.save_btn.parent(), "Save project", QtCore.QDir.homePath() +"/example.pw", ".pw Files (*.pw) ;; All Files (*)")
        if filename:
            self._cut_proc.save(filename)

    def on_load(self):
        filename, _ = QtGui.QFileDialog.getOpenFileName(self.load_btn.parent(), "Open project", QtCore.QDir.homePath(), ".pw Files (*.pw) ;; All Files (*)")
        if filename:
            self._cut_proc.load(filename)

    def on_play(self):
        program = self._cut_proc.generate_gcode()
        self.serial_text_item.setText(program)
        self.serial_thread.play(program)

    def on_reverse(self):
        self._cut_proc.reverse()

    def on_align(self):
        self._cut_proc.align()
def on_finished():
    print("Task Finished")
if __name__ == '__main__':
    pg.setConfigOption('background', 'w')
    pg.setConfigOption('foreground', 'k')
    pg.setConfigOption('antialias', True)
    application = QtGui.QApplication([])

    abs_color = (233, 79, 55)
    rel_color = (46, 134, 171)

    machine = MachineModel()
    serial_thread = SerialThread(machine)  # Créez votre thread Telnet au lieu de Serial
    serial_thread.start()
    serial_thread.finishedSignal.connect(on_finished)
    path_manager_l = PathManager(rel_color)
    path_manager_r = PathManager(abs_color)
    path_widget_l = PathManagerWidget(path_manager_l)
    path_widget_r = PathManagerWidget(path_manager_r)

    abs_pos_model = PositionModel('Absolute')
    abs_pos_widget = PositionWidget(abs_pos_model)
    rel_pos_model = PositionModel('Relative')
    rel_pos_widget = PositionWidget(rel_pos_model)
    foam_block_model = FoamBlockModel(machine)
    foam_block_widget = FoamBlockWidget(foam_block_model)
    cut_param_model = CutParametersModel()
    cut_param_widget = CutParametersWidget(cut_param_model)

    cut_proc = CutProcessor(machine, path_manager_l, path_manager_r, abs_pos_model, rel_pos_model, foam_block_model, cut_param_model)

    gview = GraphicView(cut_proc, machine,serial_thread)
    graphic_view_widget = gview.canvas.native

    cutting_proc_widget = CuttingProcessorWidget(cut_proc, machine,serial_thread)

    top_widget = QtGui.QWidget()
    grid_layout = QtGui.QGridLayout()
    grid_layout.addWidget(path_widget_l,0,0)
    grid_layout.addWidget(rel_pos_widget,1,0)
    grid_layout.addWidget(cut_param_widget,2,0)
    grid_layout.addWidget(graphic_view_widget,0,1,3,2)
    grid_layout.setColumnStretch(1, 1)
    grid_layout.addWidget(path_widget_r,0,3)
    grid_layout.addWidget(abs_pos_widget,1,3)
    grid_layout.addWidget(foam_block_widget,2,3)
    top_widget.setLayout(grid_layout)

    main_widget = QtGui.QWidget()
    layout = QtGui.QVBoxLayout()
    layout.addWidget(top_widget)
    layout.addWidget(cutting_proc_widget)
    main_widget.setLayout(layout)
    main_widget.show()

    sys.exit(application.exec_())
