"""Authenticated quiz-bank sync and episode creation. Never logs credentials."""
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlencode, urlparse, quote
from urllib.error import HTTPError, URLError
from datetime import datetime, timezone
import argparse, json, os, time, math
ROOT=Path(__file__).resolve().parent

def read_env():
    values={}
    path=ROOT/'.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key,value=line.split('=',1)
                values[key.strip()]=value.strip().strip('"').strip("'")
    return values

class Client:
    def __init__(self):
        env=read_env()
        self.base=os.environ.get('QUIZ_API_BASE_URL',env.get('QUIZ_API_BASE_URL','https://quiz.farjadsamaneh.ir/api/v1')).rstrip('/')
        self.key=os.environ.get('QUIZ_API_KEY',env.get('QUIZ_API_KEY',''))
        if not self.key: raise ValueError('Set QUIZ_API_KEY in the local .env file.')
        origin=urlparse(self.base)
        if origin.scheme!='https':raise ValueError('The API base URL must use HTTPS.')
        class SameOrigin(HTTPRedirectHandler):
            def redirect_request(self,req,fp,code,msg,headers,newurl):
                target=urlparse(newurl)
                if (target.scheme,target.netloc)!=(origin.scheme,origin.netloc):
                    raise ValueError('Refusing to forward API credentials to another origin.')
                return super().redirect_request(req,fp,code,msg,headers,newurl)
        self.opener=build_opener(SameOrigin())
    def get(self,path,**query):
        url=self.base+'/'+path.lstrip('/')
        params={k:v for k,v in query.items() if v is not None}
        if params:url+='?'+urlencode(params)
        for attempt in range(3):
            try:
                request=Request(url,headers={'X-Api-Key':self.key,'Accept':'application/json'})
                with self.opener.open(request,timeout=25) as response:return json.load(response)
            except HTTPError as exc:
                if exc.code in (429,500,502,503,504) and attempt<2:time.sleep(attempt+1);continue
                raise RuntimeError(f'Quiz API returned HTTP {exc.code}; credentials were not logged.') from None
            except (URLError,TimeoutError):
                if attempt<2:time.sleep(attempt+1);continue
                raise RuntimeError('Quiz API connection failed after three attempts.') from None

def validate_question(q):
    if not isinstance(q,dict) or not q.get('id') or not isinstance(q.get('text'),str):raise ValueError('Question is missing an ID/text.')
    options=q.get('options');index=q.get('correctIndex')
    if not isinstance(options,list) or len(options)!=4 or not all(isinstance(x,str) and x.strip() for x in options):raise ValueError(f'Question {q.get("id")} needs four nonempty options.')
    if type(index) is not int or index not in range(4):raise ValueError(f'Question {q["id"]} has an invalid correctIndex.')

def sync():
    client=Client();meta=client.get('meta');first=client.get('questions',page=1,limit=200)
    if not isinstance(first,dict) or not isinstance(first.get('items'),list):raise ValueError('Unexpected questions API response.')
    total=int(first['total']);limit=int(first['limit']);pages=int(first.get('pages',math.ceil(total/limit)))
    items=list(first['items'])
    print(f'Question bank: {total} items, {pages} pages.',flush=True)
    for page in range(2,pages+1):
        response=client.get('questions',page=page,limit=limit)
        if int(response.get('total',total))!=total:raise RuntimeError('The bank changed during the download; rerun sync for a consistent snapshot.')
        items.extend(response['items'])
        if page%5==0 or page==pages:print(f'Downloaded page {page}/{pages}.',flush=True)
    ids=[str(q.get('id')) for q in items]
    if len(items)!=total or len(set(ids))!=total:raise RuntimeError('Incomplete or duplicated pagination; existing snapshot was preserved.')
    for q in items:validate_question(q)
    folder=ROOT/'question-bank';folder.mkdir(exist_ok=True)
    stamp=datetime.now(timezone.utc).isoformat()
    payload={'retrieved_at_utc':stamp,'source':client.base,'total':total,'items':items}
    temporary=folder/'questions.downloading.json'
    temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(folder/'questions.json')
    (folder/'meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Saved and validated {total} unique questions in question-bank/questions.json.',flush=True)

def local_items():
    path=ROOT/'question-bank/questions.json'
    if not path.exists():raise ValueError('Run quiz_api.py sync first.')
    return json.loads(path.read_text(encoding='utf-8'))['items']

def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('sync',help='Download all current questions; existing snapshot changes only after complete validation.')
    search=sub.add_parser('search');search.add_argument('text');search.add_argument('--category');search.add_argument('--limit',type=int,default=10)
    episode=sub.add_parser('episode');episode.add_argument('--ids',nargs=3,required=True);episode.add_argument('--name',required=True);episode.add_argument('--category',default='اطلاعات عمومی')
    one=sub.add_parser('get');one.add_argument('id')
    args=parser.parse_args()
    if args.command=='sync':sync()
    elif args.command=='get':
        result=Client().get('questions/'+quote(args.id,safe=''))
        print(json.dumps(result,ensure_ascii=False,indent=2))
    elif args.command=='search':
        matches=[q for q in local_items() if args.text in q['text'] and (not args.category or args.category in q.get('categories',[]))]
        for q in matches[:args.limit]:print(q['id']+'  '+q['text'])
        print(f'{len(matches)} matching questions.')
    else:
        if len(set(args.ids))!=3:raise ValueError('Choose three distinct question IDs.')
        if not args.name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in args.name):raise ValueError('Use letters, digits, hyphens or underscores for the episode name.')
        lookup={q['id']:q for q in local_items()};questions=[]
        for qid in args.ids:
            if qid not in lookup:raise ValueError(f'Question ID {qid} is not in the local snapshot.')
            q=lookup[qid];validate_question(q)
            questions.append({'text':q['text'],'options':q['options'],'answer_index':q['correctIndex'],'explanation':q['correctAnswer'],'bank_question_id':qid,'source_url':'https://quiz.farjadsamaneh.ir/api/v1/questions/'+qid})
        result={'id':args.name,'category':args.category,'hook':questions[0]['text'],'questions':questions,'hashtags':['کوییز','بازی_فکری']}
        destination=ROOT/'episodes'/f'{args.name}.json'
        if destination.exists():raise FileExistsError('That episode already exists; use a new name.')
        destination.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print('Created '+str(destination))

if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError,FileNotFoundError,FileExistsError) as exc:raise SystemExit(str(exc))
