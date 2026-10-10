"""Encode captured browser frames into looping GIFs."""
import json
from pathlib import Path
from PIL import Image

root=Path(__file__).resolve().parents[1]
groups=json.loads((root/'artifacts/demo-frames/frames.json').read_text())
output=root/'docs/demos'
output.mkdir(parents=True,exist_ok=True)
for name,frames in groups.items():
    images=[]
    for frame in frames:
        with Image.open(root/frame['path']) as image:
            images.append(image.convert('RGB').quantize(colors=128))
    target=output/(name+'.gif')
    images[0].save(target,save_all=True,append_images=images[1:],
                   duration=[f['duration'] for f in frames],loop=0,optimize=True,disposal=1)
    with Image.open(target) as gif:
        assert gif.n_frames>1
    print(target.name, target.stat().st_size, 'bytes')
