from pathlib import Path
import sys
import tempfile
import unittest


DEPLOY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DEPLOY))

from patch_hosting_config import patch_caddyfile, patch_inventory  # noqa: E402


class HostingPatchTest(unittest.TestCase):
    def test_caddy_patch_preserves_existing_sites_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Caddyfile"
            path.write_text("existing.example {\n\trespond 200\n}\n", encoding="utf-8")

            self.assertTrue(patch_caddyfile(path))
            once = path.read_text(encoding="utf-8")
            self.assertIn("existing.example", once)
            self.assertEqual(once.count("benchmark.lan.awesomeio.ru {"), 1)
            self.assertFalse(patch_caddyfile(path))
            self.assertEqual(path.read_text(encoding="utf-8"), once)

    def test_caddy_patch_rejects_an_existing_conflicting_site(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Caddyfile"
            path.write_text("benchmark.lan.awesomeio.ru {\n\trespond 200\n}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "conflicts"):
                patch_caddyfile(path)

    def test_inventory_patch_preserves_entries_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inventory.json"
            path.write_text('{"schema_version":1,"nodes":[],"services":[]}', encoding="utf-8")

            self.assertTrue(patch_inventory(path))
            once = path.read_text(encoding="utf-8")
            self.assertIn("benchmark.lan.awesomeio.ru", once)
            self.assertFalse(patch_inventory(path))
            self.assertEqual(path.read_text(encoding="utf-8"), once)

    def test_inventory_patch_rejects_a_conflicting_service_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inventory.json"
            path.write_text(
                '{"schema_version":1,"nodes":[],"services":[{"name":"benchmark.lan.awesomeio.ru","label":"Other"}]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "conflicts"):
                patch_inventory(path)


if __name__ == "__main__":
    unittest.main()
