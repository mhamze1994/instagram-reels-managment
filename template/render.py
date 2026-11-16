"""Deterministic 39-second Persian quiz-reel template. No online services required to render."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'vendor'))
import argparse, json, math, os, random, re, shutil, subprocess, hashlib
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display

DIGITS=str.maketrans('0123456789','۰۱۲۳۴۵۶۷۸۹')
def persian_number(value):return str(value).translate(DIGITS)
def shape(text):return get_display(arabic_reshaper.reshape(str(text)))

def find_ffmpeg():
    local=ROOT/'tools.local.json'
    values=json.loads(local.read_text(encoding='utf-8')) if local.exists() else {}
    candidates=[os.environ.get('QUIZ_FFMPEG'),values.get('ffmpeg'),shutil.which('ffmpeg'),str(Path(os.environ.get('ProgramFiles','C:/Program Files'))/'KMPlayer 64X/LAVFilters64/ffmpeg.exe')]
    for value in candidates:
        if value and Path(value).is_file():return str(Path(value).resolve())
    raise ValueError('Set QUIZ_FFMPEG or the ffmpeg path in tools.local.json.')

class Renderer:
    def __init__(self,episode,theme):
        self.episode=episode;self.theme=theme;self.colors=theme['palette'];self.timing=theme['timing']
        self.width=720;self.height=1560;self.fps=int(theme['fps'])
        if (theme['width'],theme['height'])!=(720,1560):raise ValueError('This layout uses 720x1560 coordinates.')
        self.period=float(self.timing['question_seconds']);self.duration=self.period*3+float(self.timing['comment_seconds'])
        if self.period!=12 or self.duration!=39 or self.timing['cta_start']!=24:
            raise ValueError('The recovered approved mix is locked to 39 seconds with CTA at 24 seconds. Supply a new timed audio mix before changing these cues.')
        self.questions=episode.get('questions',[])
        if len(self.questions)!=3:raise ValueError('An episode must contain exactly three questions.')
        for q in self.questions:
            if not isinstance(q.get('options'),list) or len(q['options'])!=4 or len(set(q['options']))!=4:raise ValueError('Each question needs four distinct options.')
            if type(q.get('answer_index')) is not int or q['answer_index'] not in range(4):raise ValueError('answer_index must be an integer from 0 to 3.')
            if not q.get('lines') and not q.get('text'):raise ValueError('Provide question lines or text.')
            q['lines']=q.get('lines') or self.wrap_question(q['text'])
            if len(q['lines'])>2:raise ValueError('Use no more than two question lines.')
        self.background=Image.new('RGBA',(720,1560),self.colors['background'])
        draw=ImageDraw.Draw(self.background);rng=random.Random(31)
        for _ in range(43):
            x=rng.randrange(720);y=rng.randrange(1560);r=rng.choice([1,1,2])
            draw.ellipse((x-r,y-r,x+r,y+r),fill=rng.choice(['#3d284f','#482d5a','#281a36']))
        self.avatar=Image.open(ROOT/theme['avatar']).convert('RGBA');self.avatar.thumbnail((90,94),Image.Resampling.LANCZOS)
        self.logo=Image.open(ROOT/theme['logo']).convert('RGBA').resize((198,198),Image.Resampling.LANCZOS)
        self.headers=[self.make_header(score) for score in range(3)]
        self.content={}
        for qi,q in enumerate(self.questions):
            for state in ['normal','selected','revealed']:
                if qi==2 and state!='normal':continue
                self.content[(qi,state)]=self.make_content(qi,state)
        self.badges=[self.make_badge(i/self.fps) for i in range(math.ceil(self.timing['cta_entrance']*self.fps)+1)]
        self.ending=self.background.copy()
        self.put(self.ending,'جواب سؤال سوم چیه؟',360,720,49,self.colors['gold'],max_width=670)
        self.put(self.ending,'تو کامنتا بنویس',360,810,53,'white',max_width=670)

    @lru_cache(maxsize=256)
    def font(self,size,latin=False):
        path=ROOT/self.theme['font']
        if latin:
            alternate=Path(self.theme.get('latin_font','C:/Windows/Fonts/tahoma.ttf'))
            if alternate.exists():path=alternate
        return ImageFont.truetype(str(path),int(size))

    @lru_cache(maxsize=2048)
    def text_image(self,text,size,color,max_width):
        visual=shape(text);latin=bool(re.search('[A-Za-z]',text))
        minimum=max(24,math.ceil(size*0.70))
        for current in range(size,minimum-1,-1):
            font=self.font(current,latin);bounds=font.getbbox(visual)
            if bounds[2]-bounds[0]<=max_width:break
        else:raise ValueError('Text is too long for this layout; shorten the wording: '+text)
        left,top,right,bottom=bounds
        image=Image.new('RGBA',(max(1,right-left)+12,max(1,bottom-top)+10))
        ImageDraw.Draw(image).text((6-left,5-top),visual,font=font,fill=color)
        return image

    def put(self,image,text,x,y,size,color='white',max_width=660,align='center'):
        glyph=self.text_image(str(text),int(size),color,int(max_width))
        left=x-glyph.width/2 if align=='center' else x-glyph.width+6
        image.alpha_composite(glyph,(round(left),round(y-glyph.height/2)))

    def wrap_question(self,text):
        words=text.split()
        if len(words)<2:return [text,'']
        font=self.font(44,bool(re.search('[A-Za-z]',text)))
        candidates=[]
        for split in range(1,len(words)):
            lines=[' '.join(words[:split]),' '.join(words[split:])]
            widths=[font.getlength(shape(line)) for line in lines]
            candidates.append((max(widths)+abs(widths[0]-widths[1])*0.18,lines))
        return min(candidates,key=lambda c:c[0])[1]

    def make_header(self,score):
        image=Image.new('RGBA',(720,1560));d=ImageDraw.Draw(image)
        d.ellipse((30,60,100,130),fill='#21172d',outline='#42324d')
        d.line((50,81,80,111),fill='white',width=5);d.line((80,81,50,111),fill='white',width=5)
        d.rounded_rectangle((505,61,690,127),radius=34,fill='#241830',outline='#493452')
        d.ellipse((650,79,679,109),fill=self.colors['gold'])
        self.put(image,persian_number(5200),577,95,30,self.colors['gold'],max_width=118)
        d.rounded_rectangle((365,188,690,339),radius=28,fill='#241830',outline='#493452')
        image.alpha_composite(self.avatar,(638-self.avatar.width//2,267-self.avatar.height//2))
        self.put(image,'شما',540,230,35,max_width=105)
        self.put(image,'سطح ۳',531,268,31,'#aaa0b8',max_width=130)
        self.put(image,'امتیاز '+persian_number(score),529,306,29,self.colors['gold'],max_width=145)
        return image

    def make_content(self,qi,state):
        image=Image.new('RGBA',(720,1560));d=ImageDraw.Draw(image);q=self.questions[qi]
        self.put(image,'سؤال '+persian_number(qi+1)+' از ۳',360,395,35,max_width=320)
        for j,x in enumerate([306,360,414]):
            d.ellipse((x-8,447,x+8,463),fill=self.colors['gold'] if j==2-qi else '#71528c')
        self.put(image,q['lines'][0],360,707,44,max_width=658)
        self.put(image,q['lines'][1] if len(q['lines'])>1 else '',360,758,44,max_width=658)
        self.put(image,self.episode.get('category','اطلاعات عمومی'),360,813,29,self.colors['muted'],max_width=655)
        for j,answer in enumerate(q['options']):
            y=855+j*115;selected=state in ['selected','revealed'] and j==q['answer_index'];revealed=selected and state=='revealed'
            fill=self.colors['correct'] if revealed else '#352345' if selected else self.colors['panel']
            border=self.colors['green'] if revealed else self.colors['gold'] if selected else self.colors['border']
            d.rounded_rectangle((30,y+5,690,y+104),radius=20,fill=fill,outline=border,width=3 if selected else 1)
            d.rounded_rectangle((610,y+29,665,y+80),radius=14,fill=self.colors['green'] if revealed else '#3a2b49')
            self.put(image,['الف','ب','ج','د'][j],637.5,y+54.5,28,max_width=47)
            self.put(image,answer,580,y+54.5,39,max_width=465,align='right')
            if revealed:d.line([(61,y+56),(69,y+64),(83,y+45)],fill=self.colors['green'],width=4)
        if qi==2:
            self.put(image,'جواب سؤال سوم چیه؟',360,1350,39,self.colors['gold'])
            self.put(image,'تو کامنتا بنویس',360,1415,39)
        elif state=='revealed':
            self.put(image,'درست جواب دادی! ۱ امتیاز گرفتی.',360,1342,29,self.colors['green'])
            explanation=q.get('explanation') or q['options'][q['answer_index']]
            self.put(image,explanation,360,1390,25,max_width=660)
        return image

    def make_badge(self,elapsed):
        layer=Image.new('RGBA',(300,320));progress=min(1,max(0,elapsed/self.timing['cta_entrance']))
        if progress<=0:return layer
        ease=1-(1-progress)**3;size=max(1,round(198*ease))
        logo=self.logo.resize((size,size),Image.Resampling.LANCZOS).rotate(-180*(1-ease),Image.Resampling.BICUBIC,expand=True)
        logo.putalpha(logo.getchannel('A').point(lambda alpha:round(alpha*progress)))
        layer.alpha_composite(logo,((300-logo.width)//2,110-logo.height//2))
        text=Image.new('RGBA',(300,105))
        self.put(text,'لینک دانلود',150,32,33,self.colors['gold'],max_width=280)
        self.put(text,'داخل بیو',150,76,32,max_width=280)
        text.putalpha(text.getchannel('A').point(lambda alpha:round(alpha*progress)))
        layer.alpha_composite(text,(0,218))
        return layer

    def frame(self,index):
        t=index/self.fps
        if t>=36:return self.ending.convert('RGB')
        qi=min(2,int(t//self.period));local=t-qi*self.period
        state='revealed' if qi<2 and local>=self.timing['reveal_at'] else 'selected' if qi<2 and local>=self.timing['selection_at'] else 'normal'
        score=qi+(state=='revealed');image=self.background.copy();image.alpha_composite(self.headers[min(2,score)])
        # The hook question and all four options are fully visible at frame zero.
        entrance=1.0 if qi==0 else min(1,max(0,local/.20))
        fade=min(entrance,max(0,(12-local)/.25))
        content=self.content[(qi,state)]
        if fade<1:
            content=content.copy();content.putalpha(content.getchannel('A').point(lambda a:round(a*fade)))
        image.alpha_composite(content)
        timer_layer=Image.new('RGBA',(720,1560));d=ImageDraw.Draw(timer_layer)
        remaining=max(0,self.timing['countdown_seconds']-max(0,local-self.timing['countdown_start']))
        d.rounded_rectangle((30,512,690,524),radius=6,fill='#48344f')
        length=660*remaining/self.timing['countdown_seconds']
        if length>1:d.rounded_rectangle((30,512,round(30+length),524),radius=6,fill=self.colors['green'])
        d.ellipse((315,552,405,642),outline=self.colors['green'] if remaining else '#493452',width=4)
        self.put(timer_layer,persian_number(math.ceil(remaining)),360,598,43,self.colors['green'] if remaining else '#71528c',max_width=75)
        if fade<1:timer_layer.putalpha(timer_layer.getchannel('A').point(lambda a:round(a*fade)))
        image.alpha_composite(timer_layer)
        if 24<=t<36:
            badge_index=min(len(self.badges)-1,round((t-24)*self.fps))
            image.alpha_composite(self.badges[badge_index],(5,105))
        return image.convert('RGB')

    def cover(self):
        image=Image.new('RGBA',(1080,1920),self.colors['background']);d=ImageDraw.Draw(image)
        d.rounded_rectangle((70,375,1010,690),radius=44,fill='#2b183c',outline=self.colors['gold'],width=3)
        q=self.questions[0]
        self.put(image,q['lines'][0],540,480,73,max_width=880)
        self.put(image,q['lines'][1] if len(q['lines'])>1 else '',540,594,73,self.colors['gold'],max_width=880)
        for j,answer in enumerate(q['options']):
            y=755+j*185;d.rounded_rectangle((70,y,1010,y+145),radius=34,fill='#2b183c',outline='#624879',width=2)
            self.put(image,answer,540,y+72.5,73,max_width=850)
        return image.convert('RGB')

    def save_previews(self,folder):
        times=[0,10,13,22,23.9,24.15,25,34,38]
        sheet=Image.new('RGB',(720,3*545),'#140920');draw=ImageDraw.Draw(sheet)
        for i,t in enumerate(times):
            im=self.frame(round(t*self.fps));im.save(folder/f'frame-{t:g}.png')
            x=(i%3)*240;y=(i//3)*545
            sheet.paste(im.resize((240,520)),(x,y+25));draw.text((x+8,y+7),f'{t:g}s',fill='white')
        sheet.save(folder/'contact-sheet.png')
        self.cover().save(folder/'cover.png')

def render_video(renderer,folder,start,end):
    ff=find_ffmpeg();first=round(start*renderer.fps);last=round(end*renderer.fps)
    filename='video.mp4' if start==0 and end==renderer.duration else f'clip-{start:g}-{end:g}.mp4'
    destination=folder/filename;audio=ROOT/renderer.theme['audio'];duration=(last-first)/renderer.fps
    command=[ff,'-nostdin','-y','-f','rawvideo','-pix_fmt','rgb24','-s','720x1560','-r',str(renderer.fps),'-i','-']
    if start>0:command+=['-ss',str(start)]
    command+=['-i',str(audio),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','fast','-crf','19','-pix_fmt','yuv420p']
    if start==0 and end==renderer.duration:command+=['-c:a','copy']
    else:command+=['-af',f'atrim=duration={duration},asetpts=PTS-STARTPTS','-c:a','aac','-b:a','192k']
    command+=['-movflags','+faststart',str(destination)]
    with (folder/'render.log').open('w',encoding='utf-8') as log:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log)
        try:
            for index in range(first,last):
                process.stdin.write(renderer.frame(index).tobytes())
                if (index-first)%(renderer.fps*4)==0:print(f'Rendered {(index-first)/renderer.fps:g}/{duration:g} seconds',flush=True)
        except BaseException:
            process.kill();process.wait();raise
        finally:
            if process.stdin:process.stdin.close()
        if process.wait()!=0:raise RuntimeError('FFmpeg encoding failed. See render.log.')
    check=subprocess.run([ff,'-v','error','-i',str(destination),'-f','null',os.devnull],capture_output=True,text=True)
    if check.returncode or check.stderr.strip():raise RuntimeError('Decode verification failed: '+check.stderr[:500])
    info=subprocess.run([ff,'-hide_banner','-i',str(destination)],capture_output=True,text=True).stderr
    (folder/'media-info.txt').write_text(info,encoding='utf-8')
    measured=float(re.search(r'Duration: 00:00:([\d.]+)',info)[1])
    if '720x1560' not in info or f'{renderer.fps} fps' not in info or 'Audio: aac' not in info or abs(measured-duration)>.06:raise RuntimeError('Unexpected output specifications. See media-info.txt.')
    report={'episode':renderer.episode['id'],'file':filename,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'duration_seconds':measured,'fps':renderer.fps,'dimensions':[720,1560],'source_interval_seconds':[start,end],'full_decode':'passed','question_3_revealed':False,'cta_start_seconds':24,'review_note':'Technical checks passed. Visual/motion/audio review is recorded separately in REVIEW.md.'}
    (folder/(destination.stem+'-validation.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Saved '+str(destination),flush=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('episode',nargs='?',default='episodes/example-literature.json')
    parser.add_argument('--preview',action='store_true',help='Write still frames/contact sheet and cover only.')
    parser.add_argument('--clip',nargs=2,type=float,metavar=('START','END'),help='Render a short representative interval, without changing playback speed.')
    parser.add_argument('--theme',default='theme.json')
    args=parser.parse_args()
    path=Path(args.episode);path=path if path.is_absolute() else ROOT/path
    episode=json.loads(path.read_text(encoding='utf-8-sig'))
    if not re.fullmatch(r'[A-Za-z0-9_-]+',episode.get('id','')):raise ValueError('Episode id may contain letters, digits, underscores or hyphens only.')
    theme=json.loads((ROOT/args.theme).read_text(encoding='utf-8-sig'))
    renderer=Renderer(episode,theme);folder=ROOT/'renders'/episode['id'];folder.mkdir(parents=True,exist_ok=True)
    renderer.save_previews(folder)
    hook=episode.get('hook') or ' '.join(renderer.questions[0]['lines'])
    caption=hook+'\n\nسه سؤال؛ چندتاش رو درست جواب می‌دی؟\nجواب دو سؤال اول رو ببین و جواب سؤال سوم رو تو کامنتا بنویس 👇\n\nخودت هم بازی کن! «کوییز آف ترونز | Quiz of thrones» رو از کافه بازار دانلود کن؛ لینک در بیو 🎮\n\n'+' '.join('#'+x for x in episode.get('hashtags',['کوییز','بازی_فکری']))+'\n'
    (folder/'caption.txt').write_text(caption,encoding='utf-8-sig')
    answers='کلید پاسخ خصوصی؛ این فایل در کپشن منتشر نشود.\n\n'+'\n'.join(f'{i}. {q["options"][q["answer_index"]]}' for i,q in enumerate(renderer.questions,1))
    (folder/'answers-private.txt').write_text(answers,encoding='utf-8-sig')
    (folder/'episode.json').write_text(json.dumps(episode,ensure_ascii=False,indent=2),encoding='utf-8')
    if args.preview:print('Preview, cover, caption and private answer key saved to '+str(folder));return
    start,end=args.clip or [0,renderer.duration]
    if not 0<=start<end<=renderer.duration:raise ValueError('Clip interval must be inside the 39-second timeline.')
    render_video(renderer,folder,start,end)

if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError,FileNotFoundError) as exc:raise SystemExit(str(exc))
