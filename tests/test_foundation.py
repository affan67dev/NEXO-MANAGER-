from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from core.router import route

print(route("hello NEXO"))
print(route("search web latest AI news"))
print(route("remember my project"))
print("✅ NEXO foundation test passed")
