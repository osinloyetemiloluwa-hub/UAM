#!/usr/bin/env python3
"""Add Hands (phone control), Skills and phone-aware Memory to UAM's nanomuse. Idempotent.
usage: apply_features.py <UAM dir>     (expects main.py and static/nanomuse.html; phone_agent.py is copied next to it)
"""
import pathlib, shutil, sys

root = pathlib.Path(sys.argv[1])
here = pathlib.Path(__file__).parent
shutil.copy(here / "phone_agent.py", root / "phone_agent.py")


def patch(path, edits):
    p = root / path
    t = p.read_text(encoding="utf-8")
    for marker, old, new in edits:
        if marker in t:
            print(f"  already: {path}: {marker}")
            continue
        if t.count(old) != 1:
            sys.exit(f"apply_features: {path}: expected 1 match for {old[:60]!r}, found {t.count(old)}")
        t = t.replace(old, new)
        print(f"  patched: {path}: {marker}")
    p.write_text(t, encoding="utf-8")


# ---------------------------------------------------------------- main.py
patch("main.py", [
    ("skills: list[str]", "    memory: list[str] = []\n", "    memory: list[str] = []\n    skills: list[str] = []\n"),
    ('"phone_task"', '    _t("device_action",',
     '    _t("phone_task", "Operate the user\'s simulated phone (its apps) to do a task. Describe the goal in plain words, e.g. \'open Notes and add a note called Groceries\'. It returns what happened. If it returns NEEDS THE USER, ask the user that question in chat and only call again, saying they agreed, if they say yes.",\n'
     '       {"goal": S}, ["goal"]),\n    _t("device_action",'),
    ("operate its apps with phone_task", "You cannot control other apps. Use device_action",
     "You cannot control other apps on the user's real phone. When the user's simulated phone is open you can operate its apps with phone_task: give it one clear goal, never claim it succeeded unless the result says so, and for anything irreversible (paying, ordering, sending, deleting) tell the user first and wait for a yes. Use device_action"),
    ("Skills the user has added",
     '        if req.options.lang == "zh":\n',
     '        if req.options.skills:\n'
     '            sys_text += "\\n\\nSkills the user has added (follow them when relevant):\\n" + "\\n".join(\n'
     '                "- " + s[:600] for s in req.options.skills[-20:])\n'
     '        if req.options.lang == "zh":\n'),
    ("phone_agent.register", '@app.get("/phone")',
     'import phone_agent  # noqa: E402\n'
     'phone_agent.register(app, profiles=PROFILES, provider_by_name=PROVIDER_BY_NAME,\n'
     '                     clients=_CLIENTS, candidate_models=candidate_models)\n\n\n'
     '@app.get("/phone")'),
])

# ---------------------------------------------------------------- nanomuse.html
TOKEN_JS = ("const phoneToken=()=>{try{let t=localStorage.getItem('uam.phone.token');if(!t){"
            "t=Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');"
            "localStorage.setItem('uam.phone.token',t)}return t}catch{return ''}};\n")
PHONE_TOOL = """  if(ev.name==='phone_task'){
    const goal=String(a.goal||'').trim().slice(0,500);if(!goal)return 'Failed: no goal given.';
    const body=JSON.stringify({token:phoneToken(),call_id:ev.call_id,goal,memory:mem.map(m=>m.text),skills:skills.map(s=>s.text),profile});
    for(let i=0;i<40;i++){
      let j;try{const r=await fetch('/phone/task',{method:'POST',headers:{'Content-Type':'application/json'},body});j=await r.json()}catch{await sleep(1500);continue}
      if(j.status==='done')return 'Done: '+j.summary;
      if(j.status==='ask')return 'NEEDS THE USER: '+j.summary+' (Ask them in chat. Do not retry until they say yes.)';
      if(j.status==='stopped')return 'STOPPED: the user stopped the task on the phone. Do not retry.';
      if(j.status==='failed')return 'Failed: '+j.summary;
      status(j.steps&&j.steps.length?'phone: '+j.steps[j.steps.length-1]:'using the phone…');
    }
    return 'Failed: the phone task took too long.';
  }
"""
SKILLS_UI = """  const sh=document.createElement('h5');sh.textContent='Skills ('+skills.length+')';p.appendChild(sh);
  for(const s of skills){const r=document.createElement('div');r.className='mem';r.innerHTML='<span></span><button>×</button>';r.firstChild.textContent=s.text;
    r.lastChild.onclick=async()=>{skills=skills.filter(x=>x!==s);await kput('kv','skills',skills);drawer(true)};p.appendChild(r)}
  {const r=document.createElement('div');r.className='mem';r.innerHTML='<input maxlength="600" placeholder="Teach it a skill, e.g. When I say book a ride, always ask for a budget first" style="flex:1;min-width:0;background:transparent;color:inherit;border:1px solid var(--mut);border-radius:8px;padding:6px;font:inherit"><button>+</button>';
    const add=async()=>{const t=r.firstChild.value.trim();if(!t)return;skills.push({id:uid(),text:t.slice(0,600)});await kput('kv','skills',skills);drawer(true)};
    r.lastChild.onclick=add;r.firstChild.onkeydown=e=>{if(e.key==='Enter')add()};p.appendChild(r)}
"""
patch("static/nanomuse.html", [
    ("skills=[]", "let mem=[],rem=[]", "let mem=[],skills=[],rem=[]"),
    ("skills:skills.map", "memory:mem.map(m=>m.text),lang}", "memory:mem.map(m=>m.text),skills:skills.map(s=>s.text),lang}"),
    ("kget('kv','skills')", "mem=(await kget('kv','mem'))||[];", "mem=(await kget('kv','mem'))||[];skills=(await kget('kv','skills'))||[];"),
    ("const phoneToken", "async function clientTool(ev){\n", TOKEN_JS + "async function clientTool(ev){\n"),
    ("ev.name==='phone_task'", "  if(ev.name==='device_action')", PHONE_TOOL + "  if(ev.name==='device_action')"),
    ("sh.textContent='Skills", "  d.classList.add('open');\n}\n$('menu')", SKILLS_UI + "  d.classList.add('open');\n}\n$('menu')"),
])
