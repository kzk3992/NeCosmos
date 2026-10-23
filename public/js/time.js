// Planet time is independent of rendering and biological balance parameters.
export const PLANET_DAY_SECONDS = 15;
export const BIOLOGICAL_YEAR_DAYS = 48;
export const MODES = Object.freeze({
  '0.05': {seconds: 300, hz: 60, label: 'じっくり観察'},
  '1': {seconds: 15, hz: 4, label: '×1'},
  '5': {seconds: 3, hz: 3, label: '×5'},
  '10': {seconds: 1.5, hz: 2, label: '×10'},
  '20': {seconds: .75, hz: 2, label: '×20'},
  '100': {seconds: .15, hz: 1, label: '×100'},
});
export class PlanetClock {
  constructor(speed = 1) { this.acc = 0; this.setMode(speed); }
  setMode(speed) {
    if (!MODES[String(speed)]) throw new RangeError('Unknown playback mode');
    this.speed = Number(speed); this.acc = 0;
  }
  reset() { this.acc = 0; }
  advance(seconds, running) {
    if (!running) return 0;
    if (!Number.isFinite(seconds) || seconds < 0) throw new RangeError('Invalid elapsed time');
    this.acc += seconds / MODES[String(this.speed)].seconds;
    return this.acc;
  }
  take(max = 30) {
    const days = Math.min(Math.floor(this.acc + 1e-10), max);
    this.acc = Math.max(0, this.acc - days); return days;
  }
}
// New requests supersede old ones; the caller supplies the engine/render barrier.
export class ModeSwitch {
  constructor(apply) { this.apply = apply; this.pending = null; this.job = null; }
  request(speed) {
    if (!MODES[String(speed)]) return Promise.reject(new RangeError('Unknown playback mode'));
    this.pending = Number(speed);
    if (!this.job) this.job = this.drain().finally(() => { this.job = null; });
    return this.job;
  }
  async drain() {
    while (this.pending !== null) {
      await this.apply(() => { const speed = this.pending; this.pending = null; return speed; });
    }
  }
}
