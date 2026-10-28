"""Download pinned public ONNX weights. No credentials or model API credits needed."""
import hashlib
import json
import sys
from pathlib import Path
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.ai.vectors import folder

REPOSITORY='Xenova/bge-small-zh-v1.5'
REVISION='75c43b069aac4d136ba6bc1122f995fedcfd2781'
FILES={'tokenizer.json':'48cea5d44424912a6fd1ea647bf4fe50b55ab8b1e5879c3275f80e339e8fae26',
       'tokenizer_config.json':'e6f3b96db926a37d4039995fbf5ad17de158dfb8f6343d607e4dbaad18d75f5a',
       'config.json':'d4193ead3a810fd694fa8a31d7fc72fbaebc0668b603e398734bf2f6538ff42f',
       'onnx/model_quantized.onnx':'15b717c382bcb518ba457b93ea6850ede7f4f1cd8937454aa06972366cd19bcc'}

def main():
    target=folder();target.mkdir(parents=True,exist_ok=True)
    manifest={'repository':REPOSITORY,'revision':REVISION,'original_model':'BAAI/bge-small-zh-v1.5',
              'license':'MIT (converted weights); original model license in upstream card','files':{}}
    with httpx.Client(follow_redirects=True,timeout=180) as client:
        for resource,expected in FILES.items():
            out=target/Path(resource).name;part=out.with_suffix(out.suffix+'.part')
            if not out.exists() or hashlib.sha256(out.read_bytes()).hexdigest()!=expected:
                with client.stream('GET',f'https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{resource}') as response:
                    response.raise_for_status()
                    with part.open('wb') as f:
                        for chunk in response.iter_bytes():f.write(chunk)
                if hashlib.sha256(part.read_bytes()).hexdigest()!=expected:part.unlink();raise ValueError('模型文件校验失败。')
                part.replace(out)
            manifest['files'][out.name]={'bytes':out.stat().st_size,'sha256':expected}
            print(out.name,out.stat().st_size,flush=True)
    (target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
