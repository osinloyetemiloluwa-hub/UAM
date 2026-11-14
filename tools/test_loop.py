import sys, types, asyncio, json
# minimal stand-ins so phone_agent imports without fastapi/pydantic
fa=types.ModuleType("fastapi"); fa.WebSocket=object; fa.WebSocketDisconnect=Exception; sys.modules["fastapi"]=fa
pd=types.ModuleType("pydantic")
class BaseModel:
    def __init__(s,**k):
        for n,v in type(s).__dict__.get("__annotations__",{}).items(): setattr(s,n,k.get(n, getattr(type(s),n,None)))
pd.BaseModel=BaseModel; sys.modules["pydantic"]=pd
import phone_agent as pa

class FakeWS:  # plays the phone
    def __init__(s): s.sent=[]; s.dev=None
    async def send_json(s,m):
        s.sent.append(m)
        scr={"app":"home","app_name":"Home","width":1080,"height":2340,"keyboard":False,"screenshot":"AAAA",
             "nodes":[{"id":"1","class":"b","text":"Add","cx":100,"cy":200,"box":[0,0,1,1],"clickable":True}]}
        op=m["op"]
        res={"note":"ok","screen":scr} if op=="act" else ({} if op=="task" else scr)
        asyncio.get_running_loop().call_soon(lambda: s.dev.pending[m["id"]].set_result({"kind":"device_result","id":m["id"],"ok":True,"result":res}))

def run(script, stop_on=None):
    it=iter(script); seen={}
    class Comp:
        def create(self,**kw):
            seen["msgs"]=kw["messages"]
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=next(it)))])
    deps={"profiles":{"balanced":["x"]},"provider_by_name":{"x":{"name":"x"}},
          "clients":{"x":types.SimpleNamespace(chat=types.SimpleNamespace(completions=Comp()))},
          "candidate_models":lambda p,v:["m"]}
    ws=FakeWS(); dev=pa.Device(ws); ws.dev=dev; dev.busy=True
    req=pa.TaskReq(token="a"*32,call_id="c",goal="add a note",memory=["likes dark mode"],skills=["be brief"],profile="balanced")
    task=pa.Task("c","a"*32,"add a note")
    asyncio.run(pa._run(deps,dev,task,req))
    return task,ws,seen

t,ws,seen=run(['{"thought":"x","action":"open_app","app":"Notes"}',
               'ok here: {"thought":"y","action":"tap","x":100,"y":200,"label":"Add"}',
               '{"thought":"z","action":"done","summary":"Added the note."}'])
print(t.status,"|",t.summary,"|",t.steps)
ops=[(m["op"],m["params"].get("action") or m["params"].get("event")) for m in ws.sent]; print(ops)
assert t.status=="done" and ops[0]==("task","begin") and ops[-1]==("task","end") and ("act","tap") in ops
sysmsg=seen["msgs"][0]["content"]; assert "likes dark mode" in sysmsg and "be brief" in sysmsg
assert seen["msgs"][1]["content"][1]["type"]=="image_url"

t,ws,_=run(['{"action":"ask","question":"Pay $5?"}']); assert t.status=="ask" and "Pay" in t.summary; print("ask ok")
t,ws,_=run(['{"action":"tap","x":1,"y":1}']*5); assert t.status=="failed" and "stuck" in t.summary; print("stuck guard ok")
t,ws,_=run(['not json','still not json']); assert t.status=="failed"; print("bad json ok:",t.summary)
t,ws,_=run(['{"action":"launch_missiles"}','{"action":"done","summary":"fine"}']); assert t.status=="done"; print("invalid action skipped ok")
print("LOOP TESTS PASSED")
