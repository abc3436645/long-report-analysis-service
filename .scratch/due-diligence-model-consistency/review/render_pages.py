from pathlib import Path
import json,subprocess,shutil
from pypdf import PdfReader
from PIL import Image,ImageOps,ImageDraw
ROOT=Path(__file__).resolve().parents[3]; EXP=ROOT/'.scratch/due-diligence-model-consistency/experiment'
for arm in ['sol','terra']:
 publication=EXP/arm/'publication.json'
 if not publication.exists():continue
 data=json.loads(publication.read_text());pdf=Path(data['pdf_path']); qa=Path(__file__).parent/arm;qa.mkdir(exist_ok=True)
 reader=PdfReader(pdf); print(arm,'pages',len(reader.pages),flush=True)
 subprocess.run(['pdftoppm','-r','80','-png',str(pdf),str(qa/'page')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
 files=sorted(qa.glob('page-*.png'))
 for start in range(0,len(files),6):
  thumbs=[]
  for file in files[start:start+6]:
   im=Image.open(file).convert('RGB');im.thumbnail((450,640))
   tile=Image.new('RGB',(470,680),'#dddddd');tile.paste(im,((470-im.width)//2,25));ImageDraw.Draw(tile).text((10,660),file.stem,fill='black');thumbs.append(tile)
  board=Image.new('RGB',(470*3,680*2),'white')
  for i,tile in enumerate(thumbs):board.paste(tile,((i%3)*470,(i//3)*680))
  board.save(qa/f'overview-{start//6+1:02d}.png')
 (qa/'page-metadata.json').write_text(json.dumps({'pdf':str(pdf),'pages':len(reader.pages),'page_text_lengths':[len(page.extract_text() or '') for page in reader.pages]},indent=2))
