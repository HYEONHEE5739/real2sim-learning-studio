"""Persistent, read-only Curation worker. JSON commands, existing mmap RGB IPC."""
import argparse,json,sys
from contextlib import ExitStack
from pathlib import Path
from ..data.review import EpisodeReview
from ..data import video
from ..run import preview_session


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--workspace',required=True);args=parser.parse_args()
    directory=Path(args.output).resolve();reader=None;key=None;scene_cache={}
    with ExitStack()as stack:
        transport=False
        try:
            for line in sys.stdin:
                request=json.loads(line)
                if request.get('operation')=='close':break
                response={'id':request['id'],'epoch':request['epoch'],'seek':request['seek']}
                try:
                    current=(request['source'],request['selection_id'],request['epoch'])
                    if current!=key:
                        if reader is not None:reader.close();reader=None
                        reader=EpisodeReview(request['source'],request['selection_id'],workspace=args.workspace,scene_cache=scene_cache)
                        if directory.is_relative_to(reader.episode.source_root):raise ValueError('Review transport must be outside immutable Dataset')
                        response['info']=reader.info();key=current
                    if not transport:
                        directory.mkdir(parents=True,exist_ok=True);stack.enter_context(preview_session(directory,lambda _:None,interval_s=0));transport=True
                    frame=reader.frame(request['frame'])
                    for camera,rgb in frame.pop('rgb').items():video._preview_sink(camera,rgb,frame['selection_frame'],frame['timestamp_s'],0)
                    response.update(ok=True,result=frame)
                except Exception as error:response.update(ok=False,error=str(error))
                print(json.dumps(response,separators=(',',':')),flush=True)
        finally:
            if reader is not None:reader.close()


if __name__=='__main__':main()
