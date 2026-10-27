from PIL import Image, ImageDraw, ImageFont, ImageFilter
import subprocess, time, json, pathlib, resource
root=pathlib.Path('/tmp/ocr-benchmark'); results=[]
font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',26)
for broker,bg,fg in [('MyInvestor','white','black'),('IBKR','#131c2c','white'),('Degiro','white','#151e2b')]:
 im=Image.new('RGB',(1080,650),bg); d=ImageDraw.Draw(im)
 d.text((25,22),f'{broker} - CARTERA SINTETICA (NO CUENTA REAL)',font=font,fill=fg)
 for y,text in [(95,'Ticker         Cantidad     Divisa     Precio     Valor'),(165,'ASTS           125,5        USD        80,22      10067,61'),(235,'BN             20           USD        55,50      1110,00'),(305,'CGEO.L         8            GBP        22,20      177,60')]:
  for x,t in zip([25,270,490,690,875],text.split()): d.text((x,y),t,font=font,fill=fg)
 path=root/f'{broker}.png'; im.save(path)
 start=time.monotonic(); p=subprocess.run(['tesseract',str(path),'stdout','-l','eng','--psm','6','tsv'],capture_output=True,text=True)
 elapsed=time.monotonic()-start; (root/f'{broker}.tsv').write_text(p.stdout)
 tokens=[line.split('\t')[-1] for line in p.stdout.splitlines()[1:] if len(line.split('\t'))==12 and line.split('\t')[-1]]
 targets=['ASTS','125,5','USD','BN','20','USD','CGEO.L','8','GBP']
 # evaluate unique ticker, quantity, currency per expected row using output line groups later
 results.append({'broker':broker,'seconds':round(elapsed,3),'max_rss_kib':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,'expected_tokens_found':sum(t in tokens for t in targets),'expected_tokens':len(targets),'tokens':tokens})
print(json.dumps(results,indent=2)); (root/'results.json').write_text(json.dumps(results,indent=2))
