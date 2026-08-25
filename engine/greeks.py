import math


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot: float, strike: float, years: float, sigma: float, is_call: bool, rate: float = 0.0) -> float:
    if years <= 0.0 or sigma <= 0.0 or spot <= 0.0:
        intrinsic = max(spot - strike, 0.0) if is_call else max(strike - spot, 0.0)
        return max(intrinsic, 0.01)
    sqrt_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    if is_call:
        price = spot * norm_cdf(d1) - strike * math.exp(-rate * years) * norm_cdf(d2)
    else:
        price = strike * math.exp(-rate * years) * norm_cdf(-d2) - spot * norm_cdf(-d1)
    return max(price, 0.01)


def bs_delta(spot: float, strike: float, years: float, sigma: float, is_call: bool, rate: float = 0.0) -> float:
    if years <= 0.0 or sigma <= 0.0:
        if is_call:
            return 1.0 if spot > strike else 0.0
        return -1.0 if spot < strike else 0.0
    sqrt_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * years) / (sigma * sqrt_t)
    return norm_cdf(d1) if is_call else norm_cdf(d1) - 1.0
