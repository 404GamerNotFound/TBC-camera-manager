import unittest

from app.tbc.security import (
    SecretDecryptionError,
    decrypt_bytes,
    decrypt_secret,
    encrypt_bytes,
    encrypt_secret,
    hash_password,
    is_encrypted_secret,
    verify_password,
)


class SecurityTests(unittest.TestCase):
    def test_password_hash_verification(self):
        stored = hash_password("secret")
        self.assertTrue(verify_password("secret", stored))
        self.assertFalse(verify_password("wrong", stored))

    def test_password_hashes_are_salted(self):
        first = hash_password("secret")
        second = hash_password("secret")
        self.assertNotEqual(first, second)


class SecretEncryptionTests(unittest.TestCase):
    def test_encrypt_then_decrypt_round_trip(self):
        encrypted = encrypt_secret("my-secret-key", "hunter2")
        self.assertTrue(is_encrypted_secret(encrypted))
        self.assertNotIn("hunter2", encrypted)
        self.assertEqual(decrypt_secret("my-secret-key", encrypted), "hunter2")

    def test_empty_and_none_values_pass_through_unchanged(self):
        self.assertEqual(encrypt_secret("key", ""), "")
        self.assertIsNone(encrypt_secret("key", None))
        self.assertEqual(decrypt_secret("key", ""), "")
        self.assertIsNone(decrypt_secret("key", None))

    def test_legacy_plaintext_values_pass_through_unchanged(self):
        # Values stored before encryption was introduced have no marker
        # prefix and must keep working until re-encrypted in place.
        self.assertEqual(decrypt_secret("my-secret-key", "plain-old-password"), "plain-old-password")
        self.assertFalse(is_encrypted_secret("plain-old-password"))

    def test_decrypting_with_wrong_key_raises(self):
        encrypted = encrypt_secret("key-a", "hunter2")
        with self.assertRaises(SecretDecryptionError):
            decrypt_secret("key-b", encrypted)

    def test_encrypted_values_differ_from_plaintext(self):
        encrypted = encrypt_secret("key", "hunter2")
        self.assertNotEqual(encrypted, "hunter2")
        self.assertTrue(encrypted.startswith("enc:v1:"))


class BinarySecretEncryptionTests(unittest.TestCase):
    def test_bytes_round_trip(self):
        data = b"some binary backup archive bytes"
        encrypted = encrypt_bytes("key", data)
        self.assertNotEqual(encrypted, data)
        self.assertEqual(decrypt_bytes("key", encrypted), data)

    def test_wrong_key_raises(self):
        encrypted = encrypt_bytes("key-a", b"payload")
        with self.assertRaises(SecretDecryptionError):
            decrypt_bytes("key-b", encrypted)


if __name__ == "__main__":
    unittest.main()

