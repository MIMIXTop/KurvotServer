import base64
import binascii
import hashlib
import os
import secrets
import urllib.parse
from typing import Dict, List, Tuple, Union

from app.config import settings
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

IV_LEN = 12
TAG_LEN = 16

class Encryption:

    def __init__(self, key: str) -> None:
        self.__key = key
        self.__key_buffer = hashlib.sha256(self.__key.encode("utf-8")).digest()
        self.__aesgcm = AESGCM(self.__key_buffer)

    def random_url_safe_token(self, byte_count: int) -> str:
        token_bytes = secrets.token_bytes(byte_count)
        return base64.urlsafe_b64encode(token_bytes).decode("ascii").rstrip("=")

    def sha256_hex(self, date: str) -> str:
        return hashlib.sha256(date.encode("utf-8")).hexdigest()

    def url_encode_helper(self, params: Union[List[Tuple[str, str]], Dict[str, str]]) -> str:
        return urllib.parse.urlencode(params)
    def text_encrypt(self, text: str) -> str:
        if not self.__key:
            raise RuntimeError("Invalid Key Length")

        iv = os.urandom(IV_LEN)

        ciphertext = self.__aesgcm.encrypt(iv, text.encode("utf-8"), None)
        combined =iv + ciphertext
        return base64.urlsafe_b64encode(combined).decode("ascii")

    def text_decrypt(self, text: str) -> str:
        if not self.__key:
            raise RuntimeError("Invalid Key Length")

        try:
            combined =base64.urlsafe_b64decode(text.encode("ascii"))
        except Exception as e:
            raise RuntimeError(f"Ошибка декодирования Base64: {e}")

        if len(combined) < IV_LEN + TAG_LEN:
            raise RuntimeError("Неверный формат или длина зашифрованных данных")

        iv = combined[:IV_LEN]
        ciphertext = combined[IV_LEN:]

        try:
            decrypted = self.__aesgcm.decrypt(iv, ciphertext, None)
            return decrypted.decode("utf-8")
        except InvalidTag:
            raise RuntimeError(
                "Данные были изменены или использован неверный ключ (провал проверки MAC)"
            )
        except Exception as ex:
            raise RuntimeError(
                f"Ошибка расшифровки (возможно, неверный ключ или данные повреждены): {ex}"
            )

encryption = Encryption(settings.TOKEN_ENCRYPTION_KEY)
