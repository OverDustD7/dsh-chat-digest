"""Execute selected existing functions against synthetic inputs, without touching production data."""
import ast, contextlib, datetime as dt, io, json, os, pathlib, shutil, subprocess, sys, tempfile, types
# 这个文件在 test/ 下（2026-09-25 从 docs/audit-2026-09-20/ 迁来）：它是**验收探针**，不是文档。
ROOT=pathlib.Path(__file__).resolve().parents[2]      # 仓库根（test -> 包根 -> <工作区>）
HERE=pathlib.Path(__file__).resolve().parent          # test/
# A26（2026-09-25）：**探针不许改被检查的仓库**。原先 OUT 直接指向仓库内的 fixtures/，
#   于是每跑一次验收就在 git 里留下一堆改动（生成时间戳、被重写的 qq 库、__pycache__ 里的 .pyc）
#   ⇒ "仓库 clean" 只在刚提交完那一瞬间成立，谁跑谁脏、还会被误当成"代码被打坏了"。
#   现在把整棵 fixtures 复制到临时目录里跑：**输入照旧、写入全部落在临时目录**。
OUT=pathlib.Path(tempfile.mkdtemp(prefix='cf-pipe-'))
_SRC=HERE/'fixtures'
if _SRC.is_dir():
    shutil.copytree(_SRC, OUT/'fixtures', dirs_exist_ok=True)
CI=ROOT/'pipeline'
sys.stdout.reconfigure(encoding='utf-8')
results=[]
def record(id,expected,actual):results.append(dict(id=id,expected=expected,actual=actual,pass_=expected==actual))
def function(path,name,env):
    tree=ast.parse(path.read_text(encoding='utf-8-sig'))
    node=next(n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec'),env)
    return env[name]
buf=io.StringIO()
with contextlib.redirect_stdout(buf):
    env=dict(sys=types.SimpleNamespace(argv=['x','test-key']),os=os,OUT=str(OUT/'fixtures/decrypt'),DBS=['missing.db'],DBROOT=str(OUT/'fixtures/nonexistent'),WeChatDatabaseDecryptor=lambda _:None)
    try:
        decrypt_rc=function(CI/'scripts/wx_decrypt3.py','main',env)()
    except SystemExit as e:
        decrypt_rc=e.code
    record('P01_decrypt_all_missing_fails',True,isinstance(decrypt_rc,int) and decrypt_rc!=0)
    import time
    stale=OUT/'fixtures/stale.txt';stale.parent.mkdir(parents=True,exist_ok=True);stale.write_text('old output\n',encoding='utf-8');os.utime(stale,(1,1))
    env=dict(time=time,os=os,HERE=str(OUT),SCRIPTS=str(OUT),subprocess=types.SimpleNamespace(run=lambda *a,**k:types.SimpleNamespace(returncode=0,stdout=''),TimeoutExpired=subprocess.TimeoutExpired))
    res=function(CI/'scripts/daily_prep.py','run',env)('synthetic-noop',['test'],[str(stale)])
    record('P02_stale_artifact_rejected',True,res['status']!='ok')
    # Current orchestrator with every external step mocked failed: its process-success result remains None.
    tmp=OUT/'fixtures/daily';tmp.mkdir(parents=True,exist_ok=True)
    env=dict(sys=types.SimpleNamespace(argv=['daily_prep.py','2026-09-20']),dt=dt,TZ=dt.timezone(dt.timedelta(hours=8)),os=os,HERE=str(tmp),SCRIPTS=str(tmp),VENV_PY='python',NT_UTIL='export.py',WX_KEY='synthetic',QQ_KEY='synthetic',QQ_SRC='synthetic',run=lambda label,*a,**k:dict(step=label,status='FAILED',seconds=0,notes=[]),img_key_note=lambda _:[],check_url_coverage=lambda _:('CHECK-FAILED',[]),day_window=lambda _:(0,'?','?'),wx_login_line=lambda :'synthetic')
    rc=function(CI/'scripts/daily_prep.py','main',env)()
    record('P03_all_steps_fail_nonzero_exit',True,isinstance(rc,int) and rc!=0)
    # Export unknown ids against a synthetic existing deliverable.
    tmp=OUT/'fixtures/export';target=tmp/'output/daily/2026-09-20/items.json';target.parent.mkdir(parents=True,exist_ok=True);target.write_text('[{"id":"preserve"}]',encoding='utf-8')
    import argparse
    env=dict(argparse=argparse,os=os,io=io,json=json,HERE=str(tmp),FIELDS=('id','text'),cf_api=types.SimpleNamespace(call=lambda *a:(200,'{"items":[]}')))
    function(CI/'tools/export_day_items.py','main',env)(['2026-09-20','unknown-id'])
    record('P04_missing_ids_preserve_delivery',[{'id':'preserve'}],json.loads(target.read_text(encoding='utf-8')))
    # Fixture containing a QQ group message and private message plus an empty WX contact db.
    import shutil, sqlite3
    tmp=OUT/'fixtures/extract';scripts=tmp/'scripts';scripts.mkdir(parents=True,exist_ok=True)
    shutil.copy2(CI/'scripts/extract_day.py',scripts/'extract_day.py')
    (scripts/'extract_window.py').write_text('decode_wx_content=lambda a,b:a\nwx_text_summary=lambda a:a\nwx_type_label=lambda a:str(a)\nqq_content_summary=lambda a,b:a\n',encoding='utf-8')
    wx=tmp/'output/wx';wx.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(wx/'contact_plain.db');db.execute('CREATE TABLE IF NOT EXISTS contact(username,remark,nick_name)');db.close()
    qq=tmp/'output/qq';qq.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(qq/'nt_msg_export.db')
    for t in ['group_messages','c2c_messages']:
        db.execute('CREATE TABLE IF NOT EXISTS '+t+'(group_id,timestamp,sender_qq,msg_type,content_type,text,content)');db.execute('DELETE FROM '+t)
        db.execute('INSERT INTO '+t+' VALUES(?,?,?,?,?,?,?)',('test',1789833600,'test',1,1,'synthetic','{}'))
    db.commit();db.close()
    run=subprocess.run([sys.executable,str(scripts/'extract_day.py'),'2026-09-20'],capture_output=True)
    lines=(tmp/'output/days/2026-09-20.jsonl').read_text(encoding='utf-8').splitlines() if run.returncode==0 else []
    record('P05_qq_group_and_private_extracted',2,len(lines))
    src=OUT/'fixtures/source.db';dst=OUT/'fixtures/clear.db'
    src.write_bytes(b'H'*1024+b'new-content');dst.write_bytes(b'old-content')
    env=dict(HEADER_SIZE=1024,pathlib=pathlib)
    function(CI/'scripts/qq_decrypt_hex.py','strip_header',env)(src,dst)
    record('P06_same_size_qq_cache_refreshed',True,dst.read_bytes()==b'new-content')
(OUT/'pipeline-behavior-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False,indent=2))
