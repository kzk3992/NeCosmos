"""Read-only subday coordinates of the engine-owned daily transaction.

Grid occupancy/budgets commit on the integer day. Continuous positions follow the
immutable motion plan at the start of that day; intake commits at its end. The
same planet-time trajectory is used at every playback speed (75 metres/day).
"""
import math
METRES_PER_PLANET_DAY = 75.0

def sample(moves, cell_m, fraction):
    if not math.isfinite(fraction) or not 0 <= fraction <= 1:
        raise ValueError('planet-day fraction must be 0..1')
    out=[]
    for m in moves:
        j,i=m['origin'];tj,ti=m['position']
        x0,y0=(i+.5)*cell_m,(j+.5)*cell_m
        x1,y1=(ti+.5)*cell_m,(tj+.5)*cell_m
        distance=math.hypot(x1-x0,y1-y0)
        t=min(1,fraction*METRES_PER_PLANET_DAY/distance) if distance else 1
        out.append(dict(id=m['id'],x=x0+(x1-x0)*t,y=y0+(y1-y0)*t,walking=t<1 and distance>0,
                        heading=(math.degrees(math.atan2(x1-x0,-(y1-y0)))+360)%360 if distance else None))
    return out
