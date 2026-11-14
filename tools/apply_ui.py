#!/usr/bin/env python3
"""nanoMuse look-alike UI for UAM's chat page (run AFTER apply_features.py). Idempotent.
usage: apply_ui.py <UAM dir> <path to dragon-idle.webp>
Adds: dragon header + name pill, welcome screen (remembered), hero text + chips, side menu
(Main chat / Devices / Side chats / search / settings / files), Devices + Settings + Files sheets,
the postMessage handshake the phone module expects, and a service-worker fix for the new routes.
"""
import pathlib, re, shutil, sys

root = pathlib.Path(sys.argv[1])
dragon = pathlib.Path(sys.argv[2])
(root / "static" / "nanomuse").mkdir(parents=True, exist_ok=True)
shutil.copy(dragon, root / "static" / "nanomuse" / "dragon.webp")

html_p = root / "static" / "nanomuse.html"
h = html_p.read_text(encoding="utf-8")
if "/*ui2*/" in h:
    print("nanomuse.html: UI already applied")
else:
    def once(old, new):
        global h
        if h.count(old) != 1:
            sys.exit(f"apply_ui: expected 1 match for {old[:70]!r}, found {h.count(old)}")
        h = h.replace(old, new)

    # ---------------------------------------------------------------- CSS
    CSS = r"""/*ui2*/
:root{--bg:#fafafa;--card:#f0f0f2;--el:#fff}
@media(prefers-color-scheme:dark){:root{--bg:#0b0b0d;--card:#1c1c1f;--el:#17171a}}
header.top{display:flex;align-items:flex-start;justify-content:space-between;padding:10px 12px 0;border:0;position:relative;min-height:124px}
.rb{width:46px;height:46px;border-radius:50%;background:var(--el);box-shadow:0 1px 5px rgba(0,0,0,.1);display:flex;align-items:center;justify-content:center;padding:0;color:var(--fg)}
.who{position:absolute;left:50%;top:12px;transform:translateX(-50%);display:flex;flex-direction:column;align-items:center;pointer-events:none}
.who .av{width:74px;height:74px;margin:0;align-self:center;background:var(--card)}
.av img{width:100%;height:100%;object-fit:cover;display:block}
.pill{margin-top:-12px;background:var(--el);border-radius:16px;padding:3px 16px;box-shadow:0 1px 4px rgba(0,0,0,.1);font-size:15px;pointer-events:auto}
#status{display:block;margin-top:3px;font-size:11px;max-width:60vw}
footer>.tools{display:none}
#attach{width:42px;height:42px;border-radius:50%;background:var(--el);box-shadow:0 1px 4px rgba(0,0,0,.1);padding:0;font-size:22px;flex:none}
footer{border-top:0;background:var(--bg)}
textarea{background:var(--el);box-shadow:0 0 0 1px var(--line)}
.hero2{padding:34px 18px 20px;text-align:center}
.hero2 h1{font-size:27px;line-height:1.2;margin:0 0 14px}
.hero2 p{color:var(--mut);margin:0 auto 22px;max-width:30em}
.hero2 .chips{display:flex;flex-direction:column;align-items:center;gap:10px}
.hero2 .chips button{background:var(--card);border-radius:22px;padding:11px 18px;max-width:100%}
#dp{padding:calc(var(--sat) + 10px) 0 0;overflow:hidden;display:flex;flex-direction:column;width:88%;max-width:360px}
.dtop{padding:6px 12px}.dtop h2{margin:6px 6px 14px;font-size:26px}
.nav{display:flex;align-items:center;gap:14px;width:100%;text-align:left;padding:14px;border-radius:16px;font-size:18px}
.nav.on{background:var(--card)}.nav span{flex:1}.nav em{font-style:normal;color:var(--mut);font-size:15px}
.sec{padding:14px 20px 6px;color:var(--mut);font-size:16px}
.sc{flex:1;overflow-y:auto;padding:0 12px}
.sc .c{display:flex;align-items:center;border-radius:12px;padding:0 4px}.sc .c.on{background:var(--card)}
.sc .c span{flex:1;padding:11px 8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.empty{text-align:center;color:var(--mut);padding:90px 26px 0}.empty b{display:block;color:var(--fg);font-size:21px;margin:10px 0 6px}.empty p{margin:0}
.dbar{display:flex;align-items:center;gap:8px;padding:10px 12px calc(10px + var(--sab));border-top:1px solid var(--line);background:var(--bg)}
.ib{width:42px;height:42px;border-radius:50%;padding:0;display:flex;align-items:center;justify-content:center;flex:none}
.srch{flex:1;display:flex;align-items:center;gap:8px;background:var(--card);border-radius:22px;padding:0 14px;height:42px;color:var(--mut);min-width:0}
.srch input{flex:1;min-width:0;border:0;background:none;outline:0;font:inherit;color:var(--fg)}
.menu button{display:block;width:100%;text-align:left;background:var(--card);border-radius:14px;padding:13px 14px;margin:0 0 8px;font-size:16px}
.menu .cancel{text-align:center;color:var(--mut)}
#sheet .sg{margin:6px 0 12px}#sheet .sg h5{margin:10px 2px 6px;font-size:12px;color:var(--mut);text-transform:uppercase}
#sheet .tools{flex-wrap:wrap;gap:6px}
.drow{display:flex;align-items:center;gap:12px;padding:10px 4px}.drow .dot{width:10px;height:10px;border-radius:50%;background:#aaa}.drow .dot.on{background:#22c55e}
.drow b{display:block;font-weight:600}.drow small{color:var(--mut)}.drow.mut{opacity:.55}
.drow .tag{margin-left:auto;font-size:12px;color:var(--mut);border:1px solid var(--line);border-radius:10px;padding:1px 8px}
#sheet a.lnk{display:inline-block;margin:6px 4px;color:var(--acc)}
#welcome{position:fixed;inset:0;z-index:30;background:var(--bg);display:flex;flex-direction:column;padding:calc(var(--sat) + 24px) 22px calc(var(--sab) + 18px);overflow-y:auto}
#welcome .wc{flex:1}#welcome .av{width:104px;height:104px;margin:24px auto 18px;align-self:center}
#welcome h1{text-align:center;font-size:27px;margin:0 0 8px}#welcome .sub{text-align:center;color:var(--mut);margin:0 0 26px}
.feat{display:flex;gap:14px;margin:0 0 20px}.feat i{flex:none;width:46px;height:46px;border-radius:50%;background:var(--card);display:flex;align-items:center;justify-content:center;font-style:normal}
.feat b{display:block;font-weight:600}.feat span{color:var(--mut);font-size:15px}
#welcome .go{width:100%;background:var(--acc);color:#fff;border-radius:30px;padding:15px;font-size:18px;font-weight:600}
#welcome small{display:block;text-align:center;color:var(--mut);margin-top:12px}
"""
    once("</style>", CSS + "</style>")

    # ---------------------------------------------------------------- header + tools row
    h2, n = re.subn(r"<header>.*?</header>", lambda m: r"""<header class="top">
  <button id="menu" class="rb" aria-label="Menu"></button>
  <div class="who"><div class="av" id="hav"></div><div class="pill">nanoMuse</div><span id="status">ready</span></div>
  <button id="more" class="rb" aria-label="More"></button>
</header>""", h, count=1, flags=re.S)
    if n != 1:
        sys.exit("apply_ui: header not found")
    h = h2
    once('<div class="tools">', '<div class="tools" id="tools"><button id="lang" style="display:none" aria-hidden="true">中/EN</button>')

    # ---------------------------------------------------------------- avatar = dragon
    h, n = re.subn(r"const MARK='.*?';\n", lambda m: "const MARK='<img src=\"/static/nanomuse/dragon.webp\" alt=\"\">';\n", h, count=1, flags=re.S)
    if n != 1:
        sys.exit("apply_ui: MARK not found")

    # ---------------------------------------------------------------- strings
    STR = r"""Object.assign(T.en,{hi:"Hi, I'm nanoMuse.",intro:"I don't just answer, I get things done: research, plans, files, code and your phone's apps. Everything I do shows up here, and anything hard to undo waits for your approval.",
 chips:['What can you do for me?',"Plan my week: ask me what's on my plate",'Research and compare two options for me','Remember: I have an iced americano every morning','Open the calculator on the phone and work out 12 × 8','Change your look to an orange cat with round glasses'],
 mainchat:'Main chat',devices:'Devices',sidechats:'Side chats',sc_t:'Start a side chat',sc_s:'Side chats are an optional way to keep conversations organised by topic.',nores:'No matches',nores_s:'Try another word.',search:'Search',settings:'Settings',files:'Files',filesnone:'Files the agent makes will show up here.',model:'Model & tools',on:'On',off:'Off',close:'Close',newside:'New side chat',skills:'Skills',lng:'Language',
 welcomeT:'Welcome to nanoMuse',welcomeS:'An open-source personal agent for every device you own.',w1t:'Chat, pictures, video',w1d:'A capable model, image and video generation, tools, skills and memory.',w2t:'Hands: it uses your phone',w2d:'It taps through apps on the phone for you. You watch, and can stop it any time.',w3t:'Reach: your computers',w3d:'Pair a Mac, Windows or Linux machine. Coming soon.',start:'Start',local:'Your chats stay on this device.',
 thisphone:'Simulated phone',conn:'Connected',notconn:'Not connected',openphone:'Open the simulated phone',pair:'Pair a device',soon:'Coming soon',iphone:'iPhone or iPad',android:'Android phone',computer:'Mac, Windows or Linux'});
Object.assign(T.zh,{hi:'你好，我是 nanoMuse。',intro:'我不只是回答，我会把事情办成：研究、计划、文件、代码，还有手机上的应用。我做的一切都会显示在这里，难以撤销的操作会先等你批准。',
 chips:['你能为我做什么？','帮我规划这一周：先问问我手头有什么','帮我研究并比较两个选择','记住：我每天早上喝一杯冰美式','在手机上打开计算器，算一下 12 × 8','换个形象：一只戴圆框眼镜的橘猫'],
 mainchat:'主对话',devices:'设备',sidechats:'侧边对话',sc_t:'开始一个侧边对话',sc_s:'侧边对话可以按主题整理你的对话，可选。',nores:'没有结果',nores_s:'换个词试试。',search:'搜索',settings:'设置',files:'文件',filesnone:'智能体生成的文件会显示在这里。',model:'模型与工具',on:'开',off:'关',close:'关闭',newside:'新的侧边对话',skills:'技能',lng:'语言',
 welcomeT:'欢迎使用 nanoMuse',welcomeS:'为你所有设备准备的开源个人智能体。',w1t:'聊天、图片、视频',w1d:'强大的模型、图像与视频生成、工具、技能和记忆。',w2t:'双手：它会用你的手机',w2d:'它替你在手机的应用里点按操作，你全程可见，随时可以叫停。',w3t:'触达：你的电脑',w3d:'配对 Mac、Windows 或 Linux 电脑。即将推出。',start:'开始',local:'你的对话保存在这台设备上。',
 thisphone:'模拟手机',conn:'已连接',notconn:'未连接',openphone:'打开模拟手机',pair:'配对设备',soon:'即将推出',iphone:'iPhone 或 iPad',android:'Android 手机',computer:'Mac、Windows 或 Linux'});
"""
    once("const tr=k=>T[lang][k];\n", "const tr=k=>T[lang][k];\n" + STR)

    # ---------------------------------------------------------------- hero (empty state)
    a = h.index("if(!c.messages.length&&!c.turn){const h=document.createElement('div');h.className='hero';")
    endm = "chat.appendChild(h);busyUI();return}"
    b = h.index(endm, a) + len(endm)
    HERO = r"""if(!c.messages.length&&!c.turn){const h=document.createElement('div');h.className='hero2';h.innerHTML='<h1></h1><p></p><div class="chips"></div>';
    h.children[0].textContent=tr('hi');h.children[1].textContent=tr('intro');
    for(const q of tr('chips')){const b=document.createElement('button');b.textContent=q;b.onclick=()=>{inp.value=q;grow();send()};h.children[2].appendChild(b)}
    chat.appendChild(h);busyUI();return}"""
    h = h[:a] + HERO + h[b:]

    # ---------------------------------------------------------------- newChat: never reuse the main chat
    once("const f=convs[0];if(f&&!f.messages.length&&!f.turn){cur=f}",
         "const f=convs[0];if(f&&!f.main&&!f.messages.length&&!f.turn){cur=f}")

    # ---------------------------------------------------------------- drawer + sheets (replaces old drawer())
    a = h.index("function drawer(open){")
    endm = "$('menu').onclick=()=>drawer();"
    b = h.index(endm, a)
    NEW = r"""const IC={menu:'<path d="M4 7h16M4 12h16M4 17h16"/>',dots:'<circle cx="5" cy="12" r="1.5" fill="currentColor"/><circle cx="12" cy="12" r="1.5" fill="currentColor"/><circle cx="19" cy="12" r="1.5" fill="currentColor"/>',
 home:'<path d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z"/>',dev:'<rect x="3" y="4" width="13" height="10" rx="1.5"/><path d="M7 18h5M9.5 14v4"/><rect x="17.5" y="9" width="3.5" height="9" rx="1"/>',
 gear:'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
 doc:'<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h6"/>',search:'<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/>',edit:'<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
 bubble:'<path d="M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H11l-5 4v-4H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z"/>',chat:'<path d="M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H11l-5 4v-4H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z"/>',
 hand:'<path d="M8 12V6a1.5 1.5 0 0 1 3 0v5M11 11V4.5a1.5 1.5 0 0 1 3 0V11M14 11V6a1.5 1.5 0 0 1 3 0v8c0 4-2.5 6-6 6s-5-2-6-5l-1.5-3.5a1.5 1.5 0 0 1 2.6-1.4L8 14"/>',
 mon:'<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>'};
const ic=(n,s)=>'<svg viewBox="0 0 24 24" width="'+(s||22)+'" height="'+(s||22)+'" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">'+IC[n]+'</svg>';
$('menu').innerHTML=ic('menu');$('more').innerHTML=ic('dots');
const mainChat=()=>convs.find(c=>c.main)||convs[convs.length-1];
const toolsEl=$('tools');
const footerTools=()=>{toolsEl.style.display='';document.querySelector('footer').appendChild(toolsEl)};
let dq='';
function sideList(box){
  box.innerHTML='';const q=dq.trim().toLowerCase();
  const list=convs.filter(c=>!c.main).filter(c=>!q||(c.title||'').toLowerCase().includes(q)||c.messages.some(m=>(m.content||'').toLowerCase().includes(q))).slice(0,60);
  if(!list.length){box.innerHTML='<div class="empty">'+ic('bubble',38)+'<b></b><p></p></div>';box.querySelector('b').textContent=tr(q?'nores':'sc_t');box.querySelector('p').textContent=tr(q?'nores_s':'sc_s');return}
  for(const c of list){
    const r=document.createElement('div');r.className='c'+(c===cur?' on':'');
    r.innerHTML='<span></span><button aria-label="Delete">🗑</button>';r.firstChild.textContent=c.title||'Untitled';
    r.firstChild.onclick=()=>openChat(c.id);
    r.lastChild.onclick=async()=>{if(!confirm('Delete this chat?'))return;
      convs=convs.filter(x=>x!==c);
      const keys=await tx('files','readonly',o=>o.getAllKeys()).catch(()=>[]);
      for(const k of keys||[])if(String(k).startsWith(c.id+'/'))kdel('files',k).catch(()=>{});
      if(c===cur){cur=mainChat();ls.set('nm.cur',cur.id);paintAll(cur)}await flush0();sideList(box)};
    box.appendChild(r);
  }
}
const devStatus=()=>fetch('/phone/status?token='+encodeURIComponent(phoneToken())).then(r=>r.json()).catch(()=>({connected:false,apps:[]}));
function drawer(open){
  const d=$('drawer');if(open===false||open===undefined&&d.classList.contains('open')){d.classList.remove('open');return}
  const p=$('dp');p.innerHTML='';
  const top=document.createElement('div');top.className='dtop';top.innerHTML='<h2>nanoMuse</h2>';
  const mk=(icon,label,right,on,fn)=>{const b=document.createElement('button');b.className='nav'+(on?' on':'');b.innerHTML=ic(icon)+'<span></span><em></em>';b.children[1].textContent=label;b.children[2].textContent=right||'';b.onclick=fn;return b};
  const m=mainChat();
  top.appendChild(mk('home',tr('mainchat'),'',cur===m,()=>{if(m)openChat(m.id)}));
  const dev=mk('dev',tr('devices'),'',false,()=>{drawer(false);openDevices()});top.appendChild(dev);
  devStatus().then(s=>{dev.children[2].textContent=s.connected?tr('on'):tr('off')});
  p.appendChild(top);
  const sec=document.createElement('div');sec.className='sec';sec.textContent=tr('sidechats');p.appendChild(sec);
  const box=document.createElement('div');box.className='sc';p.appendChild(box);sideList(box);
  const bar=document.createElement('div');bar.className='dbar';
  bar.innerHTML='<button class="ib" aria-label="Settings"></button><button class="ib" aria-label="Files"></button><label class="srch"></label><button class="ib" aria-label="New side chat"></button>';
  bar.children[0].innerHTML=ic('gear');bar.children[1].innerHTML=ic('doc');bar.children[3].innerHTML=ic('edit');
  const sl=bar.children[2];sl.innerHTML=ic('search',18)+'<input type="search" enterkeyhint="search">';const si=sl.querySelector('input');si.placeholder=tr('search');si.value=dq;
  si.oninput=()=>{dq=si.value;sideList(box)};
  bar.children[0].onclick=openSettings;bar.children[1].onclick=openFiles;bar.children[3].onclick=newChat;
  p.appendChild(bar);d.classList.add('open');
}
function saveBlob(name,blob){const file=new File([blob],name,{type:blob.type||'application/octet-stream'});
  const dlf=()=>{const u=URL.createObjectURL(file),a=document.createElement('a');a.href=u;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(u),3e4)};
  if(navigator.canShare?.({files:[file]}))navigator.share({files:[file]}).catch(e=>{if(e.name!=='AbortError')dlf()});else dlf()}
async function openFiles(){
  drawer(false);let keys=[];try{keys=(await tx('files','readonly',o=>o.getAllKeys()))||[]}catch{}
  sheet((p,done)=>{
    p.innerHTML='<h4></h4><div id="fl"></div><div class="b"><button class="ok"></button></div>';
    p.querySelector('h4').textContent=tr('files');const fl=p.querySelector('#fl');
    if(!keys.length){const n=document.createElement('p');n.style.color='var(--mut)';n.textContent=tr('filesnone');fl.appendChild(n)}
    for(const k of keys.slice(-60).reverse()){const name=String(k).split('/').slice(1).join('/')||String(k);
      const r=document.createElement('div');r.className='file';r.innerHTML='<span></span><button>Save</button>';r.firstChild.textContent=name;
      r.lastChild.onclick=async()=>{const blob=await kget('files',k).catch(()=>null);if(!blob){toast('Not available');return}saveBlob(name,blob)};fl.appendChild(r)}
    const ok=p.querySelector('.ok');ok.textContent=tr('close');ok.onclick=()=>done(true)});
}
async function openDevices(){
  const s=await devStatus();
  sheet((p,done)=>{
    p.innerHTML='<h4></h4><div id="dv"></div><div class="b"><button class="ok"></button></div>';p.querySelector('h4').textContent=tr('devices');
    const dv=p.querySelector('#dv');
    const row=(title,sub,on,tag,mut)=>{const r=document.createElement('div');r.className='drow'+(mut?' mut':'');r.innerHTML='<i class="dot'+(on?' on':'')+'"></i><div><b></b><small></small></div>'+(tag?'<span class="tag"></span>':'');
      r.querySelector('b').textContent=title;r.querySelector('small').textContent=sub;if(tag)r.querySelector('.tag').textContent=tag;dv.appendChild(r)};
    row(tr('thisphone'),s.connected?tr('conn')+' · '+(s.apps||[]).length+' apps':tr('notconn'),s.connected,'');
    if(!s.connected&&window.top===window){const a=document.createElement('a');a.className='lnk';a.href='/phone';a.textContent=tr('openphone')+' →';dv.appendChild(a)}
    const h5=document.createElement('h5');h5.style.cssText='margin:16px 2px 4px;font-size:12px;color:var(--mut);text-transform:uppercase';h5.textContent=tr('pair');dv.appendChild(h5);
    row(tr('iphone'),tr('soon'),false,'',true);row(tr('android'),tr('soon'),false,'',true);row(tr('computer'),tr('soon'),false,'',true);
    const ok=p.querySelector('.ok');ok.textContent=tr('close');ok.onclick=()=>done(true)});
}
function openSettings(){
  drawer(false);
  sheet((p,done)=>{
    const close=()=>{footerTools();done(true)};
    const render=()=>{
      p.innerHTML='<h4></h4><div class="set"></div><div class="b"><button class="ok"></button></div>';p.querySelector('h4').textContent=tr('settings');
      const s=p.querySelector('.set');
      const g=document.createElement('div');g.className='sg';g.innerHTML='<h5></h5>';g.firstChild.textContent=tr('model');toolsEl.style.display='flex';g.appendChild(toolsEl);s.appendChild(g);
      const lg=document.createElement('div');lg.className='sg';lg.innerHTML='<h5></h5><button class="chip" style="font-size:14px"></button>';lg.firstChild.textContent=tr('lng');lg.lastChild.textContent=lang==='zh'?'中文 → English':'English → 中文';
      lg.lastChild.onclick=()=>{$('lang').click();render()};s.appendChild(lg);
      const mg=document.createElement('div');mg.className='sg';const mh=document.createElement('h5');mh.textContent=tr('mem')+' ('+mem.length+')';mg.appendChild(mh);
      if(!mem.length){const n=document.createElement('div');n.className='mem';n.innerHTML='<span></span>';n.firstChild.textContent=tr('none');mg.appendChild(n)}
      for(const m of mem){const r=document.createElement('div');r.className='mem';r.innerHTML='<span></span><button>×</button>';r.firstChild.textContent=m.text;
        r.lastChild.onclick=async()=>{mem=mem.filter(x=>x!==m);await kput('kv','mem',mem);render()};mg.appendChild(r)}
      s.appendChild(mg);
      const kg=document.createElement('div');kg.className='sg';
      const sh=document.createElement('h5');sh.textContent='Skills ('+skills.length+')';kg.appendChild(sh);
      for(const k of skills){const r=document.createElement('div');r.className='mem';r.innerHTML='<span></span><button>×</button>';r.firstChild.textContent=k.text;
        r.lastChild.onclick=async()=>{skills=skills.filter(x=>x!==k);await kput('kv','skills',skills);render()};kg.appendChild(r)}
      {const r=document.createElement('div');r.className='mem';r.innerHTML='<input maxlength="600" placeholder="Teach it a skill, e.g. when I say book a ride, ask my budget first" style="flex:1;min-width:0;background:transparent;color:inherit;border:1px solid var(--mut);border-radius:8px;padding:6px;font:inherit"><button>+</button>';
        const add=async()=>{const t=r.firstChild.value.trim();if(!t)return;skills.push({id:uid(),text:t.slice(0,600)});await kput('kv','skills',skills);render()};
        r.lastChild.onclick=add;r.firstChild.onkeydown=e=>{if(e.key==='Enter')add()};kg.appendChild(r)}
      s.appendChild(kg);
      const ok=p.querySelector('.ok');ok.textContent=tr('close');ok.onclick=close;
    };
    render();
  });
}
$('more').onclick=()=>sheet((p,done)=>{p.innerHTML='<div class="menu"></div>';const m=p.firstChild;
  const add=(label,fn)=>{const b=document.createElement('button');b.textContent=label;b.onclick=()=>{done(true);fn()};m.appendChild(b)};
  add(tr('newside'),newChat);add(tr('devices'),openDevices);add(tr('settings'),openSettings);add(lang==='zh'?'English':'中文',()=>{$('lang').click()});
  const c=document.createElement('button');c.className='cancel';c.textContent=tr('close');c.onclick=()=>done(true);m.appendChild(c)});
function welcome(){
  if(ls.get('nm.welcomed',false))return;
  const w=document.createElement('div');w.id='welcome';
  w.innerHTML='<div class="wc"><div class="av"></div><h1></h1><p class="sub"></p><div class="feats"></div></div><div class="wf"><button class="go"></button><small></small></div>';
  w.querySelector('.av').innerHTML=MARK;w.querySelector('h1').textContent=tr('welcomeT');w.querySelector('.sub').textContent=tr('welcomeS');
  for(const[i,t,d]of[['chat','w1t','w1d'],['hand','w2t','w2d'],['mon','w3t','w3d']]){const f=document.createElement('div');f.className='feat';f.innerHTML='<i></i><div><b></b><span></span></div>';
    f.firstChild.innerHTML=ic(i);f.querySelector('b').textContent=tr(t);f.querySelector('span').textContent=tr(d);w.querySelector('.feats').appendChild(f)}
  const go=w.querySelector('.go');go.textContent=tr('start');w.querySelector('small').textContent=tr('local');
  go.onclick=()=>{ls.set('nm.welcomed',true);w.remove();hello()};document.body.appendChild(w);
}
/* the phone module's handshake: it waits for nanomuse:ready (and hands over drafts / the colour scheme) */
const themeNow=()=>matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';
function hello(){try{if(parent!==window)parent.postMessage({type:'nanomuse:ready',name:'nanoMuse',theme:themeNow()},location.origin)}catch{}}
try{matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{try{if(parent!==window)parent.postMessage({type:'nanomuse:theme',theme:themeNow()},location.origin)}catch{}})}catch{}
addEventListener('message',e=>{const d=e.data;if(!d||d.type!=='nanomuse:draft'||parent===window||e.source!==parent)return;inp.value=String(d.text||'').slice(0,4000);grow();inp.focus()});
"""
    h = h[:a] + NEW + h[b:]

    # ---------------------------------------------------------------- boot: main chat, avatar, welcome, ready
    once("  applyLang();tick();\n", "  applyLang();tick();applyLook();welcome();\n")
    once("  if(!convs.length)newChat();\n  else{cur=convs.find(c=>c.id===ls.get('nm.cur',''))||convs[0];paintAll(cur)}\n",
         "  {let mc=convs.find(c=>c.main);if(!mc){mc=convs[convs.length-1];if(mc)mc.main=true;else{mc={id:uid(),title:'Main chat',messages:[],turn:null,run:null,extra:[],main:true};convs.push(mc)}}\n"
         "   cur=convs.find(c=>c.id===ls.get('nm.cur',''))||mc;ls.set('nm.cur',cur.id);paintAll(cur)}\n")
    once("  busyUI();\n})();\n})();", "  busyUI();if(!document.getElementById('welcome'))hello();\n})();\n})();")
    html_p.write_text(h, encoding="utf-8")
    print("nanomuse.html: UI applied")

# ---------------------------------------------------------------- service worker: new routes are never cached
sw_p = root / "static" / "sw.js"
sw = sw_p.read_text(encoding="utf-8")
if "'/phone/'" in sw:
    print("sw.js: already patched")
else:
    if sw.count("'/selftest'];") != 1 or "agent-shell-v2" not in sw:
        sys.exit("apply_ui: sw.js layout changed")
    sw = sw.replace("'/selftest'];", "'/selftest', '/phone/', '/ws'];").replace("agent-shell-v2", "agent-shell-v3")
    sw_p.write_text(sw, encoding="utf-8")
    print("sw.js: patched")
