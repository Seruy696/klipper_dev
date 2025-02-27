import socket
import logging
from reactor import Reactor  # Убедитесь, что Reactor импортирован правильно

class SocketListener:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        
        # Чтение IP и PORT из конфигурации
        self.ip = '192.168.1.194'  # Устанавливаем значение по умолчанию
        self.port = 7777  # Устанавливаем значение по умолчанию
        
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Повторное использование адреса
        try:
            self.server_socket.bind((self.ip, self.port))
            logging.info(f"Server socket {self.port} created and listening")
        except socket.error as e:
            raise RuntimeError(f"Failed to bind to {self.ip}:{self.port}: {e}")
        except Exception as e:
            logging.error(f'Error while connecting to laser sensor: {e}, next try')
        
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command('LIDAR_READ_DATA', self.read_data_raw)
        self.gcode.register_command('LIDAR_CONNECT', self.cmd_CONNECT)
        self.gcode.register_command('LIDAR_DISCONNECT', self.cmd_DISCONNECT)  # Регистрируем команду DISCONNECT
        
        self.server_socket.listen(5)
        self.client_socket = None
        self.client_address = None
        self.received_data_laser = None  # Атрибут для хранения данных

        self.connection_status = 'disconnected'
        self._try_connect_timer = None

        self.printer.register_event_handler("klippy:connect", self._handle_connect)

    def _handle_connect(self):
        if not self._try_connect_timer:
            self._try_connect_timer = self.reactor.register_timer(self._conn_timer)
            self.reactor.update_timer(self._try_connect_timer, self.reactor.NOW)

    def _conn_timer(self, eventtime):
        try:
            self.client_socket, self.client_address = self.server_socket.accept()
            self.client_socket.setblocking(False)
            logging.info(f"Connection established with {self.client_address}")
            self.connection_status = 'ok'
            # Запускаем таймер для чтения данных
            self.reactor.register_timer(self.read_data, self.reactor.NOW)
            return self.reactor.NEVER  # Останавливаем этот таймер
        except BlockingIOError:
            logging.info(f'No connection yet on port: {self.port}, retrying...')
            return eventtime + 0.5  # Повторная попытка через 0.2 секунды
        except Exception as e:
            logging.error(f'Error while accepting connection: {e}')
            return eventtime + 0.5

    def cmd_CONNECT(self, gcmd):
        self.accept_connection(0)
        
    def cmd_DISCONNECT(self, gcmd):
        if self.client_socket:
            logging.info(f"Disconnecting client {self.client_address}")
            self.client_socket.close()
            self.client_socket = None
            self.client_address = None
            self.received_data_laser = None  # Очищаем данные
            gcmd.respond_raw("Client disconnected.")
        else:
            gcmd.respond_raw("No active client connection to disconnect.")

    def accept_connection(self, eventtime):
        try:
            self.client_socket, self.client_address = self.server_socket.accept()
            self.client_socket.setblocking(False)  # Устанавливаем неблокирующий режим
            logging.info(f"Connected by {self.client_address}")
            # Запускаем таймер для постоянного чтения данных
            self.reactor.register_timer(self.read_data, self.reactor.NOW)
        except socket.error as e:
            logging.error(f"Failed to accept connection: {e}")
            if self.client_socket:
                self.client_socket.close()
                self.client_socket = None
            self.reactor.register_timer(self.accept_connection, self.reactor.NOW + 0.1)  # Повторная попытка через 1 секунду
        except Exception as e:
            logging.error(f'Unexpected error in accept_connection: {e}')
            return eventtime + 0.5

    def read_data_raw(self, gcmd):
        if self.received_data_laser:
            gcmd.respond_raw(f"Data from lidar: {self.received_data_laser}")
        else:
            gcmd.respond_raw("No data received yet.")

    def read_data(self, eventtime):
        try:
            if not self.client_socket:
                logging.info("No client socket, stopping read_data timer")
                return self.reactor.NEVER  # Останавливаем таймер, если сокет закрыт

            # Проверяем, есть ли данные в сокете
            data = self.client_socket.recv(1024)
            if data == b'':  # Проверяем, если данные пустые (соединение закрыто)
                logging.info("Connection closed by laser client")
                self.client_socket.close()
                self.client_socket = None
                # self.received_data_laser = None  # Очищаем данные
                self.accept_connection(0)  # Принимаем новое соединение
                return eventtime + 0.1  # Продолжаем чтение
            if data != b'':
                # Обработка полученных данных
                logging.info(f"Raw data received from laser sensor: {data}")
                self.received_data_laser = data.decode('utf-8')  # Сохранение данных
                logging.info(f"Received data from laser sensor: {self.received_data_laser}")
                
        except BlockingIOError:
            # Если данных нет, продолжаем опрос
            pass
        except socket.error as e:
            logging.error(f"Socket error: {e}")
            self.client_socket.close()
            self.client_socket = None
            self.accept_connection(eventtime)  # Повторная попытка
            return eventtime + 0.5
        except Exception as e:
            logging.error(f'Unexpected error in read_data: {e}')
            return eventtime + 0.5

        # Регистрируем таймер для повторного вызова read_data через 0.1 секунды
        return eventtime + 0.5

    def get_status(self, eventtime):
        if self.received_data_laser:
            try:
                return {'received_data_laser': float(self.received_data_laser)}
            except ValueError:
                return {'received_data_laser': self.received_data_laser}
        return {'received_data_laser': None}


def load_config(config):
    return SocketListener(config)