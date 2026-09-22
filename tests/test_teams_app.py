import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
APP_ID = "11111111-2222-4333-8444-555555555555"


class TeamsAppPackageTests(unittest.TestCase):
    def test_rsc_package_contains_scoped_permissions_and_valid_icons(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "app.zip"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_teams_app.py"),
                    "--app-id",
                    APP_ID,
                    "--public-url",
                    "https://seminar.example.ac.kr",
                    "--output",
                    str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            with zipfile.ZipFile(output) as package:
                self.assertEqual(set(package.namelist()), {"manifest.json", "color.png", "outline.png"})
                manifest = json.loads(package.read("manifest.json"))
                permissions = {
                    item["name"] for item in manifest["authorization"]["permissions"]["resourceSpecific"]
                }
                self.assertEqual(permissions, {"ChannelMessage.Read.Group"})
                self.assertEqual(manifest["webApplicationInfo"]["id"], APP_ID)
                self.assertEqual(manifest["validDomains"], ["seminar.example.ac.kr"])
        with Image.open(ROOT / "teams-app" / "color.png") as color:
            self.assertEqual(color.size, (192, 192))
        with Image.open(ROOT / "teams-app" / "outline.png") as outline:
            self.assertEqual(outline.size, (32, 32))
            self.assertEqual(outline.mode, "RGBA")


if __name__ == "__main__":
    unittest.main()
