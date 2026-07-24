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
        # Ingress gives TBC a Home Assistant sidebar entry and lets "Open Web
        # UI" work through Supervisor's own proxy instead of a direct
        # container-port connection - see app/tbc/ingress.py.
        self.assertTrue(config["ingress"])
        self.assertEqual(config["ingress_port"], 8732)
        self.assertIn("panel_icon", config)
        self.assertNotIn("webui", config)
        self.assertNotIn("boot", config)
        self.assertNotIn("startup", config)
        dockerfile = (ROOT / "tbc_camera_manager" / "Dockerfile").read_text(
            encoding="utf-8"
        )
        self.assertIn(f"ARG BUILD_VERSION={config['version']}", dockerfile)

        root_dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY app ./app", root_dockerfile)
        self.assertIn("COPY docs ./docs", root_dockerfile)

    def test_release_workflow_links_and_publicly_verifies_the_image(self):
        workflow = (ROOT / ".github" / "workflows" / "home-assistant-app.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "org.opencontainers.image.source=${{ github.server_url }}/${{ github.repository }}",
            workflow,
        )
        self.assertIn("fromJSON(steps.info.outputs.version)", workflow)
        self.assertIn("fromJSON(steps.info.outputs.image)", workflow)
        self.assertIn("docker logout ghcr.io", workflow)
        self.assertIn('docker pull "${IMAGE}:${VERSION}"', workflow)
        self.assertIn("change its visibility to Public", workflow)
        self.assertIn("branches:\n      - main", workflow)
        self.assertIn('paths:\n      - "tbc_camera_manager/config.yaml"', workflow)
        self.assertIn("if: startsWith(github.ref, 'refs/tags/')", workflow)


class HomeAssistantCoralAppPackageTests(unittest.TestCase):
    """Coral gets its own installable Home Assistant app (see
    tbc_camera_manager_coral/) rather than being folded into the standard app,
    since it needs extra system/Python packages (Dockerfile.coral) and only
    targets amd64 - Coral accelerator hardware."""

    def test_app_manifest_is_consistent(self):
        config = yaml.safe_load(
            (ROOT / "tbc_camera_manager_coral" / "config.yaml").read_text(encoding="utf-8")
        )

        self.assertEqual(config["version"], __version__)
        self.assertEqual(config["slug"], "tbc_camera_manager_coral")
        self.assertEqual(set(config["arch"]), {"amd64"})
        self.assertEqual(config["image"], "ghcr.io/404gamernotfound/tbc-camera-manager-ha-coral")
        self.assertEqual(config["ports"]["8732/tcp"], 8732)
        self.assertIsNone(config["options"]["admin_password"])
        self.assertTrue(config["usb"])
        self.assertTrue(config["ingress"])
        self.assertEqual(config["ingress_port"], 8732)
        self.assertNotIn("webui", config)
        self.assertNotIn("boot", config)
        self.assertNotIn("startup", config)

        dockerfile = (ROOT / "tbc_camera_manager_coral" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn(f"ARG BUILD_VERSION={config['version']}", dockerfile)

        root_dockerfile = (ROOT / "Dockerfile.coral").read_text(encoding="utf-8")
        self.assertIn("COPY app ./app", root_dockerfile)
        self.assertIn("ai-edge-litert", root_dockerfile)
        # pycoral/tflite-runtime never shipped a Linux wheel past Python 3.9 -
        # incompatible with this project's other pinned dependencies. Guards
        # against silently reintroducing either package as an actual install
        # target (mentions in comments explaining why they're avoided are fine).
        install_lines = [
            line for line in root_dockerfile.splitlines()
            if "pip install" in line and not line.strip().startswith("#")
        ]
        for line in install_lines:
            self.assertNotIn("pycoral", line)
            self.assertNotIn("tflite-runtime", line)
        # container_launcher.py is what reads /data/options.json and maps it to
        # TBC_* env vars - without it, this app would silently ignore every
        # Supervisor option (admin_password included). See Dockerfile.coral's
        # comment on why this replaced its original standalone-only CMD.
        self.assertIn("container_launcher.py", root_dockerfile)

    def test_release_workflow_links_and_publicly_verifies_the_image(self):
        workflow = (ROOT / ".github" / "workflows" / "home-assistant-app-coral.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "org.opencontainers.image.source=${{ github.server_url }}/${{ github.repository }}",
            workflow,
        )
        self.assertIn("fromJSON(steps.info.outputs.version)", workflow)
        self.assertIn("fromJSON(steps.info.outputs.image)", workflow)
        self.assertIn("docker logout ghcr.io", workflow)
        self.assertIn('docker pull "${IMAGE}:${VERSION}"', workflow)
        self.assertIn("change its visibility to Public", workflow)
        self.assertIn("branches:\n      - main", workflow)
        self.assertIn('paths:\n      - "tbc_camera_manager_coral/config.yaml"', workflow)
        self.assertIn("if: startsWith(github.ref, 'refs/tags/')", workflow)
        # The only real difference from the standard app's workflow: it must
        # build from Dockerfile.coral, not the default Dockerfile the
        # build-image action would otherwise assume.
        self.assertIn("file: ./Dockerfile.coral", workflow)


if __name__ == "__main__":
    unittest.main()
