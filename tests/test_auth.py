"""
test_auth.py
===========
Pruebas básicas de autenticación y configuración.
NO descargan datos.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_config_loads():
    from src.config import load_config, PROJECT_ROOT
    cfg = load_config()
    assert cfg is not None
    assert cfg.test_mode is True or cfg.test_mode is False
    assert len(cfg.sentinel.bands) == 12
    assert "B10" not in cfg.sentinel.bands, "B10 NO debe estar en L2A bands"
    assert cfg.temporal.months == 12
    assert cfg.sentinel.resolution == 10
    assert PROJECT_ROOT.exists()


def test_sh_credentials_present():
    from src.config import get_sh_credentials
    cid, csec = get_sh_credentials()
    assert cid is not None and len(cid) > 0
    assert csec is not None and len(csec) > 0
    assert cid != "tu-client-id-aqui", "SH_CLIENT_ID debe configurarse en .env"
    assert csec != "tu-client-secret-aqui", "SH_CLIENT_SECRET debe configurarse en .env"


def test_auth_manager_initialises():
    from src.auth import CopernicusAuth, get_auth, reset_auth
    reset_auth()
    auth = get_auth()
    assert isinstance(auth, CopernicusAuth)


def test_auth_get_sh_config():
    from src.auth import get_auth, reset_auth
    reset_auth()
    auth = get_auth()
    shcfg = auth.get_sh_config()
    assert shcfg is not None
    assert shcfg.sh_client_id is not None
    assert shcfg.sh_base_url is not None


def test_sentinel_bands_no_b10():
    from src.config import load_config
    cfg = load_config()
    for b in cfg.sentinel.bands:
        assert b.startswith("B"), f"banda no válida: {b}"
    assert cfg.sentinel.bands == [
        "B01","B02","B03","B04","B05","B06",
        "B07","B08","B8A","B09","B11","B12",
    ]


if __name__ == "__main__":
    import traceback
    tests = [
        test_config_loads,
        test_sh_credentials_present,
        test_auth_manager_initialises,
        test_auth_get_sh_config,
        test_sentinel_bands_no_b10,
    ]
    passed = 0
    for t in tests:
        name = t.__name__
        try:
            t()
            print(f"[OK]  {name}")
            passed += 1
        except Exception as e:
            print(f"[ERR] {name}: {e}")
            traceback.print_exc()
    print(f"\n{passed}/{len(tests)} tests pasados.")
    sys.exit(0 if passed == len(tests) else 1)
