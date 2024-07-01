from PyQt5 import QtCore
import time
import queue
import serial.tools.list_ports
import telnetlib

class MachineModel(QtCore.QObject):
    state_changed = QtCore.pyqtSignal()
    properties_changed = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self._wire_position = (0.0, 0.0, 0.0, 0.0)
        self._dimensions = (1000.0, 647.0, 400.0)

    def set_wire_position(self, position):
        self._wire_position = position
        self.state_changed.emit()

    def get_wire_position(self):
        return self._wire_position

    def set_no_wire_position(self):
        self._wire_position = None
        self.state_changed.emit()

    def set_dimensions(self, length, width, height):
        self._dimensions = (length, width, height)
        self.properties_changed.emit()

    def get_dimensions(self):
        return self._dimensions

    def get_width(self):
        return self._dimensions[1]

class SerialThread(QtCore.QThread):
    connection_changed = QtCore.pyqtSignal()
    position_changed = QtCore.pyqtSignal(tuple)  # Ajouter le signal position_changed
    finishedSignal = QtCore.pyqtSignal()

    def __init__(self, machine):
        super().__init__()
        self._machine = machine
        self.host = "192.168.0.1"  # Adresse IP de votre machine CNC
        self.connected = False
        self.connecting = False  # Ajout de l'attribut connecting
        self.running = False
        self.stop_request = False
        self.connect_request = False
        self.disconnect_request = False
        self.gcode = []
        self.last_status_request = time.time()
        self.on_board_buf = 128
        self.test=0;
        self.past_cmd_len = queue.Queue()

    def __del__(self):
        self.wait()

    def connect(self):
        if not self.connected and not self.connecting:
            self.connecting = True
            try:
                self.telnet = telnetlib.Telnet(self.host, port=23, timeout=2)
                self.connected = True
                self.connecting = False
                self.connection_changed.emit()
                print("Connected to Telnet")
            except Exception as e:
                self.connecting = False
                print(f"Error connecting to Telnet: {e}")

    def disconnect(self):
        if self.connected:
            try:
                self.telnet.close()
                self.connected = False
                self.connection_changed.emit()
            except Exception as e:
                print(f"Error disconnecting from Telnet: {e}")

    def play(self, gcode):
     #   print(f"Received G-code: {gcode}")
        if self.connected:
            if not self.running:
                self.gcode = gcode.splitlines(True)
                self.running = True
                print("Starting G-code execution")

    def stop(self):
        if self.connected:
            if self.running:
                self.stop_request = True
    def send_command(self, command):
        if self.connected:
            try:
                self.telnet.write(f"{command}\n".encode('utf-8'))
                print(f"Sent command: {command}")
            except Exception as e:
                print(f"Error sending command: {e}")
            self.running = False

    def run(self):
        while True:
            #print("loop")
            if self.connected:
                #print("main loop connected triggered")
                try:
                    if self.stop_request:
                        print("Sending stop command")
                        self.telnet.write("!".encode("ascii"))
                        self.running = False
                        self.stop_request = False
                except Exception as e:
                    print(f"Error writing stop command to Telnet: {e}")
                    self._reset()
                    continue

                try:
                    if self.running:
                     #   print("self running triggered")
                        if self.gcode:
                            #print(F"self.gcode triggered :{self.gcode} and len of (self.gcode[0])  is {len(self.gcode[0]) }")
                            if len(self.gcode[0]) <= self.on_board_buf:
								
                                cmd = self.gcode.pop(0)
                                self.test=0;
                                #print(f"Sending G-code command: {cmd}")
                                self.telnet.write(f"{cmd}\n".encode('utf-8'))#(cmd.encode("ascii"))
                                self.on_board_buf -= len(cmd)
                                self.past_cmd_len.put(len(cmd))
                                #print(f"longueurcmd: {len(cmd)}")
                        else:
                            self.running = False
                            #self.on_board_buf=128
                            print("on a plus rien en gcode!!")
                            self.test=1;
                            
                except Exception as e:
                    print(f"Error writing G-code to Telnet: {e}")
                    self._reset()
                    continue

                try:
                    now = time.time()
                    if self.last_status_request + 0.2 < now:
                        #print("Requesting status")
                        self.telnet.write("?".encode("ascii"))
                        self.last_status_request = now
                except Exception as e:
                    print(f"Error writing status request to Telnet: {e}")
                    self._reset()
                    continue

                try:
                    read_data = self.telnet.read_until(b"\r\n", timeout=0.2).decode('utf-8')#self.telnet.read_until(b"\n").decode("ascii")
                    #read_data = self.telnet.read_all().decode('utf-8')
                  #  print(f"Received data from Telnet: {read_data}")
                    self._process_read_data(read_data)
                except Exception as e:
                    print(f"Error reading from Telnet: {e}")
                    self._reset()
                    continue

            else:
                if self.connect_request:
                    print("Connecting to Telnet")
                    self.connect()
                    self.connect_request = False
                else:
                    time.sleep(0.2)
        self.finishedSignal.emit()
        
    def _reset(self):
        try:
            print("reset du thread serial")
            self.telnet.close()
        except Exception as e:
            print(f"Error closing Telnet: {e}")
        self.running = False
        self.stop_request = False
        self.connect_request = False
        self.disconnect_request = False
        self.on_board_buf = 128
        self.past_cmd_len = queue.Queue()

        self.connected = False
        self._machine.set_no_wire_position()
        self.connection_changed.emit()
        
    def _process_read_data(self, data):
        #print(f"Received data from Telnet: {data}")
        if data == 'ok\r\n' and not self.test:
#        if(data == 'ok\r\n'&&!self.test):
            lg=self.past_cmd_len.get()
            #print (f"on ajoute a on_board_buf:{lg}")
            #print (f"buff_onboard vaut::{self.on_board_buf}")
            self.on_board_buf += lg
            #print (f"buff_onboard vaut::{self.on_board_buf}")
        elif(data != ''):
            if(data[0] == "<"):
                self._parse_status(data)
            else:
                # handle grbl errors here
                self.on_board_buf = 128
                pass
    def _process_read_dataold(self, data):
        if data.strip() == 'ok':  # Si la réponse est 'ok'
            self.on_board_buf += self.past_cmd_len.get()
            if self.on_board_buf >128:
                self.on_board_buf=128
        elif data.startswith("<"):  # Si la réponse commence par '<'
            self._parse_status(data.strip())  # Appel à la méthode de parsing des données de statut
       # else:
        #    print(f"Received unexpected data from Telnet: {data}")

    def _parse_status(self, status):
        #print("Parsing status...")
        mpos_idx = status.find("WPos:")
        if mpos_idx != -1:
            mpos_str = status[mpos_idx + 5:].split("|")[0].split(",")
            mpos = [float(i) for i in mpos_str]
            if mpos[0] == mpos[2] and mpos[1] == mpos[3]:
                mpos[3] += 0.001
            self._machine.set_wire_position(tuple(mpos))  # Utilisation de tuple() pour garantir l'immutabilité
            self.position_changed.emit(tuple(mpos))  # Emettre le signal avec la nouvelle position

        else:
            print("No MPos data found in status.")
