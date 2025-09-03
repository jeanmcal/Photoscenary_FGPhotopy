import socket
import time
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('telnet_test.log'), logging.StreamHandler()]
)

def test_telnet():
    host = "127.0.0.1"
    port = 5000
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30.0)  # Timeout aumentado para 30 segundos
        logging.info(f"Conectando a {host}:{port}")
        sock.connect((host, port))
        logging.info("Conexão estabelecida")

        # Teste 1: Enviar comando 'data'
        logging.debug("Enviando: 'data\\r\\n'")
        sock.send(b"data\r\n")
        time.sleep(2)  # Pausa maior para FGFS processar
        data = ""
        start_time = time.time()
        while time.time() - start_time < 10.0:
            try:
                chunk = sock.recv(1024).decode('utf-8', errors='ignore')
                data += chunk
                if data.strip():
                    break
            except socket.timeout:
                continue
        logging.debug(f"Resposta do comando 'data': {data!r}")

        # Teste 2: Enviar comando de latitude
        logging.debug("Enviando: 'get /position/latitude-deg\\r\\n'")
        sock.send(b"get /position/latitude-deg\r\n")
        time.sleep(2)
        data = ""
        start_time = time.time()
        while time.time() - start_time < 10.0:
            try:
                chunk = sock.recv(1024).decode('utf-8', errors='ignore')
                data += chunk
                if data.strip():
                    break
            except socket.timeout:
                continue
        logging.debug(f"Resposta latitude: {data!r}")

        # Teste 3: Enviar comando de longitude
        logging.debug("Enviando: 'get /position/longitude-deg\\r\\n'")
        sock.send(b"get /position/longitude-deg\r\n")
        time.sleep(2)
        data = ""
        start_time = time.time()
        while time.time() - start_time < 10.0:
            try:
                chunk = sock.recv(1024).decode('utf-8', errors='ignore')
                data += chunk
                if data.strip():
                    break
            except socket.timeout:
                continue
        logging.debug(f"Resposta longitude: {data!r}")

        # Tentar parsear as respostas
        if '=' in data:
            try:
                lon = float(data.split("=")[-1].strip("\r\n\t "))
                logging.info(f"Longitude obtida: {lon}")
            except ValueError as e:
                logging.error(f"Erro ao parsear longitude: {str(e)}")

    except socket.timeout:
        logging.error("Timeout ao tentar comunicar com o FGFS")
    except socket.error as e:
        logging.error(f"Erro de socket: {str(e)}")
    except Exception as e:
        logging.error(f"Erro inesperado: {str(e)}")
    finally:
        sock.close()
        logging.info("Conexão fechada")

if __name__ == "__main__":
    test_telnet()