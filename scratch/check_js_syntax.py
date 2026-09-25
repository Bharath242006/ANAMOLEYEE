import re
import subprocess
import os

with open("static/index.html", "r", encoding="utf-8") as f:
    html = f.read()

scripts = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
js_content = "\n".join(scripts)

temp_js = "scratch/temp_index.js"
os.makedirs("scratch", exist_ok=True)
with open(temp_js, "w", encoding="utf-8") as f:
    f.write(js_content)

result = subprocess.run(["node", "--check", temp_js], capture_output=True, text=True)
print("Node check exit code:", result.returncode)
if result.stdout:
    print("STDOUT:", result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)
