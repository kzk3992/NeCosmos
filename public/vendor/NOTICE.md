# Bundled runtime dependencies

- Pyodide 0.27.7, Python 3.12.7 / WebAssembly: https://pyodide.org/en/0.27.7/
  Files downloaded from the official distribution URL documented by Pyodide:
  https://cdn.jsdelivr.net/pyodide/v0.27.7/full/
  Pyodide license: pyodide/LICENSE. CPython/library licenses are included in the distribution.
- NumPy 2.0.2 wasm32 wheel, SHA-256 verified against bundled official pyodide-lock.json.
  Package license is inside the wheel's numpy-2.0.2.dist-info directory.
- Three.js 0.160.0: https://threejs.org/ ; MIT license in three/LICENSE.
  Selected unmodified modules from https://registry.npmjs.org/three/-/three-0.160.0.tgz.

All required files are served by this application; no runtime CDN requests are required.
