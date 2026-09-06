import json, pathlib, sys
sys.path.insert(0, '/home/fruit/dev')
from MarkdownGlance.preview.renderer.export import standalone_html
from playwright.sync_api import sync_playwright
root=pathlib.Path('/tmp/mdglance-release-042/browser'); root.mkdir(exist_ok=True)
source='# Release check\n\n```mermaid\nflowchart LR\nA --> B\n```\n\nInline $a^2+b^2=c^2$.\n\n$$\n\\frac{1}{2}\n$$\n'
f=root/'check.html'; f.write_text(standalone_html(source,'Release check',''))
results=[]
with sync_playwright() as p:
 b=p.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True)
 for theme in ('light','dark'):
  page=b.new_page(color_scheme=theme)
  page.goto(f.as_uri())
  page.wait_for_selector('.mermaid svg',timeout=60000)
  page.wait_for_selector('.katex',timeout=60000)
  assert page.locator('.katex').count()==2
  page.screenshot(path=str(root/(theme+'.png')),full_page=True)
  results.append({'theme':theme,'mermaid_svg':page.locator('.mermaid svg').count(),'math':page.locator('.katex').count(),'transport':'file'})
  page.close()
 page=b.new_page(); page.route('https://**/*',lambda route:route.abort()); page.goto(f.as_uri()); assert page.locator('pre.mermaid').inner_text().strip()=='flowchart LR\nA --> B'; assert page.locator('.arithmatex').count()==2
 results.append({'offline_source_fallback':'pass'})
 b.close()
(root/'results.json').write_text(json.dumps(results,indent=2)+'\n'); print(json.dumps(results))
