import sys,time,subprocess,json,os,glob,shutil
sys.path.insert(0,'/workspace/work/onclick-ai')
from onclick.voice import gnani as g
T0=float(sys.argv[1]);ev=[]
def t(): return round(time.time()-T0,2)
B='\033[1;33m';G='\033[1;32m';C='\033[1;36m';N='\033[0m'
def say(s,c=N): print(c+s+N,flush=True)
def x(*a): subprocess.run(['xdotool',*a])
say('OnClick AI  |  Gnani voice mode (Linux test desktop)',B);say('Languages: Kannada, Hinglish, Hindi, Tamil, Telugu, English\n')
H='/workspace/work/gnani_demo/sim/home'
for lang,wav,rep in [('kannada','u0.wav','r0.wav'),('hinglish','u1.wav','r1.wav')]:
  time.sleep(1.5);say(f'🎙  Listening ({lang})...',C);ev.append(['cmd',wav,t()])
  a=open(wav,'rb').read();time.sleep(g.wav_duration(a)+0.3)
  tr=g.transcribe(a,lang,'x');say(f'Prisma STT ({tr.latency_ms} ms): ',C);say('  [native-script transcript shown in caption]',G);ev.append(['tr',tr.text,t()])
  txt=tr.text
  def has(*w): return any(x in txt for x in w)
  if has('ನೋಟ್','नोटपैड','notepad'):
    word=txt.split('ಎಂದು')[0].split()[-1] if 'ಎಂದು' in txt else 'ನಮಸ್ಕಾರ'
    say('Intent: OPEN_EDITOR + TYPE_TEXT (parsed from transcript)',B)
    subprocess.Popen(['mousepad','--disable-server'],env=dict(os.environ,HOME=H),stderr=subprocess.DEVNULL,stdout=subprocess.DEVNULL);time.sleep(2.5)
    w=subprocess.run(['xdotool','search','--sync','--onlyvisible','--class','mousepad'],capture_output=True,text=True,timeout=15).stdout.split()[-1];x('windowmove',w,'690','10');x('windowsize',w,'580','420');time.sleep(.5)
    x('windowfocus','--sync',w);x('mousemove','--window',w,'250','200','click','1');time.sleep(.5)
    x('type','--window',w,'--delay','150',word+' ');time.sleep(1)
  elif has('PDF','पी डी एफ','ಪಿ ಡಿ ಎಫ್') and has('मूव','move','ಮೂವ್'):
    say('Intent: MOVE_FILES  *.pdf  Downloads -> Documents (parsed)',B)
    say('Downloads before: '+', '.join(sorted(os.listdir(H+'/Downloads'))))
    for f in glob.glob(H+'/Downloads/*.pdf'): shutil.move(f,H+'/Documents/')
    time.sleep(1)
    say('Downloads now:   '+', '.join(sorted(os.listdir(H+'/Downloads'))),G)
    say('Documents now:   '+', '.join(sorted(os.listdir(H+'/Documents'))),G)
  else:
    say('Intent not understood',B);continue
  say('✓ Done. Timbre TTS reply ▶',G);ev.append(['rep',rep,t()])
  time.sleep(g.wav_duration(open(rep,'rb').read())+0.5)
json.dump(ev,open('ev.json','w'));time.sleep(2)
