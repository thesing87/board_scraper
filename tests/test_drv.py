import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA_DIR, LIVE_URL, shot_dir
import os, sys, tempfile, importlib.util
os.environ['OUTPUT_DIR'] = tempfile.mkdtemp()
spec = importlib.util.spec_from_file_location('m', os.path.join(ROOT, 'app', 'fmkorea-scraper.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class Alive:
    def execute_script(self, s): return 1
class Dead:
    quit_called = False
    def execute_script(self, s): raise RuntimeError('session deleted')
    def quit(self): Dead.quit_called = True
m.create_driver = lambda: 'NEW'
a = Alive(); assert m.ensure_driver_alive(a) is a
assert m.ensure_driver_alive(Dead()) == 'NEW' and Dead.quit_called
print('DRIVER OK')
