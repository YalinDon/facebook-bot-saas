# app/services.py

from cryptography.fernet import Fernet
from flask import current_app

class EncryptionService:
    def __init__(self):
        key = current_app.config['ENCRYPTION_KEY']
        if not key:
            raise ValueError("ENCRYPTION_KEY n'est pas définie dans la configuration.")
        self.fernet = Fernet(key.encode())

    def encrypt(self, data: str) -> str:
        """Chiffre une chaîne de caractères et retourne le résultat encodé en utf-8."""
        if not isinstance(data, str):
            raise TypeError("La donnée à chiffrer doit être une chaîne de caractères.")
        return self.fernet.encrypt(data.encode('utf-8')).decode('utf-8')

    def decrypt(self, encrypted_data: str) -> str:
        """Déchiffre une chaîne et retourne la chaîne originale."""
        if not isinstance(encrypted_data, str):
            raise TypeError("La donnée à déchiffrer doit être une chaîne de caractères.")
        return self.fernet.decrypt(encrypted_data.encode('utf-8')).decode('utf-8')
