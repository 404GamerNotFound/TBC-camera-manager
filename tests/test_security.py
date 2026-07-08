import unittest

from app.tbc.security import hash_password, verify_password


class SecurityTests(unittest.TestCase):
    def test_password_hash_verification(self):
        stored = hash_password("secret")
        self.assertTrue(verify_password("secret", stored))
        self.assertFalse(verify_password("wrong", stored))

    def test_password_hashes_are_salted(self):
        first = hash_password("secret")
        second = hash_password("secret")
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()

