# License: GPL 3

import xml.etree.ElementTree as ET

class MapServer:
    def __init__(self, server_id, proxy=None):
        self.error_code = 0
        self.url = None
        self.name = "Unknown"
        try:
            tree = ET.parse('params.xml')
            root = tree.getroot()
            for server in root.findall('.//server'):
                if server.find('id').text == str(server_id):
                    url_base = server.find('url-base').text
                    url_command = server.find('url-command').text
                    self.url = url_base + url_command
                    self.name = server.find('name').text
                    break
            else:
                self.error_code = 1  # Servidor não encontrado
                print(f"MapServer - Error: Server ID {server_id} not found in params.xml")
        except FileNotFoundError:
            self.error_code = 2  # params.xml não encontrado
            print("MapServer - Error: params.xml file not found")
        except Exception as err:
            self.error_code = 3  # Outro erro de parsing
            print(f"MapServer - Error parsing params.xml: {err}")
        self.proxy = proxy