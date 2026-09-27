"""Execute selected existing functions against synthetic inputs, without touching production data."""
import ast, contextlib, datetime as dt, io, json, os, pathlib, shutil, subprocess, sys, tempfile, types
# 这个文件在 test/ 下（2026-09-25 从 docs/audit-2026-09-20/ 迁来）：它是**验收探针**，不是文档。
ROOT=pathlib.Path(__file__).resolve().parents[1]      # 仓库根（本文件在 <仓库>/test/ 下）
# A55（2026-09-27）：原来写成 parents[2] 且到处找 `pipeline/scripts/`（A34 之后脚本已直接在
#   `pipeline/` 下、也没有 scripts/ 这一层）⇒ 这个验收探针从 A34 起就没跑起来过。
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
TOOLS=ROOT/'agent'/'tools'      # A58：工具箱在 agent/tools/（A34 起）
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
        decrypt_rc=function(CI/'wx_decrypt3.py','main',env)()
    except SystemExit as e:
        decrypt_rc=e.code
    record('P01_decrypt_all_missing_fails',True,isinstance(decrypt_rc,int) and decrypt_rc!=0)
    import time
    stale=OUT/'fixtures/stale.txt';stale.parent.mkdir(parents=True,exist_ok=True);stale.write_text('old output\n',encoding='utf-8');os.utime(stale,(1,1))
    env=dict(time=time,os=os,HERE=str(OUT),SCRIPTS=str(OUT),subprocess=types.SimpleNamespace(run=lambda *a,**k:types.SimpleNamespace(returncode=0,stdout=''),TimeoutExpired=subprocess.TimeoutExpired))
    res=function(CI/'daily_prep.py','run',env)('synthetic-noop',['test'],[str(stale)])
    record('P02_stale_artifact_rejected',True,res['status']!='ok')
    # Current orchestrator with every external step mocked failed: its process-success result remains None.
    tmp=OUT/'fixtures/daily';tmp.mkdir(parents=True,exist_ok=True)
    env=dict(sys=types.SimpleNamespace(argv=['daily_prep.py','2026-09-20']),dt=dt,TZ=dt.timezone(dt.timedelta(hours=8)),os=os,HERE=str(tmp),SCRIPTS=str(tmp),VENV_PY='python',NT_UTIL='export.py',WX_KEY='synthetic',QQ_KEY='synthetic',QQ_SRC='synthetic',run=lambda label,*a,**k:dict(step=label,status='FAILED',seconds=0,notes=[]),img_key_note=lambda _:[],check_url_coverage=lambda _:('CHECK-FAILED',[]),day_window=lambda _:(0,'?','?'),wx_login_line=lambda :'synthetic',MAIN_GROUP='synthetic',QQ_STALE_DAYS=3.0,qq_source_state=lambda:(0.1,'synthetic'),mark_qq_stale=lambda *a,**k:False)
    rc=function(CI/'daily_prep.py','main',env)()
    record('P03_all_steps_fail_nonzero_exit',True,isinstance(rc,int) and rc!=0)
    # Export unknown ids against a synthetic existing deliverable.
    tmp=OUT/'fixtures/export';target=tmp/'output/daily/2026-09-20/items.json';target.parent.mkdir(parents=True,exist_ok=True);target.write_text('[{"id":"preserve"}]',encoding='utf-8')
    import argparse
    env=dict(argparse=argparse,os=os,io=io,json=json,HERE=str(tmp),FIELDS=('id','text'),cf_api=types.SimpleNamespace(call=lambda *a:(200,'{"items":[]}')))
    function(TOOLS/'export_day_items.py','main',env)(['2026-09-20','unknown-id'])
    record('P04_missing_ids_preserve_delivery',[{'id':'preserve'}],json.loads(target.read_text(encoding='utf-8')))
    # Fixture containing a QQ group message and private message plus an empty WX contact db.
    # A59（2026-09-27）：按**新布局**隔离 —— 在临时目录里造一棵 mini 包：
    #   <tmp>/pipeline/ 放脚本（脚本的 pkg_dir() 由自身位置算出）、<tmp>/agent/ 当工作区，
    #   再用 DSH_CHAT_FEED_LOCAL 指临时私人 profile。夹具只写临时目录，不碰真实 profile。
    import shutil, sqlite3
    tmp=OUT/'fixtures/extract';mini=tmp/'mini'
    (mini/'pipeline').mkdir(parents=True,exist_ok=True)
    (mini/'agent').mkdir(parents=True,exist_ok=True)
    prof=tmp/'profile';prof.mkdir(parents=True,exist_ok=True)
    (prof/'pipeline.yaml').write_text(
        "wx_account_dir: 'x'\nwx_msg_glob: 'x'\nwx_key_dir: 'x'\nself_wxid: 'test'\n"
        "wx_key: 'synthetic'\nmain_group: 'test'\nqq_data_dir: 'x'\nself_qq: 'test'\n"
        "qq_key: 'synthetic'\ngroups:\n  - 'test'\n", encoding='utf-8')
    for f in ('extract_day.py','pconf.py'):
        shutil.copy2(CI/f, mini/'pipeline'/f)
    (mini/'pipeline'/'extract_window.py').write_text(
        'decode_wx_content=lambda a,b:a\nwx_text_summary=lambda a:a\nwx_type_label=lambda a:str(a)\nqq_content_summary=lambda a,b:a\n',
        encoding='utf-8')
    wx=mini/'agent/output/wx';wx.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(wx/'contact_plain.db');db.execute('CREATE TABLE IF NOT EXISTS contact(username,remark,nick_name)');db.close()
    qq=mini/'agent/output/qq';qq.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(qq/'nt_msg_export.db')
    for t in ['group_messages','c2c_messages']:
        db.execute('CREATE TABLE IF NOT EXISTS '+t+'(group_id,timestamp,sender_qq,msg_type,content_type,text,content)');db.execute('DELETE FROM '+t)
        db.execute('INSERT INTO '+t+' VALUES(?,?,?,?,?,?,?)',('test',1789833600,'test',1,1,'synthetic','{}'))
    db.commit();db.close()
    env2=dict(os.environ);env2['DSH_CHAT_FEED_LOCAL']=str(prof)
    run=subprocess.run([sys.executable,str(mini/'pipeline/extract_day.py'),'2026-09-20'],capture_output=True,env=env2)
    out=(mini/'agent/output/days/2026-09-20.jsonl')
    lines=out.read_text(encoding='utf-8').splitlines() if out.is_file() else []
    record('P05_qq_group_and_private_extracted',2,len(lines))
    src=OUT/'fixtures/source.db';dst=OUT/'fixtures/clear.db'
    src.write_bytes(b'H'*1024+b'new-content');dst.write_bytes(b'old-content')
    env=dict(HEADER_SIZE=1024,pathlib=pathlib)
    function(CI/'qq_decrypt_hex.py','strip_header',env)(src,dst)
    record('P06_same_size_qq_cache_refreshed',True,dst.read_bytes()==b'new-content')
    # A62（2026-09-27 用户定案）：**QQ 源库陈旧/缺失不许再报 ok**。
    #   实测 2026-09-19~09-26 连续 8 天 QQ 0 条，而「2-QQ解密+导出」「2b-QQ结构化导出」
    #   两步每天报 `ok` —— 这条支线断了 8 天，报告里一个字都没有。判据：源库 mtime。
    env=dict(QQ_STALE_DAYS=3.0)
    mark=function(CI/'daily_prep.py','mark_qq_stale',env)
    def _steps():
        return [dict(step='1-微信DB解密',status='ok',notes=[]),
                dict(step='2-QQ解密+导出',status='ok',notes=[]),
                dict(step='2b-QQ结构化导出',status='ok',notes=[])]
    s_stale=_steps(); hit=mark(s_stale,9.6,'源库已 9.6 天没更新')
    s_fresh=_steps(); miss=mark(s_fresh,0.1,'刚更新过')
    s_gone=_steps(); gone=mark(s_gone,None,'源库不存在')
    record('P07_stale_qq_source_marks_steps',
           {'stale':True,'qq':'stale(9.6天未更新)','wx_untouched':'ok','fresh':False,'missing':'stale(缺源库)'},
           {'stale':hit,'qq':s_stale[1]['status'],'wx_untouched':s_stale[0]['status'],
            'fresh':miss,'missing':s_gone[1]['status']})
(OUT/'pipeline-behavior-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False,indent=2))
