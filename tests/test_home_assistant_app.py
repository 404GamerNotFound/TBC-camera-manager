import unittest
from pathlib import Path

import yaml

from app.tbc import __version__


ROOT = Path(__file__).resolve().parents[1]


class HomeAssistantAppPackageTests(unittest.TestCase):
    def test_repository_and_app_manifests_are_consistent(self):
        repository = yaml.safe_load((ROOT / "repository.yaml").read_text(encoding="utf-8"))
        config = yaml.safe_load(
            (ROOT / "tbc_camera_manager" / "config.yaml").read_text(encoding="utf-8")
        )

        self.assertEqual(repository["url"], config["url"])
        self.assertEqual(config["version"], __version__)
        self.assertEqual(config["slug"], "tbc_camera_manager")
        self.assertEqual(set(config["arch"]), {"amd64", "aarch64"})
        self.assertEqual(config["image"], "ghcr.io/404gamernotfound/tbc-camera-manager-ha")
        self.assertEqual(config["ports"]["8732/tcp"], 8732)
        self.assertIsNone(config["options"]["admin_password"])
        self.assertNotIn("boot", config)
        self.assertNotIn("startup", config)

    def test_release_workflow_links_and_publicly_verifies_the_image(self):
        workflow = (ROOT / ".github" / "workflows" / "home-assistant-app.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "org.opencontainers.image.source=${{ github.server_url }}/${{ github.repository }}",
            workflow,
        )
        self.assertIn("docker logout ghcr.io", workflow)
        self.assertIn('docker pull "${IMAGE}:${VERSION}"', workflow)
        self.assertIn("change its visibility to Public", workflow)


if __name__ == "__main__":
    unittest.main()
