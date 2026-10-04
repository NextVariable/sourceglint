"""Bundle canonical repository resources without maintaining duplicate copies."""
from pathlib import Path
from shutil import copytree, copy2

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildWithResources(build_py):
    def run(self):
        super().run()
        root = Path(__file__).resolve().parent
        destination = Path(self.build_lib) / "sourceglint" / "_data"
        for name in ("config", "schemas"):
            copytree(root / name, destination / name, dirs_exist_ok=True)
        (destination / "docs").mkdir(exist_ok=True)
        copy2(root / "docs" / "source-live-status.json", destination / "docs" / "source-live-status.json")


setup(cmdclass={"build_py": BuildWithResources})
