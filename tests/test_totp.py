import unittest

from app.tbc.security import (
    generate_recovery_codes,
    generate_totp_secret,
    hash_recovery_code,
    totp_code,
    totp_provisioning_uri,
    verify_totp,
)

# RFC 6238 Appendix B test vectors use the ASCII seed "12345678901234567890",
# which is GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ in base32. The published 8-digit
# SHA-1 codes truncate to these 6-digit values.
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


class TotpTests(unittest.TestCase):
    def test_rfc_6238_sha1_test_vectors(self):
        self.assertEqual(totp_code(RFC_SECRET, timestamp=59), "287082")
        self.assertEqual(totp_code(RFC_SECRET, timestamp=1111111109), "081804")
        self.assertEqual(totp_code(RFC_SECRET, timestamp=1234567890), "005924")

    def test_verify_accepts_current_code(self):
        self.assertTrue(verify_totp(RFC_SECRET, "287082", timestamp=59))

    def test_verify_accepts_adjacent_period_within_window(self):
        # Code for t=59 (counter 1) still accepted at t=61 (counter 2) with window=1.
        self.assertTrue(verify_totp(RFC_SECRET, "287082", timestamp=61, window=1))
        self.assertFalse(verify_totp(RFC_SECRET, "287082", timestamp=61, window=0))

    def test_verify_rejects_wrong_or_malformed_codes(self):
        self.assertFalse(verify_totp(RFC_SECRET, "000000", timestamp=59))
        self.assertFalse(verify_totp(RFC_SECRET, "28708", timestamp=59))
        self.assertFalse(verify_totp(RFC_SECRET, "abcdef", timestamp=59))
        self.assertFalse(verify_totp("", "287082", timestamp=59))

    def test_generated_secret_is_valid_base32_and_verifiable(self):
        secret = generate_totp_secret()
        code = totp_code(secret, timestamp=1000)
        self.assertTrue(verify_totp(secret, code, timestamp=1000))

    def test_provisioning_uri_contains_issuer_account_and_secret(self):
        uri = totp_provisioning_uri("ABC234", username="tony", issuer="TBC")
        self.assertTrue(uri.startswith("otpauth://totp/TBC%3Atony?"))
        self.assertIn("secret=ABC234", uri)
        self.assertIn("issuer=TBC", uri)

    def test_recovery_codes_are_unique_and_hash_ignores_case_and_spaces(self):
        codes = generate_recovery_codes()
        self.assertEqual(len(codes), 8)
        self.assertEqual(len(set(codes)), 8)
        self.assertEqual(hash_recovery_code(codes[0]), hash_recovery_code(f"  {codes[0].upper()}  "))


if __name__ == "__main__":
    unittest.main()
