from pathlib import Path


def test_project_structure_exists():
    assert Path("src/agents").exists()
    assert Path("src/tools").exists()
    assert Path("src/workflows").exists()
    assert Path("src/config").exists()
    assert Path("requirements.txt").exists()
