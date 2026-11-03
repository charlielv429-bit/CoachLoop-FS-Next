"""Run only after configuring backend/.env and starting the backend.
Sends two non-personal teaching questions to the real configured provider.
"""
import json
import urllib.error
import urllib.request

messages=[]
for question in ['左前压步有哪些分解练习？请区分资料依据与教学建议。','我刚才问的是哪个动作？请承接前一轮，说明连续练习时要注意的证据边界。']:
    messages.append({'role':'user','content':question})
    request=urllib.request.Request('http://127.0.0.1:8000/api/chat',data=json.dumps({'messages':messages}).encode(),headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=65) as response:
            answer=json.load(response)
    except urllib.error.HTTPError as error:
        print('验收未完成：',json.load(error).get('detail','请求失败'))
        raise SystemExit(1)
    print('\n问题：',question)
    print('资料依据：',answer['textbook_facts'])
    print('AI建议：',answer['suggestions'])
    print('参考边界：',answer['limitations'])
    for source in answer['citations']:
        print('引用：',source['authors'],source['title'],source['pages'],source['verification_status'])
    messages.append({'role':'assistant','content':'\n'.join([*answer['textbook_facts'],answer['suggestions'],answer['limitations']])})
print('\n两轮真实 API 请求成功。请人工核对中文回答质量、上下文承接、摘要忠实性与书名页码；请求成功不等于教学质量通过。')
