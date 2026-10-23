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

    def nearest_reference(self,j,i,exclude=None):
        """Vector oracle for equivalence tests / measured small-population fallback."""
        import numpy as np
        if not hasattr(self,'_vector_points'):
            self._vector_keys=np.array(sorted(self.keys))
            self._vector_points=np.array([self.points[key] for key in self._vector_keys])
        valid=self._vector_keys!=exclude
        if not valid.any():return None
        points=self._vector_points
        distances=(points[:,0]-j)**2+(points[:,1]-i)**2
        distances=np.where(valid,distances,np.iinfo(np.int64).max)
        return int(self._vector_keys[int(np.argmin(distances))])
