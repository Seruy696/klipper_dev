import socket
import logging

class SocketListener:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        
        # Чтение IP и PORT из конфигурации
        self.ip = '192.168.1.194'  # Устанавливаем значение по умолчанию
        self.port = 5000  # Устанавливаем значение по умолчанию
        
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Повторное использование адреса
        try:
            self.server_socket.bind((self.ip, self.port))
        except socket.error as e:
            raise RuntimeError(f"Failed to bind to {self.ip}:{self.port}: {e}")
        
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command('LIDAR_READ_DATA', self.read_data_raw)
        
        self.server_socket.listen(5)
        self.client_socket = None
        self.client_address = None
        self.received_data = None  # Атрибут для хранения данных
        self.printer.register_event_handler("klippy:connect", self.handle_connect)
        self.printer.register_event_handler("klippy:disconnect", self.handle_disconnect)

    def handle_connect(self):
        self.reactor.register_callback(self.accept_connection)

    def handle_disconnect(self):
        if self.client_socket:
            self.client_socket.close()
        self.server_socket.close()

    def accept_connection(self, eventtime):
        self.client_socket, self.client_address = self.server_socket.accept()
        self.client_socket.setblocking(False)  # Устанавливаем неблокирующий режим
        logging.info(f"Connected by {self.client_address}")
        # Запускаем таймер для постоянного чтения данных
        self.reactor.register_timer(self.read_data, self.reactor.NOW)

    def read_data_raw(self, gcmd):
        if self.received_data:
            gcmd.respond_raw(f"Data from lidar: {self.received_data}")
        else:
            gcmd.respond_raw("No data received yet.")

    def read_data(self, eventtime):
        try:
            # Проверяем, есть ли данные в сокете
            data = self.client_socket.recv(1024)
            # logging.info(f"data from socket: {data}")
            if data == b'':  # Проверяем, если данные пустые (соединение закрыто)
                # logging.info("No data received, restarting socket")
                self.client_socket.close()
                self.client_socket = None
                self.reactor.register_callback(self.accept_connection)  # Принимаем новое соединение
                return self.reactor.NEVER  # Останавливаем таймер, чтобы не продолжать чтение
            if data != b'':
                # Обработка полученных данных
                self.received_data = data.decode('utf-8')  # Сохранение данных
                # logging.info(f"Received data: {self.received_data}")
            else:
                # Если данные не пришли, просто продолжаем опрос
                pass
        except BlockingIOError:
            # Если данных нет, продолжаем опрос
            pass
        except socket.error as e:
            logging.error(f"Socket error: {e}")
            self.client_socket.close()
            self.client_socket = None
            return self.reactor.NEVER

        # Регистрируем таймер для повторного вызова read_data через 0.1 секунды
        return eventtime + 0.1

    def get_status(self, eventtime):
        if self.received_data:
            try:
                return {'received_data': float(self.received_data)}
            except ValueError:
                return {'received_data': self.received_data}
        return {'received_data': None}

def load_config(config):
    return SocketListener(config)