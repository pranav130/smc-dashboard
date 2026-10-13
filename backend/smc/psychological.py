from typing import List
from backend.smc.models import PsychologicalLevel

def calculate_psychological_levels(current_price: float, count_each_side: int = 3) -> List[PsychologicalLevel]:
    """
    Calculate psychological round numbers ending in '20' and '80'.
    Highlighted in SMC trading rules: 'Trades occurring at or near the 20s or 80s levels have increased probability'.
    """
    if current_price <= 0:
        return []

    # Century base (e.g. for 4192.5, century is 4100)
    century = int(current_price // 100) * 100
    candidate_centuries = [century - 100, century, century + 100, century + 200]

    raw_levels = []
    for c in candidate_centuries:
        raw_levels.append((c + 20.0, "20"))
        raw_levels.append((c + 80.0, "80"))

    # Sort by absolute distance from current price
    raw_levels.sort(key=lambda x: abs(x[0] - current_price))

    results: List[PsychologicalLevel] = []
    for price, ltype in raw_levels[:count_each_side * 2]:
        dist = round(price - current_price, 2)
        dist_pct = round((dist / current_price) * 100.0, 2)
        results.append(PsychologicalLevel(
            price=price,
            level_type=ltype,
            distance=dist,
            distance_pct=dist_pct
        ))

    # Sort back by price descending
    results.sort(key=lambda x: x.price, reverse=True)
    return results
