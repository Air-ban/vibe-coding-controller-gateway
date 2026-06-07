import requests
import json

BASE_URL = 'http://localhost:8000'
session_id = 'cb06fe24-5136-4244-9144-7e8cc0c49207'

# 测试切换模型
print('=== Test Model Switch ===')
r = requests.post(f'{BASE_URL}/api/sessions/{session_id}/model', 
    json={'model': 'deepseek/deepseek-chat'})
print(f'Status: {r.status_code}')
print(r.json())

# 测试查询当前模型
print('\n=== Test Get Current Model ===')
r = requests.get(f'{BASE_URL}/api/sessions/{session_id}/model')
print(f'Status: {r.status_code}')
print(r.json())

# 测试工作目录
print('\n=== Test WorkDir ===')
r = requests.get(f'{BASE_URL}/api/sessions/{session_id}/workdir')
print(f'Status: {r.status_code}')
print(r.json())

# 测试上下文对话
print('\n=== Test Context Chat ===')
r = requests.post(f'{BASE_URL}/api/chat', 
    json={'message': '我叫李四，记住我', 'session_id': session_id})
data = r.json()
print('User: 我叫李四，记住我')
print(f'Assistant: {data["response"]}')

r = requests.post(f'{BASE_URL}/api/chat', 
    json={'message': '我叫什么名字', 'session_id': session_id})
data = r.json()
print('User: 我叫什么名字')
print(f'Assistant: {data["response"]}')

print('\n=== Test History ===')
r = requests.get(f'{BASE_URL}/api/sessions/{session_id}/history')
data = r.json()
print(f'Total messages: {data["count"]}')
for msg in data['history']:
    print(f"{msg['role']}: {msg['content'][:30]}")
