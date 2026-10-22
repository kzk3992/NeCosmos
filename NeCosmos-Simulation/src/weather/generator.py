"""Provisional finite-state daily meteorology; precipitation mm/day, T Celsius,
light relative to unit mean sunlight, RH fraction. 360-day seasons are unrelated
 to 300-day observation intervals. Stateless counter RNG streams 301..306.
next(day) advances exactly once; repeated current-day calls are cached. Reading
state never advances RNG. Regime and thermal anomaly are explicit replay state.
"""
import math
from dataclasses import dataclass, asdict
from ..coupling import rng

@dataclass(frozen=True)
class Weather:
    day: int
    state: int  # 0 clear, 1 cloudy, 2 rain, 3 extreme rain
    regime: int  # 0 ordinary, 1 wet period, 2 drought period
    temperature_C: float
    precipitation_mm: float
    sunlight: float
    relative_humidity: float
    wet_probability: float
    extreme: bool

class WeatherGenerator:
    def __init__(self, seed, climate, config, mode='normal', extreme_start_day=1):
        if mode not in config['modes']:raise ValueError('Unknown weather mode: '+mode)
        self.seed,self.climate,self.config,self.mode=seed,dict(climate),config,mode
        self.extreme_start_day=int(extreme_start_day)
        self.day=0;self.regime=0;self.anomaly=0.0
        self.current=Weather(0,0,0,float(climate['temp_C']),0.0,1.0,0.65,0.0,False)

    def probabilities(self,day,previous_state,regime):
        c,g=self.climate,self.config
        season=math.cos(2*math.pi*(day%g['year_days'])/g['year_days'])
        base=min(max(c['wet_day_prob'],1e-6),1-1e-6)
        logit=math.log(base/(1-base))+g['season_rain_logit_amplitude']*season
        logit+=g['wet_persistence_logit'] if previous_state>=2 else g['dry_persistence_logit']
        logit+=g['regime_wet_logit'][regime]+g['modes'][self.mode]['wet_logit']
        return 1/(1+math.exp(-logit))

    def next(self,day):
        if day==self.day:return self.current
        if day!=self.day+1:raise ValueError('Weather must advance sequentially, one day at a time')
        c,g=self.climate,self.config
        if self.mode=='fixed':
            self.current=Weather(day,2,0,float(c['temp_C']),float(c['rain_mm_day']),1.0,0.65,1.0,False)
        else:
            season=math.sin(2*math.pi*(day%g['year_days'])/g['year_days'])
            u=rng.u01(self.seed,301,day,[0,1,2,3,4,5])
            transition=g['regime_transition'][self.regime]
            self.regime=0 if u[0]<transition[0] else (1 if u[0]<transition[0]+transition[1] else 2)
            p=self.probabilities(day,self.current.state,self.regime)
            wet=u[1]<p
            mode=g['modes'][self.mode]
            amount=0.0
            if wet:
                amount=c['rain_mm_day']/max(c['wet_day_prob'],1e-6)*(-math.log(max(u[2],1e-12))-math.log(max(u[3],1e-12)))/2
                amount*=g['regime_rain_multiplier'][self.regime]*mode['rain_multiplier']
            extreme=wet and self.mode=='extreme' and day>=self.extreme_start_day and u[4]<g['extreme_probability']
            if extreme:amount+=g['extreme_extra_min_mm']+(g['extreme_extra_max_mm']-g['extreme_extra_min_mm'])*float(rng.u01(self.seed,302,day,[0])[0])
            state=3 if extreme else (2 if wet else (1 if u[5]<0.3 else 0))
            noise=float(rng.normal(self.seed,303,day,[0])[0])
            self.anomaly=g['temperature_ar']*self.anomaly+g['temperature_noise_C']*noise
            temp=c['temp_C']+c['season_amp_C']*season+self.anomaly+([0,-0.5,-1.2,-2][state])+(2 if self.regime==2 else 0)
            sunlight=max(0.05,(1+0.18*season)*[1.1,0.65,0.38,0.2][state])
            rh=min(0.99,max(0.08,0.46+0.08*season+(0.30 if wet else 0)+[0,0.1,-0.18][self.regime]+0.04*float(rng.normal(self.seed,304,day,[0])[0])))
            self.current=Weather(day,state,self.regime,float(temp),float(amount),float(sunlight),float(rh),float(p),bool(extreme))
        self.day=day
        return self.current

    def export_state(self):
        return {'day':self.day,'regime':self.regime,'anomaly':self.anomaly,'current':asdict(self.current)}

    def restore_state(self,state):
        self.day=int(state['day']);self.regime=int(state['regime']);self.anomaly=float(state['anomaly'])
        self.current=Weather(**state['current'])
