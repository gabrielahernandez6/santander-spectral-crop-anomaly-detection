"""Pruebas del algoritmo portado (sin modelos): índices, parches, máscaras, regiones y persistencia."""
import numpy as np
import pytest
from rasterio.transform import from_origin

from app import pipeline as pl

BANDAS = ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"]


def _bandas(H=12, W=10, **valores):
    x = np.full((len(BANDAS), H, W), 0.1, np.float32)
    for b, v in valores.items():
        x[BANDAS.index(b)] = v
    return x


def test_indices_formulas_del_notebook():
    x = _bandas(B08=0.4, B04=0.05, B03=0.08, B05=0.15, B11=0.2)
    ind = pl.calcular_indices(x, BANDAS)
    np.testing.assert_allclose(ind[:, 0, 0], [(0.4 - 0.05) / 0.45, (0.4 - 0.08) / 0.48, (0.4 - 0.15) / 0.55,
                                              (0.4 - 0.2) / 0.6], rtol=1e-6)


def test_indices_division_por_cero_da_cero():
    x = _bandas(B08=0.0, B04=0.0)
    assert pl.calcular_indices(x, BANDAS)[0, 0, 0] == 0.0


def test_recortar_centra_el_parche_y_refleja_bordes():
    H, W, P = 7, 6, 5
    r = P // 2
    x = np.arange(len(BANDAS) * H * W, dtype=np.float32).reshape(len(BANDAS), H, W)
    xpad = np.pad(x, ((0, 0), (r, r), (r, r)), mode="reflect")
    i, j = np.array([0, 3, 6]), np.array([0, 2, 5])
    parches = pl.recortar(xpad, i, j, P)
    assert parches.shape == (3, len(BANDAS), P, P)
    np.testing.assert_array_equal(parches[:, :, r, r], x[:, i, j].T)
    # Reflexión sin repetir el borde (igual que F.pad(mode="reflect") de PyTorch): fila -1 = fila 1
    np.testing.assert_array_equal(parches[0, :, r - 1, r], x[:, 1, 0])


def test_preparar_escena_rellena_invalidos_con_la_mediana():
    x = _bandas()
    x[BANDAS.index("B08")] = np.linspace(0.2, 0.5, x.shape[1] * x.shape[2]).reshape(x.shape[1:])
    valido = np.ones(x.shape[1:], bool)
    valido[0, 0] = False
    x[:, 0, 0] = np.nan
    e = pl.preparar_escena(x, valido, BANDAS, "2025-01-01")
    assert e.bandas.dtype == np.float16 and e.indices.dtype == np.float16
    assert np.isfinite(e.bandas).all()
    esperado = np.median(x[BANDAS.index("B08")][valido])
    assert abs(float(e.bandas[BANDAS.index("B08"), 0, 0]) - esperado) < 1e-3


def test_preparar_escena_sin_validos_falla():
    with pytest.raises(pl.ErrorEscena):
        pl.preparar_escena(_bandas(), np.zeros((12, 10), bool), BANDAS, "2025-01-01")


def test_mascaras_palma_de_referencia_y_no_dosel():
    T, H, W = 6, 4, 4
    valido = np.ones((T, H, W), bool)
    palma_t = np.zeros((T, H, W), bool)
    palma_t[:3, 0, 0] = True           # 3 de 6 fechas >= 0.34 * 6 -> palma de referencia
    palma_t[:2, 0, 1] = True           # 2 de 6 < 2.04 -> no
    ndvi = np.full((T, H, W), 0.8, np.float32)
    ndvi[:5, 1, 1] = 0.2               # 5 de 6 fechas con NDVI bajo (>= 80 %) -> no-dosel
    cfg = dict(frac_fechas_palma=0.34, ndvi_no_dosel=0.40, frac_no_dosel=0.80, min_fechas_temporal=3)
    palma_ref, no_dosel = pl.mascaras_ubicacion(palma_t, valido, ndvi, cfg)
    assert palma_ref[0, 0] and not palma_ref[0, 1]
    assert no_dosel[1, 1] and no_dosel.sum() == 1


def test_evaluable_excluye_halo_de_nube():
    H, W = 9, 9
    palma = np.ones((H, W), bool)
    valido = np.ones((H, W), bool)
    valido[4, 4] = False
    ev = pl.evaluable(palma, np.zeros((H, W), bool), valido, buffer_px=2)
    assert not ev[2:7, 2:7].any() and ev[1, 1] and ev[7, 7]


def test_persistencia():
    p = pl.persistencia(np.array([[2, 0], [0, 1]]), np.array([[4, 0], [3, 1]]))
    assert p[0, 0] == 0.5 and np.isnan(p[0, 1]) and p[1, 0] == 0 and p[1, 1] == 1


def test_regiones_un_bloque_de_consenso():
    H, W = 30, 30
    x = _bandas(H, W, B08=0.4, B04=0.04)
    x *= np.random.default_rng(0).uniform(0.97, 1.03, x.shape).astype(np.float32)   # variación natural
    x[BANDAS.index("B04"), 10:14, 10:15] = 0.12          # región con más rojo -> cae el NDVI, no el resto          # región con menos NIR -> cae el NDVI
    e = pl.preparar_escena(x, np.ones((H, W), bool), BANDAS, "2025-03-01")
    capas = np.zeros((7, H, W), np.uint8)
    capas[-1, 10:14, 10:15] = 5
    capas[-1, 0, 0] = 255
    capas[-1, 25, 25] = 6                                # 1 píxel: menor que el área mínima
    transform = from_origin(-73.5, 7.0, 0.0001, 0.0001)
    pers = np.full((H, W), 0.5, np.float32)
    regiones, lab = pl.regiones_escena(capas, e, pers, transform, 0.01, 4, 5, BANDAS)
    assert len(regiones) == 1
    r = regiones[0]
    assert r["px"] == 20 and r["ha"] == 0.2 and r["votos_medios"] == 5
    assert r["z_NDVI"] < -1 and r["caida_principal"].startswith("NDVI")
    assert r["firma"]["B04"] > r["firma_normal"]["B04"]
    assert r["_geometria"]["type"] == "Polygon"
    assert (lab > 0).sum() == 20
