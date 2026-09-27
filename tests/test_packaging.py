"""Published wheels must carry the same contracts and UI as the checkout."""
import subprocess
import sys
import zipfile
from pathlib import Path


def test_wheel_contains_canonical_schemas_and_frontend(tmp_path):
    root = Path(__file__).resolve().parents[1]
    canonical = {p.name: p.read_bytes() for p in (root / "contracts").glob("*.json")}
    packaged = {p.name: p.read_bytes() for p in (root / "src/bobthereviewer/schemas").glob("*.json")}
    assert canonical == packaged
    built = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(tmp_path)],
        cwd=root, capture_output=True, text=True, timeout=120,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    with zipfile.ZipFile(next(tmp_path.glob("bobthereviewer-*.whl"))) as wheel:
        assert "bobthereviewer/frontend/index.html" in wheel.namelist()
        assert any(name.startswith("bobthereviewer/frontend/assets/") for name in wheel.namelist())
        assert "bobthereviewer/templates/custom_modes.yaml" in wheel.namelist()
        assert "bobthereviewer/templates/bobreviewer.yml" in wheel.namelist()
        for name, data in canonical.items():
            assert wheel.read(f"bobthereviewer/schemas/{name}") == data
