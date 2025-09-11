# License: GPL 2
# Geodesics module for Earth coordinate calculations

import math
from dataclasses import dataclass

# Earth ellipsoid semi-axes in WGS84
EARTH_R_MAJOR_WGS84 = 6378137.0000
EARTH_R_MINOR_WGS84 = 6356752.3142
# Flattening of the Earth in WGS84
F_WGS84 = (EARTH_R_MAJOR_WGS84 - EARTH_R_MINOR_WGS84) / EARTH_R_MAJOR_WGS84

def local_earth_radius(lat, degrees=True):
    """Calculate local Earth radius in WGS84."""
    if degrees:
        lat = math.radians(lat)
    r1 = EARTH_R_MAJOR_WGS84
    r2 = EARTH_R_MINOR_WGS84
    return math.sqrt(((r1**2 * math.cos(lat))**2 + (r2**2 * math.sin(lat))**2) /
                     ((r1 * math.cos(lat))**2 + (r2 * math.sin(lat))**2))

def angular_distance(lon0, lat0, lon1, lat1, degrees=True, f=F_WGS84):
    """Calculate angular distance between two points on a flattened sphere."""
    if degrees:
        lon0, lat0, lon1, lat1 = map(math.radians, [lon0, lat0, lon1, lat1])
    gcarc, az, baz = inverse(lon0, lat0, lon1, lat1, 1.0, f)
    return math.degrees(gcarc) if degrees else gcarc

def azimuth(lon0, lat0, lon1, lat1, degrees=True, f=F_WGS84):
    """Calculate azimuth from one point to another on a flattened sphere."""
    lon0, lat0, lon1, lat1 = map(float, [lon0, lat0, lon1, lat1])
    if degrees:
        lon0, lat0, lon1, lat1 = map(math.radians, [lon0, lat0, lon1, lat1])
    gcarc, az, baz = inverse(lon0, lat0, lon1, lat1, 1.0, f)
    return math.degrees(az) if degrees else az

def angular_step(lon, lat, azimuth, distance, degrees=True, f=F_WGS84):
    """Calculate new coordinates after traveling along an azimuth."""
    if degrees:
        lon, lat, azimuth, distance = map(math.radians, [lon, lat, azimuth, distance])
    lon_prime, lat_prime, baz = forward(lon, lat, azimuth, distance, 1.0, f)
    if degrees:
        return math.degrees(lon_prime), math.degrees(lat_prime), math.degrees(baz)
    return lon_prime, lat_prime, baz

def surface_distance(lon0, lat0, lon1, lat1, a, degrees=True, f=F_WGS84):
    """Calculate physical distance between two points on a flattened sphere."""
    if degrees:
        lon0, lat0, lon1, lat1 = map(math.radians, [lon0, lat0, lon1, lat1])
    distance, az, baz = inverse(lon0, lat0, lon1, lat1, a, f)
    return distance

def forward(lon, lat, azimuth, distance, a, f):
    """Calculate forward position using Vincenty's formula."""
    if abs(lat) > math.pi / 2:
        raise ValueError(f"Latitude ({lat}) must be in range [-π/2, π/2]")
    if a <= 0:
        raise ValueError(f"Semimajor axis ({a}) must be positive")
    if abs(f) >= 1:
        raise ValueError(f"Magnitude of flattening ({f}) must be less than 1")

    lambda1, phi1, alpha12, s = map(float, [lon, lat, azimuth, distance])
    alpha12 = alpha12 % (2 * math.pi)
    b = a * (1 - f)

    TanU1 = (1 - f) * math.tan(phi1)
    U1 = math.atan(TanU1)
    sigma1 = math.atan2(TanU1, math.cos(alpha12))
    Sinalpha = math.cos(U1) * math.sin(alpha12)
    cosalpha_sq = 1.0 - Sinalpha * Sinalpha

    u2 = cosalpha_sq * (a * a - b * b) / (b * b)
    A = 1.0 + (u2 / 16384) * (4096 + u2 * (-768 + u2 * (320 - 175 * u2)))
    B = (u2 / 1024) * (256 + u2 * (-128 + u2 * (74 - 47 * u2)))

    sigma = s / (b * A)
    if sigma == 0:
        return lambda1, phi1, (alpha12 + math.pi) % (2 * math.pi)

    last_sigma = 2 * sigma + 2
    while abs((last_sigma - sigma) / sigma) > 1.0e-9:
        two_sigma_m = 2 * sigma1 + sigma
        delta_sigma = B * math.sin(sigma) * (
            math.cos(two_sigma_m) + (B / 4) * (
                math.cos(sigma) * (-1 + 2 * math.cos(two_sigma_m)**2) -
                (B / 6) * math.cos(two_sigma_m) * (-3 + 4 * math.sin(sigma)**2) * (-3 + 4 * math.cos(two_sigma_m)**2)
            )
        )
        last_sigma = sigma
        sigma = (s / (b * A)) + delta_sigma

    phi2 = math.atan2(
        (math.sin(U1) * math.cos(sigma) + math.cos(U1) * math.sin(sigma) * math.cos(alpha12)),
        ((1 - f) * math.sqrt(Sinalpha**2 + (math.sin(U1) * math.sin(sigma) - math.cos(U1) * math.cos(sigma) * math.cos(alpha12))**2))
    )

    lambda_ = math.atan2(
        (math.sin(sigma) * math.sin(alpha12)),
        (math.cos(U1) * math.cos(sigma) - math.sin(U1) * math.sin(sigma) * math.cos(alpha12))
    )

    C = (f / 16) * cosalpha_sq * (4 + f * (4 - 3 * cosalpha_sq))
    omega = lambda_ - (1 - C) * f * Sinalpha * (
        sigma + C * math.sin(sigma) * (
            math.cos(two_sigma_m) + C * math.cos(sigma) * (-1 + 2 * math.cos(two_sigma_m)**2)
        )
    )

    lambda2 = lambda1 + omega
    alpha21 = math.atan2(
        Sinalpha,
        (-math.sin(U1) * math.sin(sigma) + math.cos(U1) * math.cos(sigma) * math.cos(alpha12))
    )
    alpha21 = (alpha21 + math.pi) % (2 * math.pi)

    return lambda2, phi2, alpha21

def inverse(lon1, lat1, lon2, lat2, a, f):
    """Calculate distance and angles using Vincenty's inverse formula."""
    for lat in (lat1, lat2):
        if abs(lat) > math.pi / 2:
            raise ValueError(f"Latitude ({lat}) must be in range [-π/2, π/2]")
    if a <= 0:
        raise ValueError(f"Semimajor axis ({a}) must be positive")
    if abs(f) >= 1:
        raise ValueError(f"Magnitude of flattening ({f}) must be less than 1")

    lambda1, phi1, lambda2, phi2 = map(float, [lon1, lat1, lon2, lat2])
    tol = 1.0e-8
    if abs(phi2 - phi1) < tol and abs(lambda2 - lambda1) < tol:
        return 0.0, 0.0, 0.0

    b = a * (1 - f)
    TanU1 = (1 - f) * math.tan(phi1)
    TanU2 = (1 - f) * math.tan(phi2)
    U1 = math.atan(TanU1)
    U2 = math.atan(TanU2)
    lambda_ = lambda2 - lambda1
    last_lambda = -4000000.0
    omega = lambda_

    alpha, sigma, Sin_sigma, Cos2sigma_m, Cos_sigma, sqr_sin_sigma = (
        -999999., -999999., -999999., -999999., -999999., -999999.
    )

    while (last_lambda < -3000000.0 or lambda_ != 0) and abs((last_lambda - lambda_) / lambda_) > 1.0e-9:
        sqr_sin_sigma = (math.cos(U2) * math.sin(lambda_))**2 + (
            (math.cos(U1) * math.sin(U2) - math.sin(U1) * math.cos(U2) * math.cos(lambda_))**2
        )
        Sin_sigma = math.sqrt(sqr_sin_sigma)
        Cos_sigma = math.sin(U1) * math.sin(U2) + math.cos(U1) * math.cos(U2) * math.cos(lambda_)
        sigma = math.atan2(Sin_sigma, Cos_sigma)
        Sin_alpha = math.cos(U1) * math.cos(U2) * math.sin(lambda_) / math.sin(sigma)
        Sin_alpha = min(1.0, max(-1.0, Sin_alpha))
        alpha = math.asin(Sin_alpha)
        Cos2sigma_m = math.cos(sigma) - 2 * math.sin(U1) * math.sin(U2) / math.cos(alpha)**2
        C = (f / 16) * math.cos(alpha)**2 * (4 + f * (4 - 3 * math.cos(alpha)**2))
        last_lambda = lambda_
        lambda_ = omega + (1 - C) * f * math.sin(alpha) * (
            sigma + C * math.sin(sigma) * (
                Cos2sigma_m + C * math.cos(sigma) * (-1 + 2 * Cos2sigma_m**2)
            )
        )

    u2 = math.cos(alpha)**2 * (a * a - b * b) / (b * b)
    A = 1 + (u2 / 16384) * (4096 + u2 * (-768 + u2 * (320 - 175 * u2)))
    B = (u2 / 1024) * (256 + u2 * (-128 + u2 * (74 - 47 * u2)))
    delta_sigma = B * Sin_sigma * (
        Cos2sigma_m + (B / 4) * (
            Cos_sigma * (-1 + 2 * Cos2sigma_m**2) -
            (B / 6) * Cos2sigma_m * (-3 + 4 * sqr_sin_sigma) * (-3 + 4 * Cos2sigma_m**2)
        )
    )
    s = b * A * (sigma - delta_sigma)
    alpha12 = math.atan2(
        (math.cos(U2) * math.sin(lambda_)),
        (math.cos(U1) * math.sin(U2) - math.sin(U1) * math.cos(U2) * math.cos(lambda_))
    )
    alpha21 = math.atan2(
        (math.cos(U1) * math.sin(lambda_)),
        (-math.sin(U1) * math.cos(U2) + math.cos(U1) * math.sin(U2) * math.cos(lambda_))
    )
    alpha12 = alpha12 % (2 * math.pi)
    alpha21 = (alpha21 + math.pi) % (2 * math.pi)
    return s, alpha12, alpha21