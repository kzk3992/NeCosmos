// NeCosmos v0.10 renderer: live height-field terrain + water from the simulation, immutable rock base,
// 8-direction pixel cat sprites, Phase 3 GLB objects. Sim (x, y, z) metres, Blender Z-up ->
// Three (x - 8, z, 8 - y). Rendering never waits on the simulation worker.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const DIRS = ["front", "front_left", "left", "back_left", "back", "back_right", "right", "front_right"];
const FEET_V = 1 - 207.42 / 256;           // sprite rig ground-origin row (Phase 2 metadata)
const SPRITE_M = 0.8;                       // sprite frame width in metres (ortho scale of the rig)
const BIOME_COL = [0xa9be76, 0xe2d3a3, 0x7e9a72, 0xc8d4dc, 0x6fa0c8];   // moss, desert, wet, cold, aquatic
const HALF = 8;

export function toThree(x, y, z) { return new THREE.Vector3(x - HALF, z, HALF - y); }

export class World3D {
  constructor(container, catalog) {
    this.container = container;
    this.catalog = catalog;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x101926);
    this.camera = new THREE.PerspectiveCamera(32, 1, 0.1, 200);
    this.camera.position.set(0, 20, 28);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(0, -0.1, 0);
    this.controls.enableDamping = true;
    this.controls.minDistance = 4;
    this.controls.maxDistance = 45;
    this.controls.minPolarAngle = 0.35;
    this.controls.maxPolarAngle = 1.25;
    this.controls.screenSpacePanning = false;
    this.scene.add(new THREE.HemisphereLight(0xeef4ff, 0x5a4a3c, 1.5));
    const sun = new THREE.DirectionalLight(0xffffff, 2.0);
    sun.position.set(-8, 16, 10);
    this.scene.add(sun);
    this.catScale = 1.6;
    this.texCache = {};
    this.catSprites = new Map();
    this.lastCell = new Map();
    this.heading = new Map();
    this.objects = new Map();
    this.models = {};
    this.loader = new GLTFLoader();
    this.raycaster = new THREE.Raycaster();
    this.ghost = null;
    this.state = null;
    window.addEventListener("resize", () => this.resize());
    this.resize();
    const loop = () => { this.controls.update(); this.updateSpriteDirs(); this.renderer.render(this.scene, this.camera); requestAnimationFrame(loop); };
    loop();
  }

  resize() {
    const w = this.container.clientWidth || 1, h = this.container.clientHeight || 1;
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  // ------------------------------------------------------------------ terrain / water / rock
  setWorld(st) {
    for (const k of ["terrain", "water", "rock"]) if (this[k]) { this.scene.remove(this[k]); this[k].geometry.dispose(); }
    for (const s of this.catSprites.values()) this.scene.remove(s);
    this.catSprites.clear(); this.lastCell.clear(); this.heading.clear();
    for (const o of this.objects.values()) this.scene.remove(o.root);
    this.objects.clear();
    const n = st.n, d = st.cell_m;
    this.n = n; this.d = d;
    const grid = (yOf) => {
      const g = new THREE.BufferGeometry();
      const pos = new Float32Array(n * n * 3), col = new Float32Array(n * n * 3);
      const idx = [];
      for (let j = 0; j < n; j++) for (let i = 0; i < n; i++) {
        const k = j * n + i, p = toThree((i + 0.5) * d, (j + 0.5) * d, yOf(k));
        pos.set([p.x, p.y, p.z], 3 * k);
      }
      for (let j = 0; j < n - 1; j++) for (let i = 0; i < n - 1; i++) {
        const a = j * n + i, b = a + 1, c = a + n, e = c + 1;
        // j increases toward -Z in Three.js, so this winding faces +Y.
        idx.push(a, b, c, b, e, c);
      }
      g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      g.setAttribute("color", new THREE.BufferAttribute(col, 3));
      g.setIndex(idx);
      return g;
    };
    this.terrain = new THREE.Mesh(grid((k) => st.z[k]), new THREE.MeshLambertMaterial({ vertexColors: true, flatShading: true }));
    this.water = new THREE.Mesh(grid((k) => st.z[k] - 0.05), new THREE.MeshLambertMaterial({ color: 0x4f9bd0, transparent: true, opacity: 0.72, flatShading: true, depthWrite: false }));
    this.water.renderOrder = 2;
    this.scene.add(this.terrain, this.water);
    this.rock = this.buildRock(st);
    this.scene.add(this.rock);
    this.update(st);
  }

  buildRock(st) {
    // immutable underside + rim skirt from the fixed perimeter heights (rim never changes)
    const n = st.n, d = st.cell_m, ring = [];
    for (let i = 0; i < n; i++) ring.push([0, i]);
    for (let j = 1; j < n; j++) ring.push([j, n - 1]);
    for (let i = n - 2; i >= 0; i--) ring.push([n - 1, i]);
    for (let j = n - 2; j > 0; j--) ring.push([j, 0]);
    const pos = [], col = [], idx = [];
    const levels = [[1.0, 0], [1.0, -0.6], [0.92, -1.4], [0.7, -2.3], [0.35, -3.1]];
    const bands = [0x7a5a3f, 0x927a62, 0x7e6e62, 0x655c57, 0x4f4a4a];
    levels.forEach(([rf, dz], L) => {
      for (const [j, i] of ring) {
        const x = (i + 0.5) * d - HALF, y = (j + 0.5) * d - HALF;
        const z = L === 0 ? st.z[j * n + i] : 0.8 + dz;
        const p = toThree(x * rf + HALF, y * rf + HALF, z);
        pos.push(p.x, p.y, p.z);
        const c = new THREE.Color(bands[L]);
        col.push(c.r, c.g, c.b);
      }
    });
    const m = ring.length;
    for (let L = 0; L < levels.length - 1; L++) for (let k = 0; k < m; k++) {
      const a = L * m + k, b = L * m + (k + 1) % m;
      idx.push(a, b, a + m, b, b + m, a + m);
    }
    const c0 = pos.length / 3;
    pos.push(0, -3.4, 0);
    col.push(0.3, 0.28, 0.28);
    const last = (levels.length - 1) * m;
    for (let k = 0; k < m; k++) idx.push(last + k, c0, last + (k + 1) % m);
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute("color", new THREE.Float32BufferAttribute(col, 3));
    g.setIndex(idx);
    g.computeVertexNormals();
    return new THREE.Mesh(g, new THREE.MeshLambertMaterial({ vertexColors: true, flatShading: true, side: THREE.DoubleSide }));
  }

  update(st) {
    this.state = st;
    const n = st.n;
    const tp = this.terrain.geometry.attributes.position, tc = this.terrain.geometry.attributes.color;
    const wp = this.water.geometry.attributes.position, wc = this.water.geometry.attributes.color;
    const c = new THREE.Color();
    for (let k = 0; k < n * n; k++) {
      tp.setY(k, st.z[k]);
      c.setHex(BIOME_COL[st.biome[k]] ?? BIOME_COL[0]);
      if (st.snow && st.snow[k] > 0.002) c.lerp(new THREE.Color(0xf4f7fb), 0.7);
      if (!st.unlocked[k]) { const g = (c.r + c.g + c.b) / 3; c.setRGB((c.r * 0.45 + g * 0.55) * 0.7, (c.g * 0.45 + g * 0.55) * 0.7, (c.b * 0.45 + g * 0.55) * 0.7); }
      if (st.protection[k] > 0.05) c.lerp(new THREE.Color(0xd8c07a), 0.25 * st.protection[k]);
      tc.setXYZ(k, c.r, c.g, c.b);
      const wet = st.h[k] > 0.004;
      wp.setY(k, wet ? st.z[k] + st.h[k] : st.z[k] - 0.05);
      const wcol = st.river[k] ? new THREE.Color(0x3a7fd8) : st.pond[k] ? new THREE.Color(0x4f8fd0) : new THREE.Color(0x8fc8e8);
      wc.setXYZ(k, wcol.r, wcol.g, wcol.b);
    }
    this.water.material.vertexColors = true;
    tp.needsUpdate = tc.needsUpdate = wp.needsUpdate = wc.needsUpdate = true;
    this.terrain.geometry.computeVertexNormals();
    this.water.geometry.computeVertexNormals();
    this.terrain.geometry.computeBoundingSphere();
    this.updateCats(st);
    this.updateObjects(st);
  }

  heightAt(x, y) {
    const st = this.state, n = st.n, d = st.cell_m;
    const gi = Math.min(Math.max(x / d - 0.5, 0), n - 1.001), gj = Math.min(Math.max(y / d - 0.5, 0), n - 1.001);
    const i0 = Math.floor(gi), j0 = Math.floor(gj), fi = gi - i0, fj = gj - j0, z = st.z;
    const a = z[j0 * n + i0], b = z[j0 * n + i0 + 1], c = z[(j0 + 1) * n + i0], e = z[(j0 + 1) * n + i0 + 1];
    return (1 - fi) * (1 - fj) * a + fi * (1 - fj) * b + (1 - fi) * fj * c + fi * fj * e;
  }

  // ------------------------------------------------------------------ cats
  texture(species, dir) {
    const key = species + "/" + dir;
    if (!this.texCache[key]) {
      const cat = this.catalog.cats.find((c) => c.id === species);
      const t = new THREE.TextureLoader().load(`/${cat.spriteBase}/${cat.spritePrefix}_${dir}.png`);
      t.colorSpace = THREE.SRGBColorSpace;
      t.magFilter = THREE.NearestFilter;
      t.minFilter = THREE.NearestFilter;
      t.generateMipmaps = false;
      this.texCache[key] = t;
    }
    return this.texCache[key];
  }

  updateCats(st) {
    const cats = st.cats, d = st.cell_m, seen = new Set();
    for (let k = 0; k < cats.id.length; k++) {
      const id = cats.id[k], sp = st.species[cats.sp[k]], j = cats.j[k], i = cats.i[k];
      seen.add(id);
      let s = this.catSprites.get(id);
      if (!s) {
        s = new THREE.Sprite(new THREE.SpriteMaterial({ map: this.texture(sp, "front"), transparent: true, alphaTest: 0.5 }));
        s.center.set(0.5, FEET_V);
        s.userData = { id, sp };
        this.scene.add(s);
        this.catSprites.set(id, s);
        this.heading.set(id, ((id * 2654435761) >>> 0) % 360);
      }
      const prev = this.lastCell.get(id);
      if (prev && (prev[0] !== j || prev[1] !== i)) {                 // face the direction of travel
        this.heading.set(id, (Math.atan2(i - prev[1], -(j - prev[0])) * 180 / Math.PI + 360) % 360);
      }
      this.lastCell.set(id, [j, i]);
      const h = ((id * 2246822519) >>> 0) / 4294967296, h2 = ((id * 3266489917) >>> 0) / 4294967296;
      const x = (i + 0.5) * d + (h - 0.5) * 0.3, y = (j + 0.5) * d + (h2 - 0.5) * 0.3;
      s.position.copy(toThree(x, y, this.heightAt(x, y) + 0.01));
      s.scale.set(SPRITE_M * this.catScale, SPRITE_M * this.catScale, 1);
      Object.assign(s.userData, { age: cats.age[k], energy: cats.energy[k], mass: cats.mass[k], action: cats.action[k], j, i, x, y, sp });
    }
    for (const [id, s] of this.catSprites) if (!seen.has(id)) { this.scene.remove(s); s.material.dispose(); this.catSprites.delete(id); }
  }

  updateSpriteDirs() {
    // 8-direction sprite: camera azimuth around the cat relative to its heading (Blender convention)
    const cam = this.camera.position;
    for (const s of this.catSprites.values()) {
      const dx = cam.x - s.position.x, dy = -(cam.z - s.position.z);
      const head = this.heading.get(s.userData.id) * Math.PI / 180;     // heading: 0 = cat faces -y (front)
      const fx = Math.sin(head), fy = -Math.cos(head);
      const az = Math.atan2(fx * dy - fy * dx, fx * dx + fy * dy);
      const idx = ((Math.round(az * 180 / Math.PI / 45) % 8) + 8) % 8;
      const t = this.texture(s.userData.sp, DIRS[idx]);
      if (s.material.map !== t) { s.material.map = t; s.material.needsUpdate = true; }
    }
  }

  // ------------------------------------------------------------------ objects
  async model(id) {
    if (!this.models[id]) {
      const o = this.catalog.objects.find((c) => c.id === id);
      this.models[id] = new Promise((ok, bad) => this.loader.load("/" + o.model, (g) => ok(g.scene), undefined, bad));
    }
    return this.models[id];
  }

  async updateObjects(st) {
    const seen = new Set();
    for (const o of st.objects) {
      seen.add(o.pid);
      let rec = this.objects.get(o.pid);
      if (!rec) {
        rec = { root: new THREE.Group(), marker: null };
        this.objects.set(o.pid, rec);
        this.scene.add(rec.root);
        this.model(o.id).then((m) => rec.root.add(m.clone(true))).catch((e) => console.error("model", o.id, e));
        const ring = new THREE.Mesh(new THREE.RingGeometry(0.35, 0.45, 24), new THREE.MeshBasicMaterial({ color: 0x5fd0ff, side: THREE.DoubleSide, transparent: true, opacity: 0.85 }));
        ring.rotation.x = -Math.PI / 2;
        ring.position.y = 0.04;
        rec.marker = ring;
        rec.root.add(ring);
      }
      rec.root.position.copy(toThree(o.x, o.y, o.baseZ));
      rec.root.rotation.y = o.yaw * Math.PI / 180;      // Blender yaw about +Z == three yaw about +Y
      rec.marker.visible = !!o.submerged;
      rec.root.userData = o;
    }
    for (const [pid, rec] of this.objects) if (!seen.has(pid)) { this.scene.remove(rec.root); this.objects.delete(pid); }
  }

  async setGhost(id, x, y, yaw, ok) {
    this.ghostWant = id;
    const drop = () => { if (this.ghost) { this.scene.remove(this.ghost); this.ghost.traverse((c) => c.isMesh && c.material.dispose()); } this.ghost = null; this.ghostId = null; };
    if (!id) return drop();
    if (this.ghostId !== id) {
      if (this.ghostLoading === id) return;            // a load for this id is already in flight
      this.ghostLoading = id;
      let m;
      try { m = (await this.model(id)).clone(true); } finally { this.ghostLoading = null; }
      if (this.ghostWant !== id) return;               // cancelled or switched while loading
      m.traverse((c) => { if (c.isMesh) { c.material = new THREE.MeshBasicMaterial({ color: 0x8fe08f, transparent: true, opacity: 0.55, depthWrite: false }); c.renderOrder = 10; c.raycast = () => {}; } });
      drop();
      this.ghost = m;
      this.ghostId = id;
      this.scene.add(m);
    }
    this.ghost.position.copy(toThree(x, y, this.heightAt(x, y)));
    this.ghost.rotation.y = yaw * Math.PI / 180;
    this.ghost.traverse((c) => { if (c.isMesh) c.material.color.setHex(ok ? 0x8fe08f : 0xe07070); });
  }

  // ------------------------------------------------------------------ picking
  ndc(ev) {
    const r = this.renderer.domElement.getBoundingClientRect();
    return new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  }

  pickGround(ev) {
    this.raycaster.setFromCamera(this.ndc(ev), this.camera);
    const hit = this.raycaster.intersectObject(this.terrain, false)[0];
    if (!hit) return null;
    return { x: hit.point.x + HALF, y: HALF - hit.point.z };
  }

  pickCat(ev) {
    this.raycaster.setFromCamera(this.ndc(ev), this.camera);
    const hit = this.raycaster.intersectObjects([...this.catSprites.values()], false)[0];
    return hit ? hit.object.userData : null;
  }

  pickObject(ev) {
    this.raycaster.setFromCamera(this.ndc(ev), this.camera);
    const roots = [...this.objects.values()].map((r) => r.root);
    const hit = this.raycaster.intersectObjects(roots, true)[0];
    if (!hit) return null;
    let o = hit.object;
    while (o && !o.userData?.pid) o = o.parent;
    return o ? o.userData : null;
  }
}
