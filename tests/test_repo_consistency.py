"""Coherencia del repositorio: versión única, copias compartidas idénticas, textos en los dos idiomas y sintaxis de JS y shell."""
import hashlib, re, shutil, subprocess, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
MODULES = ["wol-console", "nut-monitor", "net-monitor", "proxmox-monitor", "overview", "auth"]

class Versions(unittest.TestCase):
    def test_version_file_control_and_changelog_agree(self):
        v = (ROOT / "VERSION").read_text().strip()
        self.assertRegex(v, r"^\d+\.\d+(\.\d+)?[a-z]?$")
        ctrl = re.search(r"^Version:\s*(\S+)", (ROOT / "debian/control").read_text(), re.M).group(1)
        top = re.search(r"^## (\S+)", (ROOT / "CHANGELOG.md").read_text(), re.M).group(1)
        self.assertEqual((ctrl, top), (v, v), "VERSION, debian/control y la primera entrada del CHANGELOG deben coincidir")

class License(unittest.TestCase):
    """Desde la 1.3 el proyecto es PolyForm Noncommercial 1.0.0 (uso comercial solo con permiso del autor)."""
    def test_license_file_and_docs_agree(self):
        lic = (ROOT / "LICENSE").read_text()
        self.assertTrue(lic.startswith("Required Notice: Copyright"), "PolyForm exige la línea «Required Notice:»")
        for clave in ("PolyForm Noncommercial License 1.0.0", "Noncommercial Purposes", "Personal Uses", "No Liability", "polyformproject.org/licenses/noncommercial/1.0.0"):
            self.assertIn(clave, lic)
        self.assertNotIn("Permission is hereby granted, free of charge", lic, "quedó texto de la licencia MIT")
        for readme in ("README.md", "README.en.md"):
            txt = (ROOT / readme).read_text()
            self.assertIn("PolyForm Noncommercial 1.0.0", txt, readme)
            self.assertNotRegex(txt, r"(?m)^MIT\b", f"{readme} todavía dice MIT")

    def test_debian_copyright_names_the_same_license(self):
        c = (ROOT / "debian/copyright").read_text()
        self.assertIn("License: PolyForm-Noncommercial-1.0.0", c)
        self.assertIn("Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/", c)

class SharedAssets(unittest.TestCase):
    """Estos archivos se copian a mano a varias carpetas: si una copia cambia sola, la página se comporta distinto según el módulo."""
    SHARED = ["timefmt.js", "csp-bind.js", "footer.js", "ipcard.js", "ipcard.css"]
    def test_copies_are_identical(self):
        for name in self.SHARED:
            with self.subTest(file=name):
                digests = {m: hashlib.sha256(p.read_bytes()).hexdigest() for m in MODULES if (p := ROOT / m / "static" / name).is_file()}
                self.assertGreaterEqual(len(digests), 2, f"{name} no se encontró en varios módulos")
                self.assertEqual(len(set(digests.values())), 1, f"{name} difiere entre módulos: {digests}")

    def test_every_script_in_index_exists(self):
        for m in MODULES:
            idx = ROOT / m / "static" / "index.html"
            if not idx.is_file(): continue
            for src in re.findall(r'<script[^>]+src="([^"]+)"', idx.read_text()):
                with self.subTest(module=m, script=src):
                    self.assertTrue((ROOT / m / "static" / src).is_file() or src.startswith(("/", "http")), f"{m}: falta {src}")

    def test_no_inline_script_or_handlers(self):      # CSP estricta: script-src 'self'
        for m in MODULES:
            idx = ROOT / m / "static" / "index.html"
            if not idx.is_file(): continue
            html = idx.read_text()
            with self.subTest(module=m):
                self.assertEqual(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>", html), [], "script en línea")
                self.assertEqual(re.findall(r'\son(?:click|change|input|load|error|submit|keydown|keyup)=', html), [], "manejador en línea")

NODE_KEYS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const m = /\bconst (LANG|TXT)\s*=\s*\{/.exec(src);
if (!m) { console.log(JSON.stringify({missing: true})); process.exit(0); }
let i = m.index + m[0].length - 1, depth = 0, q = null, esc = false;
for (let j = i; j < src.length; j++) {
  const c = src[j];
  if (q) { if (esc) esc = false; else if (c === '\\') esc = true; else if (c === q) q = null; continue; }
  if (c === "'" || c === '"' || c === '`') { q = c; continue; }
  if (c === '{') depth++;
  if (c === '}' && --depth === 0) { var lit = src.slice(i, j + 1); break; }
}
const o = new Function('return ' + lit)();
console.log(JSON.stringify({en: Object.keys(o.en || {}), es: Object.keys(o.es || {})}));
"""

@unittest.skipUnless(shutil.which("node"), "node no está instalado")
class Languages(unittest.TestCase):
    def test_en_and_es_have_the_same_keys(self):
        import json
        for m in MODULES:
            f = ROOT / m / "static" / "app.js"
            with self.subTest(module=m):
                r = subprocess.run(["node", "-e", NODE_KEYS, str(f)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr[-300:])
                d = json.loads(r.stdout)
                self.assertFalse(d.get("missing"), "no se encontró la tabla de textos (const LANG / TXT)")
                self.assertGreater(len(d["en"]), 20)
                self.assertEqual(sorted(set(d["en"]) - set(d["es"])), [], "faltan en español")
                self.assertEqual(sorted(set(d["es"]) - set(d["en"])), [], "faltan en inglés")

@unittest.skipUnless(shutil.which("node"), "node no está instalado")
class JavaScriptSyntax(unittest.TestCase):
    def test_all_static_js_parses(self):
        for f in sorted(ROOT.glob("*/static/*.js")):
            with self.subTest(file=str(f.relative_to(ROOT))):
                r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr[-300:])

@unittest.skipUnless(shutil.which("bash"), "bash no está instalado")
class ShellSyntax(unittest.TestCase):
    def test_scripts_parse(self):
        files = [*ROOT.glob("scripts/*"), *(ROOT / "debian").glob("p*")]
        for f in files:
            if not f.is_file() or f.suffix == ".py": continue
            head = f.read_text(errors="ignore").splitlines()[:1]
            if not head or "sh" not in head[0]: continue
            with self.subTest(file=str(f.relative_to(ROOT))):
                self.assertEqual(subprocess.run(["bash", "-n", str(f)], capture_output=True, text=True).returncode, 0)
if __name__ == "__main__": unittest.main()
