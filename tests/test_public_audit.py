"""Test leak detection without embedding actual credentials or personal data."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "public_audit", Path(__file__).resolve().parents[1] / "packaging/audit_public.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class PublicAuditTests(unittest.TestCase):
    def test_local_home_path_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Local home"):
            audit.check_data(str(Path.home()).encode())

    def test_standalone_credentials_are_rejected(self):
        for token in (b"AKIA" + b"A" * 16, b"ghp_" + b"a" * 36,
                      b"-----BEGIN " + b"PRIVATE KEY-----\n" + b"A" * 64):
            with self.subTest(kind=token[:4]):
                with self.assertRaisesRegex(ValueError, "credential"):
                    audit.check_data(token)

    def test_crypto_labels_and_alphabetic_tables_are_not_credentials(self):
        audit.check_data(b"-----BEGIN " + b"PRIVATE KEY-----")
        audit.check_data(b"PREFIX" + b"AKIA" + b"A" * 16 + b"SUFFIX")


if __name__ == "__main__":
    unittest.main()
