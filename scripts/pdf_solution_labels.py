import sys,collections
import build_local_pdf_plan as b
from PIL import Image, ImageFilter

def green(key,pn):
 p=b.doc(key)[pn-1];pix=p.get_pixmap();im=Image.frombytes('RGB',(pix.width,pix.height),pix.samples);a=im.load()
 mask=set((y,x) for y in range(50,pix.height-45) for x in range(25,135) if a[x,y][1]>a[x,y][0]+8 and a[x,y][1]>a[x,y][2]+4 and a[x,y][1]<235)
 mm=Image.new('1',(pix.width,pix.height));mp=mm.load()
 for y,x in mask:mp[x,y]=1
 mm=mm.filter(ImageFilter.MaxFilter(3));mp=mm.load();mask=set((y,x) for y in range(50,pix.height-45) for x in range(25,135) if mp[x,y])
 result=[]
 for y,x in list(mask):
  if (y,x) not in mask:continue
  points=[];todo=[(y,x)];mask.remove((y,x))
  while todo:
   yy,xx=todo.pop();points.append((yy,xx))
   for dy,dx in [(1,0),(-1,0),(0,1),(0,-1)]:
    ny,nx=yy+dy,xx+dx
    if (ny,nx) in mask:mask.remove((ny,nx));todo.append((ny,nx))
  if len(points)<35:continue
  yy=[v[0] for v in points];xx=[v[1] for v in points];box=(min(xx),min(yy),max(xx)+1,max(yy)+1)
  if 8<box[2]-box[0]<55 and 5<box[3]-box[1]<26:result.append(box)
 return sorted(result,key=lambda v:v[1])
if __name__=='__main__':
 for pn in [4,12,40]:print(pn,green('basea',pn))
