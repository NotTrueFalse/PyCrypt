import hashlib
import os
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from argon2 import PasswordHasher
import random
# import time


class SectorCrypt:
    def __init__(self, password: str, pin: str):
        """
        Initialize the SectorCrypt with a password and a PIN (acting as a salt).
        
        :param password: User-provided password.
        :param pin: User-provided PIN code (used as the salt).
        """
        self.raw_password = password
        self.pin = pin.encode("utf-8")  # PIN as bytes
        self.pin = hashlib.shake_256(self.pin).digest(16)  # Truncate to 16 bytes
        Mo = 1024 ** 2  # 1 MiB in bytes
        self.ph = PasswordHasher(
            time_cost=2,
            memory_cost=Mo,
            parallelism=2,
            hash_len=32,
            salt_len=len(self.pin),
        )
        self.password = self._derive_password()
        self.aes_module = AES.new(self.password, AES.MODE_ECB)

    def _derive_password(self) -> bytes:
        """
        Derive a 32-byte key from the password and PIN (acting as the salt) using Argon2.
        """
        # start = time.time()
        # Use the PIN directly as the salt for key derivation
        key = self.ph.hash(self.raw_password, salt=self.pin)
        key = hashlib.sha256(key.encode("utf-8")).digest()  # Final key as 32 bytes
        # end = time.time()
        # print(f"Key derivation time: {end - start:.2f} seconds")
        return key

    def _generate_seed(self, sector_number: int) -> int:
        """Generate a deterministic seed based on password and sector number."""
        combined = self.password + sector_number.to_bytes(4, "big") + self.pin
        return int(combined.hex(), 16)#we don't want to sha256 for every sector else it will be slow

    def encrypt_sector(self, sector_number: int, data: bytes) -> bytes:
        """Encrypt a sector with AES, shuffle, and add noise."""
        if len(data) % 16 != 0:#don't pad if already a multiple of 16
            data = pad(data, AES.block_size)
        encrypted_data = self.aes_module.encrypt(data)
        seed = self._generate_seed(sector_number)
        shuffled_data = self._shuffle_bytes(seed, encrypted_data)
        noisy_data = self._noise(seed, shuffled_data)
        if len(noisy_data) != len(data):
            raise ValueError("Data length changed during encryption!")
        return noisy_data

    def decrypt_sector(self, sector_number: int, data: bytes) -> bytes:
        """Reverse noise, unshuffle, and decrypt a sector."""
        seed = self._generate_seed(sector_number)
        unnoised_data = self._noise(seed, data)
        unshuffled_data = self._shuffle_bytes(seed, unnoised_data, reverse=True)
        decrypted_data = self.aes_module.decrypt(unshuffled_data)
        if len(decrypted_data) % 16 != 0:
            decrypted_data = unpad(decrypted_data, AES.block_size)
        return decrypted_data

    def _shuffle_bytes(self, seed: int, data: bytes, reverse=False) -> bytes:
        """Shuffle or unshuffle bytes deterministically based on seed."""
        if not reverse:
            data = bytearray(data)
            random.Random(seed).shuffle(data)
            return bytes(data)
        indexes = list(range(len(data)))
        random.Random(seed).shuffle(indexes)
        unshuffled_data = bytearray(c for _, c in sorted(zip(indexes, data)))
        return bytes(unshuffled_data)


    def _noise(self, seed: int, data: bytes) -> bytes:
        """XOR each byte with a pseudorandom byte generated from the seed."""
        random.seed(seed)
        noise = [random.randint(0, 255) for _ in range(len(data))]
        return bytes(data[i] ^ noise[i] for i in range(len(data)))


# Example usage:
if __name__ == "__main__":
    password = input("Enter password: ")
    pin = input("Enter PIN: ")
    sector_number = 123
    sector_data = os.urandom(16)  # Randomly generated sector data for testing
    sector_data = b"Hello, World!" + sector_data[13:]  # Replace the first 13 bytes with a known string
    print(f"Original sector: {sector_data[:64]}...")
    crypt = SectorCrypt(password, pin)
    #shuffle test
    shuffled_data = crypt._shuffle_bytes(sector_number, sector_data)
    unshuffled_data = crypt._shuffle_bytes(sector_number, shuffled_data, reverse=True)
    assert sector_data == unshuffled_data, "Shuffle failed!"
    print("Shuffle successful!")
    #noise test
    noisy_data = crypt._noise(sector_number, sector_data)
    unnoised_data = crypt._noise(sector_number, noisy_data)
    assert sector_data == unnoised_data, "Noise failed!"
    print("Noise successful!")
    #encryption test
    encrypted = crypt.encrypt_sector(sector_number, sector_data)
    crypt = SectorCrypt(password, pin)
    decrypted = crypt.decrypt_sector(sector_number, encrypted)
    assert decrypted == sector_data, "Decryption failed!"
    print(f"Decryption successful: {decrypted[:64]}...")