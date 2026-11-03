"""Trusted local HTML viewer; the browser never receives the interactive PDF."""

import html
import json
import uuid
from fastapi.responses import HTMLResponse


def passive_viewer(doc_id, title, pages):
    nonce = uuid.uuid4().hex
    content = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>教材原页安全预览</title>
<style nonce="NONCE">body{margin:0;background:#eef2ed;color:#294738;font:14px system-ui}header{position:sticky;top:0;background:#fff;padding:14px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}h1{font-size:15px;margin:0}button,input{font:inherit;padding:6px}input{width:70px}main{text-align:center;padding:16px}img{max-width:100%;background:white}p{font-size:12px}</style>
<header><h1>TITLE</h1><button id="prev">上一页</button><label>PDF页码 <input id="page" type="number" min="1"></label><button id="jump">跳转</button><span id="count"></span><button id="next">下一页</button><p>仅展示本机渲染原页；表单、注释交互和自动定位不执行。原PDF文件未修改。</p></header>
<main><p id="status" role="status"></p><img id="image" alt="原PDF页面"></main>
<script nonce="NONCE">
const total=PAGES, documentId=DOCID;
const input=document.getElementById('page'),image=document.getElementById('image'),status=document.getElementById('status');
function current(){const n=Number((location.hash.match(/^#page=(\\d+)$/)||[])[1])||1;return Math.max(1,Math.min(total,n));}
function show(){const n=current();input.value=n;input.max=total;document.getElementById('count').textContent='/ '+total;status.textContent='正在本机渲染 PDF 第'+n+'页…';image.alt='原PDF第'+n+'页（安全渲染）';image.src='/api/library/documents/'+documentId+'/pages/'+n+'/image';document.getElementById('prev').disabled=n<=1;document.getElementById('next').disabled=n>=total;}
function go(n){location.hash='page='+Math.max(1,Math.min(total,Number(n)||1));}
image.onload=()=>{status.textContent='PDF 第'+current()+'页；印刷页码需另行核对。';};image.onerror=()=>{status.textContent='原页渲染失败，请返回知识库查看诊断或重试。';};
document.getElementById('prev').onclick=()=>go(current()-1);document.getElementById('next').onclick=()=>go(current()+1);document.getElementById('jump').onclick=()=>go(input.value);window.addEventListener('hashchange',show);show();
</script></html>"""
    # Placeholders are replaced before the escaped user-controlled title, so a title
    # cannot change script constants. Document IDs are validated by the endpoint.
    content = (
        content.replace("PAGES", str(int(pages)))
        .replace("DOCID", json.dumps(doc_id))
        .replace("NONCE", nonce)
        .replace("TITLE", html.escape(title))
    )
    return HTMLResponse(
        content,
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": f"default-src 'none'; img-src 'self'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; connect-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'self'",
            "Referrer-Policy": "no-referrer",
        },
    )
