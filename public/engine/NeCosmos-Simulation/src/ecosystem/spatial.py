"""Deterministic ecology-only grid index (canonical index breaks distance ties)."""
class SpatialIndex:
    def __init__(self, js, is_, keys=None):
        self.cells={}
        self.keys=list(range(len(js))) if keys is None else list(keys)
        self.points={}
        for key,j,i in zip(self.keys,js,is_):
            point=(int(j),int(i));self.points[key]=point
            self.cells.setdefault(point,[]).append(key)
        self.extent=max((max(abs(j),abs(i)) for j,i in self.cells),default=0)+1

    def nearby(self,j,i,radius=1,cross=False):
        return [key for dj in range(-radius,radius+1) for di in range(-radius,radius+1)
                if not cross or abs(dj)+abs(di)<=radius
                for key in self.cells.get((j+dj,i+di),())]

    def nearest(self,j,i,exclude=None):
        best=None;best_d=float('inf')
        for radius in range(self.extent*2+1):
            if radius == 0:
                ring=[(0,0)]
            else:
                ring=([(dj,di) for dj in (-radius,radius) for di in range(-radius,radius+1)]
                      +[(dj,di) for di in (-radius,radius) for dj in range(-radius+1,radius)])
            for dj,di in ring:
                for key in self.cells.get((j+dj,i+di),()):
                    if key==exclude:continue
                    distance=dj*dj+di*di
                    if distance<best_d or (distance==best_d and (best is None or key<best)):
                        best,best_d=key,distance
            if best is not None and best_d < (radius+1)**2:break
        return best
