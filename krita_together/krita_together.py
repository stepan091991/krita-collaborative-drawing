from krita import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QImage, QBitmap, QRegion, QColor
import json
import threading
import socket
import base64
import queue
import secrets


def variant_to_json(v):
    if isinstance(v, bool): return v
    if isinstance(v, int): return v
    if isinstance(v, float): return v
    if isinstance(v, str): return v
    if isinstance(v, QColor): return {'__type__': 'QColor', 'value': v.name()}
    return None

def json_to_variant(v):
    if isinstance(v, dict) and v.get('__type__') == 'QColor':
        return QColor(v['value'])
    return v


class KritaTogetherExtension(Extension):
    def __init__(self, parent, docker):
        super().__init__(parent)
        self.docker = docker

    def setup(self):
        pass

    def createActions(self, window):
        action = window.createAction("krita_together_menu", "Общий доступ...", "tools")
        action.triggered.connect(self.show_connect_dialog)

    def show_connect_dialog(self):
        dlg = QDialog()
        dlg.setWindowTitle("Общий доступ - Подключение")
        layout = QVBoxLayout(dlg)

        tabs = QTabWidget()

        # --- Вкладка 1: Прямое подключение ---
        direct_tab = QWidget()
        dl = QVBoxLayout(direct_tab)
        ip_edit = QLineEdit("127.0.0.1")
        port_edit = QLineEdit("50007")
        pass_edit = QLineEdit()
        pass_edit.setEchoMode(QLineEdit.Password)
        pass_edit.setPlaceholderText("Пароль (если есть)")
        dl.addWidget(QLabel("IP-адрес:"))
        dl.addWidget(ip_edit)
        dl.addWidget(QLabel("Порт:"))
        dl.addWidget(port_edit)
        dl.addWidget(QLabel("Пароль:"))
        dl.addWidget(pass_edit)

        # --- Вкладка 2: Через сервер ---
        relay_tab = QWidget()
        rl = QVBoxLayout(relay_tab)
        r_ip = QLineEdit()
        r_ip.setPlaceholderText("IP вашего VPS")
        r_port = QLineEdit("50008")
        r_room = QLineEdit(secrets.token_urlsafe(16))
        r_pass = QLineEdit()
        r_pass.setEchoMode(QLineEdit.Password)
        r_pass.setPlaceholderText("Пароль (если есть)")
        rl.addWidget(QLabel("IP сервера:"))
        rl.addWidget(r_ip)
        rl.addWidget(QLabel("Порт сервера:"))
        rl.addWidget(r_port)
        rl.addWidget(QLabel("Токен комнаты:"))
        rl.addWidget(r_room)
        rl.addWidget(QLabel("Пароль:"))
        rl.addWidget(r_pass)

        tabs.addTab(direct_tab, "Прямое")
        tabs.addTab(relay_tab, "Через сервер")
        layout.addWidget(tabs)

        btn_layout = QHBoxLayout()
        btn_host = QPushButton("Создать сессию")
        btn_connect = QPushButton("Подключиться")
        btn_layout.addWidget(btn_host)
        btn_layout.addWidget(btn_connect)
        layout.addLayout(btn_layout)

        def do_host():
            if tabs.currentIndex() == 0:
                self.docker.do_host(port_edit.text(), pass_edit.text())
            else:
                self.docker.do_relay_host(r_ip.text(), r_port.text(), r_room.text(), r_pass.text())
            dlg.accept()

        def do_connect():
            if tabs.currentIndex() == 0:
                self.docker.do_connect(ip_edit.text(), port_edit.text(), pass_edit.text())
            else:
                self.docker.do_relay_join(r_ip.text(), r_port.text(), r_room.text(), r_pass.text())
            dlg.accept()

        btn_host.clicked.connect(do_host)
        btn_connect.clicked.connect(do_connect)
        dlg.exec_()


class KritaTogetherDocker(DockWidget):
    update_canvas_signal = pyqtSignal(bytes, str, int, int, int, int)
    layer_update_signal = pyqtSignal(object)
    create_doc_signal = pyqtSignal(object)
    show_error_signal = pyqtSignal(str, str)
    ui_state_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Общий доступ")

        main_widget = QWidget()
        self.setWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # --- Прямое подключение ---
        self.direct_group = QGroupBox("Прямое подключение")
        dl = QVBoxLayout(self.direct_group)
        self.input_ip = QLineEdit("127.0.0.1")
        self.input_port = QLineEdit("50007")
        self.input_password = QLineEdit()
        self.input_password.setEchoMode(QLineEdit.Password)
        self.input_password.setPlaceholderText("Пароль (необязательно)")
        self.btn_host = QPushButton("Создать сессию")
        self.btn_connect = QPushButton("Подключиться")
        dl.addWidget(QLabel("IP-адрес:"))
        dl.addWidget(self.input_ip)
        dl.addWidget(QLabel("Порт:"))
        dl.addWidget(self.input_port)
        dl.addWidget(QLabel("Пароль:"))
        dl.addWidget(self.input_password)
        dl.addWidget(self.btn_host)
        dl.addWidget(self.btn_connect)

        # --- Через сервер ---
        self.relay_group = QGroupBox("Подключение через сервер")
        rl = QVBoxLayout(self.relay_group)
        self.relay_ip = QLineEdit()
        self.relay_ip.setPlaceholderText("IP вашего VPS")
        self.relay_port = QLineEdit("50008")
        self.relay_room = QLineEdit(secrets.token_urlsafe(16))
        self.relay_password = QLineEdit()
        self.relay_password.setEchoMode(QLineEdit.Password)
        self.relay_password.setPlaceholderText("Пароль (необязательно)")
        self.btn_relay_host = QPushButton("Создать комнату")
        self.btn_relay_join = QPushButton("Подключиться к комнате")
        rl.addWidget(QLabel("IP сервера:"))
        rl.addWidget(self.relay_ip)
        rl.addWidget(QLabel("Порт сервера:"))
        rl.addWidget(self.relay_port)
        rl.addWidget(QLabel("Токен комнаты:"))
        rl.addWidget(self.relay_room)
        rl.addWidget(QLabel("Пароль:"))
        rl.addWidget(self.relay_password)
        rl.addWidget(self.btn_relay_host)
        rl.addWidget(self.btn_relay_join)

        # --- Отключение и логи ---
        self.btn_disconnect = QPushButton("Отключиться")
        self.btn_disconnect.setVisible(False)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)

        layout.addWidget(self.direct_group)
        layout.addWidget(self.relay_group)
        layout.addWidget(self.btn_disconnect)
        layout.addWidget(QLabel("Журнал событий:"))
        layout.addWidget(self.log_output)

        # --- Состояние ---
        self.clients = []
        self.authenticated_clients = {}
        self.server_socket = None
        self.is_hosting = False
        self.session_password = ""

        self.client_socket = None
        self.is_connected = False
        self.authenticated = False

        self.is_relay = False
        self.relay_socket = None

        self.send_lock = threading.Lock()
        self.doc_lock = threading.RLock()

        self.outgoing_queue = queue.Queue()
        self.sender_thread = threading.Thread(target=self._sender_loop, daemon=True)
        self.sender_thread.start()

        self.is_applying_remote = False
        self.awaiting_sync = False
        self.last_pixel_data = {}
        self.last_layer_structure = None

        self.sync_timer = QTimer()
        self.sync_timer.setInterval(66)
        self.sync_timer.timeout.connect(self.sync_canvas)
        self.sync_timer.start()

        self.btn_host.clicked.connect(self.start_hosting)
        self.btn_connect.clicked.connect(self.connect_to_host)
        self.btn_relay_host.clicked.connect(self.start_relay_hosting)
        self.btn_relay_join.clicked.connect(self.connect_relay_join)
        self.btn_disconnect.clicked.connect(self.disconnect_session)

        self.update_canvas_signal.connect(self.apply_remote_canvas)
        self.layer_update_signal.connect(self.apply_layer_structure)
        self.create_doc_signal.connect(self.create_document_from_info)
        self.show_error_signal.connect(self._show_error_box)
        self.ui_state_signal.connect(self._apply_ui_state)

    # ================== UI ==================

    def _show_error_box(self, title, text):
        QMessageBox.warning(self, title, text)

    def _apply_ui_state(self, state):
        if state == 'disconnected':
            self.direct_group.setVisible(True)
            self.relay_group.setVisible(True)
            self.btn_disconnect.setVisible(False)
        elif state == 'hosting':
            self.direct_group.setVisible(False)
            self.relay_group.setVisible(False)
            self.btn_disconnect.setVisible(True)
            self.btn_disconnect.setText("Закрыть сессию")
        elif state == 'connected':
            self.direct_group.setVisible(False)
            self.relay_group.setVisible(False)
            self.btn_disconnect.setVisible(True)
            self.btn_disconnect.setText("Отключиться")

    def do_host(self, port, password):
        self.input_port.setText(port)
        self.input_password.setText(password)
        self.start_hosting()

    def do_connect(self, ip, port, password):
        self.input_ip.setText(ip)
        self.input_port.setText(port)
        self.input_password.setText(password)
        self.connect_to_host()

    def do_relay_host(self, ip, port, room, password):
        self.relay_ip.setText(ip)
        self.relay_port.setText(port)
        self.relay_room.setText(room)
        self.relay_password.setText(password)
        self.start_relay_hosting()

    def do_relay_join(self, ip, port, room, password):
        self.relay_ip.setText(ip)
        self.relay_port.setText(port)
        self.relay_room.setText(room)
        self.relay_password.setText(password)
        self.connect_relay_join()

    def disconnect_session(self):
        self.log("Отключение...")
        self.is_hosting = False
        self.is_connected = False
        self.is_relay = False

        if self.server_socket:
            try: self.server_socket.close()
            except: pass
            self.server_socket = None
        for c in self.clients:
            try: c.close()
            except: pass
        self.clients.clear()
        self.authenticated_clients.clear()

        if self.client_socket:
            try: self.client_socket.close()
            except: pass
            self.client_socket = None

        if self.relay_socket:
            try: self.relay_socket.close()
            except: pass
            self.relay_socket = None

        self.ui_state_signal.emit('disconnected')
        self.log("Сессия закрыта.")

    # ================== РЕLAY ==================

    def start_relay_hosting(self):
        if self.is_hosting or self.is_connected: return
        relay_ip = self.relay_ip.text().strip()
        relay_port = self.relay_port.text().strip()
        room = self.relay_room.text().strip()
        self.session_password = self.relay_password.text().strip()

        if not relay_ip or not relay_port.isdigit() or not room:
            self.show_error_signal.emit("Ошибка ввода", "Введите IP сервера, порт и токен комнаты.")
            return

        self.ui_state_signal.emit('hosting')
        self.log(f"Подключение к Relay {relay_ip}:{relay_port}...")

        def thread():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(10)
                sock.connect((relay_ip, int(relay_port)))
                sock.sendall(f"HOST:{room}\n".encode('utf-8'))
                resp = sock.recv(1024).decode('utf-8', errors='ignore').strip()
                sock.settimeout(None)

                if not resp.startswith("OK"):
                    self.log(f"Relay: {resp}")
                    self.show_error_signal.emit("Ошибка Relay", resp)
                    self.ui_state_signal.emit('disconnected')
                    try: sock.close()
                    except: pass
                    return

                self.log(f"Комната создана. Ожидание клиента...")
                self.is_hosting = True
                self.is_relay = True
                self.relay_socket = sock
                threading.Thread(target=self._relay_recv, args=(sock, True), daemon=True).start()
            except Exception as e:
                self.log(f"Ошибка Relay: {e}")
                self.show_error_signal.emit("Ошибка подключения", str(e))
                self.ui_state_signal.emit('disconnected')

        threading.Thread(target=thread, daemon=True).start()

    def connect_relay_join(self):
        if self.is_hosting or self.is_connected: return
        relay_ip = self.relay_ip.text().strip()
        relay_port = self.relay_port.text().strip()
        room = self.relay_room.text().strip()
        password = self.relay_password.text().strip()

        if not relay_ip or not relay_port.isdigit() or not room:
            self.show_error_signal.emit("Ошибка ввода", "Введите IP сервера, порт и токен комнаты.")
            return

        self.ui_state_signal.emit('connected')
        self.log(f"Подключение к Relay {relay_ip}:{relay_port}...")

        def thread():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(10)
                sock.connect((relay_ip, int(relay_port)))
                sock.sendall(f"JOIN:{room}\n".encode('utf-8'))
                resp = sock.recv(1024).decode('utf-8', errors='ignore').strip()
                sock.settimeout(None)

                if not resp.startswith("OK"):
                    self.log(f"Relay: {resp}")
                    self.show_error_signal.emit("Ошибка Relay", resp)
                    self.ui_state_signal.emit('disconnected')
                    try: sock.close()
                    except: pass
                    return

                self.log(f"Подключено к комнате. Отправка пароля...")
                self.is_connected = True
                self.is_relay = True
                self.relay_socket = sock
                self.awaiting_sync = True
                threading.Thread(target=self._relay_recv, args=(sock, False), daemon=True).start()
                self.outgoing_queue.put({'kind': 'forward', 'raw': {'type': 'hello', 'password': password}})
            except Exception as e:
                self.log(f"Ошибка Relay: {e}")
                self.show_error_signal.emit("Ошибка подключения", str(e))
                self.ui_state_signal.emit('disconnected')

        threading.Thread(target=thread, daemon=True).start()

    def _relay_recv(self, sock, is_host):
        buffer = ""
        while self.is_hosting or self.is_connected:
            try:
                data = sock.recv(65536).decode('utf-8')
                if not data: break
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip():
                        if is_host:
                            self.process_message(line, sender_sock=sock)
                        else:
                            self.process_message(line)
            except: break
        if is_host:
            self.log("Relay: клиент отключился.")
        else:
            self.log("Relay: соединение потеряно.")
            self.awaiting_sync = False
            self.ui_state_signal.emit('disconnected')

    # ================== ПРЯМОЕ ПОДКЛЮЧЕНИЕ ==================

    def start_hosting(self):
        if self.is_hosting or self.is_connected: return
        port = self.input_port.text().strip()
        if not port.isdigit():
            self.show_error_signal.emit("Ошибка ввода", "Порт должен быть числом.")
            return
        self.session_password = self.input_password.text().strip()
        self.is_hosting = True
        self.is_relay = False
        self.ui_state_signal.emit('hosting')
        threading.Thread(target=self._server_thread, args=(int(port),), daemon=True).start()

    def _server_thread(self, port):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind(("0.0.0.0", port))
            self.server_socket.listen(5)
            pwd_msg = "с паролем" if self.session_password else "без пароля"
            self.log(f"Сервер запущен на порту {port} ({pwd_msg}).")
        except Exception as e:
            self.log(f"Ошибка сервера: {e}")
            self.is_hosting = False
            self.ui_state_signal.emit('disconnected')
            self.show_error_signal.emit("Ошибка сервера", f"Порт {port} занят или недоступен:\n{e}")
            return

        while self.is_hosting:
            try:
                client_sock, addr = self.server_socket.accept()
                self.clients.append(client_sock)
                self.authenticated_clients[client_sock] = False
                self.log(f"Клиент {addr} подключился, ожидание авторизации...")
                threading.Thread(target=self._handle_client, args=(client_sock,), daemon=True).start()
            except: break

    def _handle_client(self, client_sock):
        buffer = ""
        while self.is_hosting:
            try:
                data = client_sock.recv(65536).decode('utf-8')
                if not data: break
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip(): self.process_message(line, sender_sock=client_sock)
            except: break
        if client_sock in self.clients: self.clients.remove(client_sock)
        if client_sock in self.authenticated_clients: del self.authenticated_clients[client_sock]
        self.log("Клиент отключился.")

    def connect_to_host(self):
        ip = self.input_ip.text().strip()
        port = self.input_port.text().strip()
        if not ip or not port.isdigit():
            self.show_error_signal.emit("Ошибка ввода", "Введите корректный IP и Порт.")
            return
        if self.is_connected or self.is_hosting: return
        password = self.input_password.text().strip()

        self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.client_socket.connect((ip, int(port)))
            self.is_connected = True
            self.is_relay = False
            self.awaiting_sync = True
            self.ui_state_signal.emit('connected')
            self.log(f"Подключено к {ip}:{port}. Отправка пароля...")
            threading.Thread(target=self._client_receive_thread, daemon=True).start()
            self.outgoing_queue.put({'kind': 'forward', 'raw': {'type': 'hello', 'password': password}})
        except ConnectionRefusedError:
            self.log(f"Подключение к {ip}:{port} отклонено.")
            self.show_error_signal.emit("Ошибка подключения", f"Хост не отвечает на {ip}:{port}.\nПроверьте IP, порт и запущен ли хост.")
            self.disconnect_session()
        except Exception as e:
            self.log(f"Ошибка подключения: {e}")
            self.show_error_signal.emit("Ошибка подключения", str(e))
            self.disconnect_session()

    def _client_receive_thread(self):
        buffer = ""
        while self.is_connected:
            try:
                data = self.client_socket.recv(65536).decode('utf-8')
                if not data: break
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    if line.strip(): self.process_message(line)
            except: break
        self.is_connected = False
        self.awaiting_sync = False
        self.ui_state_signal.emit('disconnected')
        self.log("Соединение с сервером потеряно.")

    # ================== ОБРАБОТКА СООБЩЕНИЙ ==================

    def process_message(self, message_str, sender_sock=None):
        try:
            msg = json.loads(message_str)
            msg_type = msg.get("type")

            if msg_type == "hello" and self.is_hosting and sender_sock:
                client_password = msg.get("password", "")
                if client_password == self.session_password:
                    self.authenticated_clients[sender_sock] = True
                    self.log("Клиент авторизован.")
                    self._send_doc_info(sender_sock)
                else:
                    self.log("Клиент ввел неверный пароль. Отключение.")
                    self._do_send({"type": "auth_failed"}, target_sock=sender_sock)
                    try: sender_sock.close()
                    except: pass
                return

            if msg_type == "auth_failed":
                self.log("Ошибка авторизации: неверный пароль.")
                self.show_error_signal.emit("Ошибка авторизации", "Введенный пароль неверен.")
                self.disconnect_session()
                return

            if msg_type == "doc_info":
                if 'error' in msg:
                    self.log(f"Ошибка хоста: {msg['error']}")
                    self.show_error_signal.emit("Ошибка хоста", msg['error'])
                    self.disconnect_session()
                    return
                self.log(f"Получен холст {msg['width']}x{msg['height']} @ {msg['resolution']} DPI")
                self.create_doc_signal.emit(msg)
                return

            if msg_type == "canvas_update":
                png_data = base64.b64decode(msg['png'])
                self.update_canvas_signal.emit(png_data, msg['layer'], msg['x'], msg['y'], msg['w'], msg['h'])

            elif msg_type == "layers_update":
                self.layer_update_signal.emit(msg['layers'])

            elif msg_type == "request_sync" and self.is_hosting and sender_sock:
                if self.authenticated_clients.get(sender_sock, False):
                    self.log("Клиент запросил полную синхронизацию.")
                    self.outgoing_queue.put({'kind': 'full_sync_to', 'target': sender_sock})

            elif msg_type == "full_sync_end":
                self.awaiting_sync = False
                self.authenticated = True
                self.log("Синхронизация завершена. Можно рисовать!")

            # Пересылка (только для прямого multi-client режима)
            if self.is_hosting and sender_sock and not self.is_relay and msg_type not in ("hello", "request_sync"):
                if self.authenticated_clients.get(sender_sock, False):
                    self.outgoing_queue.put({'kind': 'forward', 'raw': msg_dict})
        except: pass

    # ================== ОСТАЛЬНАЯ ЛОГИКА (без изменений) ==================
    # --- Создание документа ---
    def create_document_from_info(self, info):
        try:
            app = Krita.instance()
            name = "Сессия Общий доступ"
            doc = app.createDocument(
                info['width'], info['height'], name,
                info['colorModel'], info['colorDepth'], info['colorProfile'],
                info['resolution']
            )
            if doc:
                app.activeWindow().addView(doc)
                self.log(f"Создан холст {info['width']}x{info['height']} @ {info['resolution']} DPI")
                QTimer.singleShot(1000, self._request_sync_after_create)
            else:
                self.log("ОШИБКА: Не удалось создать документ.")
        except Exception as e:
            self.log(f"Ошибка создания документа: {e}")

    def _request_sync_after_create(self):
        self.log("Холст готов. Запрос полной синхронизации...")
        self.outgoing_queue.put({'kind': 'request_sync'})

    # --- Синхронизация ---
    def find_layer_by_name(self, doc, name):
        for node in doc.rootNode().childNodes():
            if node.name() == name:
                return node
        return None

    def get_layer_info(self, doc):
        result = []
        for node in doc.rootNode().childNodes():
            info = {
                'name': node.name(),
                'type': node.type(),
                'visible': node.visible(),
                'opacity': node.opacity(),
                'blend_mode': node.blendingMode(),
            }
            if node.type() in ('filterlayer', 'filtermask'):
                try:
                    f = node.filter()
                    if f:
                        info['filter_id'] = f.name()
                        props = f.configuration().properties()
                        serialized = {}
                        for k in props:
                            val = variant_to_json(props[k])
                            if val is not None:
                                serialized[k] = val
                        if serialized:
                            info['filter_props'] = serialized
                except Exception: pass
            result.append(info)
        return result

    def find_dirty_rect(self, last_img, current_img, w, h):
        diff_img = QImage(w, h, QImage.Format_ARGB32)
        diff_img.fill(0)
        painter = QPainter(diff_img)
        painter.setCompositionMode(QPainter.CompositionMode_Difference)
        painter.drawImage(0, 0, last_img)
        painter.drawImage(0, 0, current_img)
        painter.end()
        mask = diff_img.createAlphaMask()
        return QRegion(QBitmap.fromImage(mask)).boundingRect()

    def sync_canvas(self):
        if self.is_applying_remote or self.awaiting_sync: return
        app = Krita.instance()
        window = app.activeWindow()
        if not window: return
        view = window.activeView()
        if not view or not view.document(): return
        doc = view.document()
        with self.doc_lock:
            current_layers = self.get_layer_info(doc)
            if self.last_layer_structure != current_layers:
                self.last_layer_structure = current_layers
                self.outgoing_queue.put({'kind': 'layers', 'layers': current_layers})
            for node in doc.rootNode().childNodes():
                if node.type() == 'paintlayer' and node.visible():
                    self.sync_layer_pixels(doc, node)

    def sync_layer_pixels(self, doc, layer):
        layer_name = layer.name()
        w, h = doc.width(), doc.height()
        current_bytes = layer.pixelData(0, 0, w, h)
        if layer_name not in self.last_pixel_data:
            self.last_pixel_data[layer_name] = {
                'bytes': current_bytes,
                'img': QImage(current_bytes, w, h, QImage.Format_ARGB32)
            }
            return
        last = self.last_pixel_data[layer_name]
        if current_bytes == last['bytes']: return
        current_img = QImage(current_bytes, w, h, QImage.Format_ARGB32)
        rect = self.find_dirty_rect(last['img'], current_img, w, h)
        if rect.isEmpty():
            self.last_pixel_data[layer_name] = {'bytes': current_bytes, 'img': current_img}
            return
        x, y, rw, rh = rect.x(), rect.y(), rect.width(), rect.height()
        sub_img = current_img.copy(x, y, rw, rh)
        self.outgoing_queue.put({
            'kind': 'pixels', 'layer': layer_name,
            'x': x, 'y': y, 'w': rw, 'h': rh, 'image': sub_img
        })
        self.last_pixel_data[layer_name] = {'bytes': current_bytes, 'img': current_img}

    # --- Применение ---
    def apply_remote_canvas(self, png_data, layer_name, x, y, w, h):
        was_applying = self.is_applying_remote
        self.is_applying_remote = True
        try:
            with self.doc_lock:
                app = Krita.instance()
                view = app.activeWindow().activeView()
                if not view or not view.document(): return
                doc = view.document()
                layer = self.find_layer_by_name(doc, layer_name)
                if not layer or layer.type() != 'paintlayer': return
                img = QImage.fromData(png_data, "PNG").convertToFormat(QImage.Format_ARGB32)
                if img.width() != w or img.height() != h:
                    img = img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                layer.setPixelData(img.constBits().asstring(img.byteCount()), x, y, w, h)
                dw, dh = doc.width(), doc.height()
                full = layer.pixelData(0, 0, dw, dh)
                self.last_pixel_data[layer_name] = {'bytes': full, 'img': QImage(full, dw, dh, QImage.Format_ARGB32)}
                doc.refreshProjection()
        except Exception as e:
            self.log(f"Ошибка применения холста: {e}")
        finally:
            self.is_applying_remote = was_applying

    def apply_layer_structure(self, layers_info):
        was_applying = self.is_applying_remote
        self.is_applying_remote = True
        try:
            with self.doc_lock:
                app = Krita.instance()
                view = app.activeWindow().activeView()
                if not view or not view.document(): return
                doc = view.document()
                root = doc.rootNode()
                existing = root.childNodes()
                changed = False

                while len(existing) > len(layers_info):
                    node = existing[-1]; name = node.name()
                    node.remove()
                    if name in self.last_pixel_data: del self.last_pixel_data[name]
                    existing = root.childNodes(); changed = True

                while len(existing) < len(layers_info):
                    info = layers_info[len(existing)]
                    nn = None
                    if info['type'] == 'filterlayer' and 'filter_id' in info:
                        try:
                            f = Krita.instance().filter(info['filter_id'])
                            if f:
                                cfg = f.configuration()
                                for k, v in info.get('filter_props', {}).items():
                                    try: cfg.setProperty(k, json_to_variant(v))
                                    except: pass
                                nn = doc.createFilterLayer(info['name'], f)
                        except Exception as e: self.log(f"Ошибка фильтра: {e}")
                    if nn is None:
                        nn = doc.createNode(info['name'], info['type'])
                    if nn:
                        try:
                            nn.setVisible(info['visible'])
                            nn.setOpacity(info['opacity'])
                            nn.setBlendingMode(info['blend_mode'])
                            root.addChildNode(nn, None)
                        except: pass
                    existing = root.childNodes(); changed = True

                for i, info in enumerate(layers_info):
                    if i >= len(existing): break
                    node = existing[i]
                    if node.name() != info['name']:
                        old = node.name(); node.setName(info['name'])
                        if old in self.last_pixel_data:
                            self.last_pixel_data[info['name']] = self.last_pixel_data.pop(old)
                    try:
                        if node.visible() != info['visible']: node.setVisible(info['visible']); changed = True
                        if node.opacity() != info['opacity']: node.setOpacity(info['opacity']); changed = True
                        if node.blendingMode() != info['blend_mode']: node.setBlendingMode(info['blend_mode']); changed = True
                    except: pass
                    if info['type'] in ('filterlayer', 'filtermask') and 'filter_props' in info:
                        try:
                            f = node.filter()
                            if f:
                                cfg = f.configuration()
                                cur = cfg.properties()
                                for k, v in info['filter_props'].items():
                                    if k in cur:
                                        val = json_to_variant(v)
                                        try:
                                            if str(cur[k]) != str(val):
                                                cfg.setProperty(k, val); changed = True
                                        except: pass
                        except: pass
                if changed: doc.refreshProjection()
                self.last_layer_structure = layers_info
        except Exception as e:
            self.log(f"Ошибка применения слоёв: {e}")
        finally:
            self.is_applying_remote = was_applying

    # --- Отправка ---
    def _send_full_sync(self, target_sock):
        app = Krita.instance()
        view = app.activeWindow().activeView()
        if not view or not view.document():
            self._do_send({"type": "full_sync_end"}, target_sock=target_sock)
            return
        doc = view.document()
        self._do_send({"type": "layers_update", "layers": self.get_layer_info(doc)}, target_sock=target_sock)
        w, h = doc.width(), doc.height()
        for node in doc.rootNode().childNodes():
            if node.type() == 'paintlayer':
                data = node.pixelData(0, 0, w, h)
                img = QImage(data, w, h, QImage.Format_ARGB32)
                ba = QByteArray(); buf = QBuffer(ba); buf.open(QIODevice.WriteOnly)
                img.save(buf, "PNG"); buf.close()
                b64 = base64.b64encode(ba.data()).decode('utf-8')
                self._do_send({
                    "type": "canvas_update", "png": b64, "layer": node.name(),
                    "x": 0, "y": 0, "w": w, "h": h
                }, target_sock=target_sock)
        self._do_send({"type": "full_sync_end"}, target_sock=target_sock)

    def _send_doc_info(self, target_sock):
        app = Krita.instance()
        view = app.activeWindow().activeView()
        if not view or not view.document():
            self._do_send({"type": "doc_info", "error": "У хоста не открыт документ"}, target_sock=target_sock)
            return
        doc = view.document()
        self._do_send({
            'type': 'doc_info',
            'width': doc.width(), 'height': doc.height(),
            'resolution': doc.resolution(), 'colorModel': doc.colorModel(),
            'colorDepth': doc.colorDepth(), 'colorProfile': doc.colorProfile(),
        }, target_sock=target_sock)

    def _sender_loop(self):
        while True:
            try: item = self.outgoing_queue.get(timeout=0.5)
            except queue.Empty: continue
            if item is None: break
            try:
                if item['kind'] == 'pixels':
                    img = item['image']
                    ba = QByteArray(); buf = QBuffer(ba); buf.open(QIODevice.WriteOnly)
                    img.save(buf, "PNG"); buf.close()
                    b64 = base64.b64encode(ba.data()).decode('utf-8')
                    self._do_send({
                        "type": "canvas_update", "png": b64, "layer": item['layer'],
                        "x": item['x'], "y": item['y'], "w": item['w'], "h": item['h']
                    })
                elif item['kind'] == 'layers':
                    self._do_send({"type": "layers_update", "layers": item['layers']})
                elif item['kind'] == 'forward':
                    self._do_send(item['raw'])
                elif item['kind'] == 'request_sync':
                    self._do_send({"type": "request_sync"})
                elif item['kind'] == 'full_sync_to':
                    self._send_full_sync(item['target'])
            except Exception as e:
                self.log(f"Ошибка отправки: {e}")

    def _do_send(self, msg_dict, target_sock=None):
        msg_str = (json.dumps(msg_dict) + '\n').encode('utf-8')
        with self.send_lock:
            if target_sock:
                try: target_sock.sendall(msg_str)
                except: pass
                return
            if self.is_relay and self.relay_socket:
                try: self.relay_socket.sendall(msg_str)
                except: pass
            elif self.is_hosting:
                for c in list(self.clients):
                    if self.authenticated_clients.get(c, False):
                        try: c.sendall(msg_str)
                        except: pass
            elif self.is_connected and self.client_socket:
                try: self.client_socket.sendall(msg_str)
                except: pass

    def log(self, text):
        QMetaObject.invokeMethod(self.log_output, "append", Qt.QueuedConnection, Q_ARG(str, text))

    def canvasChanged(self, canvas):
        pass