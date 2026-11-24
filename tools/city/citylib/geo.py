"""WGS84 lon/lat -> local metres for the Cityhub world.

Projection: a local Transverse Mercator (TM) on the WGS84 ellipsoid, centred on the world origin
(central meridian = origin longitude, latitude of origin = origin latitude, scale factor k0 = 1,
no false easting or northing). So the origin maps to (0, 0), +x is grid east and +y is grid north,
and 1 unit = 1 m with a scale error under 1 ppm within 10 km of the origin (k = 1 + x^2 / 2R^2),
which is far below what a game can show. Unlike UTM (zone 44N, k0 = 0.9996), distances are true
at the origin, and unlike an equirectangular approximation the map stays conformal city-wide.

The maths is Krueger's series to sixth order in n, as given by C. F. F. Karney, "Transverse
Mercator with an accuracy of a few nanometers", J. Geodesy 85 (2011), eqs. 7-11 and 35-36.

World axes (AGENTS.md rule 5): Unity +X = east = TM x, Unity +Z = north = TM y, Unity +Y = up.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# WGS84
WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563

# The Cityhub world origin: Unity world (0, 0, 0). A fixed point on Delta Face Green chosen on
# 2026-11-15 (TDD "Open-world streaming" > Rules). Never change it once cells are shipped: every
# cell id and Addressable key depends on it. Height: Unity Y = metres above mean sea level.
CITYHUB_ORIGIN_LAT = 6.92250
CITYHUB_ORIGIN_LON = 79.84550


@dataclass(frozen=True)
class TransverseMercator:
    lat0: float
    lon0: float
    k0: float = 1.0
    a: float = WGS84_A
    f: float = WGS84_F

    def __post_init__(self) -> None:
        n = self.f / (2.0 - self.f)
        e2 = self.f * (2.0 - self.f)
        object.__setattr__(self, "_e", math.sqrt(e2))
        object.__setattr__(self, "_e2", e2)
        n2, n3, n4, n5, n6 = n**2, n**3, n**4, n**5, n**6
        object.__setattr__(self, "_A", self.a / (1.0 + n) * (1.0 + n2 / 4.0 + n4 / 64.0 + n6 / 256.0))
        object.__setattr__(self, "_alpha", (
            n / 2 - 2 * n2 / 3 + 5 * n3 / 16 + 41 * n4 / 180 - 127 * n5 / 288 + 7891 * n6 / 37800,
            13 * n2 / 48 - 3 * n3 / 5 + 557 * n4 / 1440 + 281 * n5 / 630 - 1983433 * n6 / 1935360,
            61 * n3 / 240 - 103 * n4 / 140 + 15061 * n5 / 26880 + 167603 * n6 / 181440,
            49561 * n4 / 161280 - 179 * n5 / 168 + 6601661 * n6 / 7257600,
            34729 * n5 / 80640 - 3418889 * n6 / 1995840,
            212378941 * n6 / 319334400,
        ))
        object.__setattr__(self, "_beta", (
            n / 2 - 2 * n2 / 3 + 37 * n3 / 96 - n4 / 360 - 81 * n5 / 512 + 96199 * n6 / 604800,
            n2 / 48 + n3 / 15 - 437 * n4 / 1440 + 46 * n5 / 105 - 1118711 * n6 / 3870720,
            17 * n3 / 480 - 37 * n4 / 840 - 209 * n5 / 4480 + 5569 * n6 / 90720,
            4397 * n4 / 161280 - 11 * n5 / 504 - 830251 * n6 / 7257600,
            4583 * n5 / 161280 - 108847 * n6 / 3991680,
            20648693 * n6 / 638668800,
        ))
        object.__setattr__(self, "_y0", 0.0)
        object.__setattr__(self, "_y0", self._raw(self.lat0, self.lon0)[1])

    # -- forward ---------------------------------------------------------------------------
    def _raw(self, lat: float, lon: float) -> tuple[float, float]:
        phi = math.radians(lat)
        lam = math.radians(lon - self.lon0)
        e = self._e
        tau = math.tan(phi)
        sigma = math.sinh(e * math.atanh(e * tau / math.sqrt(1 + tau * tau)))
        tau_p = tau * math.sqrt(1 + sigma * sigma) - sigma * math.sqrt(1 + tau * tau)
        xi_p = math.atan2(tau_p, math.cos(lam))
        eta_p = math.asinh(math.sin(lam) / math.sqrt(tau_p * tau_p + math.cos(lam) ** 2))
        xi, eta = xi_p, eta_p
        for j, al in enumerate(self._alpha, start=1):
            xi += al * math.sin(2 * j * xi_p) * math.cosh(2 * j * eta_p)
            eta += al * math.cos(2 * j * xi_p) * math.sinh(2 * j * eta_p)
        return self.k0 * self._A * eta, self.k0 * self._A * xi - self._y0

    def forward(self, lat: float, lon: float) -> tuple[float, float]:
        """(lat, lon) degrees -> (x east, y north) metres from the origin."""
        return self._raw(lat, lon)

    # -- inverse ---------------------------------------------------------------------------
    def inverse(self, x: float, y: float) -> tuple[float, float]:
        """(x east, y north) metres -> (lat, lon) degrees."""
        xi = (y + self._y0) / (self.k0 * self._A)
        eta = x / (self.k0 * self._A)
        xi_p, eta_p = xi, eta
        for j, be in enumerate(self._beta, start=1):
            xi_p -= be * math.sin(2 * j * xi) * math.cosh(2 * j * eta)
            eta_p -= be * math.cos(2 * j * xi) * math.sinh(2 * j * eta)
        tau_p = math.sin(xi_p) / math.sqrt(math.sinh(eta_p) ** 2 + math.cos(xi_p) ** 2)
        lam = math.atan2(math.sinh(eta_p), math.cos(xi_p))
        e, e2 = self._e, self._e2
        tau = tau_p
        for _ in range(8):  # Newton on tau'(tau) = target (Karney eqs. 19-21)
            sigma = math.sinh(e * math.atanh(e * tau / math.sqrt(1 + tau * tau)))
            tp = tau * math.sqrt(1 + sigma * sigma) - sigma * math.sqrt(1 + tau * tau)
            dtau = (tau_p - tp) / (1 + tp * tp) ** 0.5 * (1 + (1 - e2) * tau * tau) / (
                (1 - e2) * math.sqrt(1 + tau * tau))
            tau += dtau
            if abs(dtau) < 1e-14:
                break
        return math.degrees(math.atan(tau)), self.lon0 + math.degrees(lam)


CITYHUB = TransverseMercator(CITYHUB_ORIGIN_LAT, CITYHUB_ORIGIN_LON)


def project(lat: float, lon: float, tm: TransverseMercator = CITYHUB) -> tuple[float, float]:
    """(lat, lon) -> (east, north) metres in the Cityhub world frame."""
    return tm.forward(lat, lon)
