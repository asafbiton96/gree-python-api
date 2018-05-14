import socket
import base64
import json

from .gree_config import GreeConfig
from .aes_cipher import AESCipher
from .exceptions import InvalidParameterGiven, InvalidResponse, UnexpectedResponse


class GreeDevice():
    GENERIC_AES_KEY = b"a3K8Bx%2r8Y7#xDh"
    SCAN_PACKET = b'{"t": "scan"}'

    def __init__(self, mac, unique_key, host='255.255.255.255', port=7000, timeout=15):
        if ':' in mac:
            mac = mac.replace(':', '')
        self.__mac = mac
        self.__unique_key = unique_key
        self.__host = host
        self.__port = port

        self.__unique_cipher = AESCipher(self.__unique_key)

        self.__sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.__sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.__sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.__sock.settimeout(timeout)

        self._status = None

    def __encrypt_pack(self, json_pack):
        bytestring = str.encode(json.dumps(json_pack))
        return base64.b64encode(self.__unique_key.encrypt(bytestring))

    def __generate_status_packet(self):
        pack = json.loads("""
        {
          "cols": [
            "Pow", 
            "Mod", 
            "SetTem", 
            "WdSpd", 
            "Air", 
            "Blo", 
            "Health", 
            "SwhSlp", 
            "Lig", 
            "SwingLfRig", 
            "SwUpDn", 
            "Quiet", 
            "Tur", 
            "StHt", 
            "TemUn", 
            "HeatCoolType", 
            "TemRec", 
            "SvSt"
          ],
          "mac": "<MAC address>",
          "t": "status"
        }
        """)
        pack['mac'] = self.__mac

        encrypted_pack = self.__encrypt_pack(pack)

        packet = json.loads("""{
            "cid": "app",
            "i": 0,
            "pack": "<encrypted, encoded pack>",
            "t": "pack",
            "tcid": "<MAC address>",
            "uid": 0
        }""")
        packet['pack'] = encrypted_pack.decode('utf-8')
        packet['tcid'] = self.__mac

        return packet

    def _send_json(self, json_packet):
        return self.__sock.sendto(json.dumps(json_packet), (self.__host, self.__port)) > 0

    def __recv_response(self):
        response = ''
        while True:
            data = self.__sock.recvfrom(1024)[0]
            if not data:
                break
            response += data

        return json.loads(response)

    def __parse_response(self, response, cipher=None):
        cipher = cipher or self.__unique_cipher
        if type(cipher) is not AESCipher:
            raise InvalidParameterGiven("[_parse_response]: Param cipher is not of type AESCipher")

        if 'pack' not in response:
            raise InvalidResponse("[_parse_response]: Response object has no 'pack' field")

        pack = response['pack']
        decoded_pack = base64.b64decode(pack)
        decrypted_pack = json.loads(cipher.decrypt(decoded_pack))

        response['pack'] = decrypted_pack

        return response

    def __generate_cmd_packet(self, config):
        pack = json.loads("""{
          "opt": ["TemUn", "SetTem"],
          "p": [0, 27],
          "t": "cmd"
        }""")
        pack['opt'] = config.config.keys()
        pack['p'] = config.config.values()

        encrypted_pack = self.__encrypt_pack(pack)

        packet = json.loads("""{
          "cid": "app",
          "i": 0,
          "pack": "<encrypted, encoded pack>",
          "t": "pack",
          "tcid": "<MAC address>",
          "uid": 0
        }""")
        packet['pack'] = encrypted_pack.decode('utf-8')
        packet['tcid'] = self.__mac

        return packet

    def update_status(self):
        status_packet = self.__generate_status_packet()

        if self._send_json(status_packet):
            response = self.__recv_response()
            parsed_response = self.__parse_response(response)

            status = {}
            keys = parsed_response['pack']['cols']
            values = parsed_response['pack']['dat']

            for i in range(keys):
                status[keys[i]] = values[i]

            self._status = status
            return True
        return False

    def send_command(self, power_on=None, temperature=None, mode=None,
                     is_quiet=None, fan_speed=None, swing=None,
                     energy_saving=None, display_on=None, health_mode=None,
                     air_valve=None, blow_mode=None, turbo_mode=None):
        """
        :param power_on: bool
        :param temperature: int
        :param mode: int (GreeConfig.MODES)
        :param is_quiet: bool
        :param fan_speed: int (0-5)
        :param swing: int (0-11)
        :param energy_saving: bool
        :param display_on: bool
        :param health_mode: bool
        :param air_valve: bool
        :param blow_mode: bool
        :param turbo_mode: bool
        :return:
        """

        config = GreeConfig()
        if power_on:        config.power_on = power_on
        if temperature:     config.temperature = temperature
        if mode:            config.mode = mode
        if is_quiet:        config.fan_speed = fan_speed
        if fan_speed:       config.swing = swing
        if swing:           config.quiet_mode_enabled = is_quiet
        if energy_saving:   config.energy_saving_enabled = energy_saving
        if display_on:      config.display_enabled = display_on
        if health_mode:     config.health_mode_enabled = health_mode
        if air_valve:       config.air_valve_enabled = air_valve
        if blow_mode:       config.blow_mode_enabled = blow_mode
        if turbo_mode:      config.turbo_mode_enabled = turbo_mode

        cmd_packet = self.__generate_cmd_packet(config)

        if self._send_json(cmd_packet):
            response = self.__recv_response()
            parsed_response = self.__parse_response(response)

            if parsed_response['pack']['r'] != 200:
                raise UnexpectedResponse(f"Pack parameter 'r' is different than expected "
                                         f"(received {parsed_response['pack']['r']}, expected 200). "
                                         f"This may mean an error has occured.")

            return True
        return False

    @property
    def status(self):
        if not self._status:
            self.update_status()
        return self._status