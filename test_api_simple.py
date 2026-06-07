import requests
import json

BASE_URL = 'http://localhost:8000'

# 测试版本
print('Test 1: Version')
r = requests.get(f'{BASE_URL}/api/version')
print(f'Status: {r.status_code}')
print(f'Version: {r.json()["version"]}')

# 测试模型
print('\nTest 2: Models')
r = requests.get(f'{BASE_URL}/api/models')
data = r.json()
print(f'Status: {r.status_code}')
print(f'Count: {data["count"]}')

# 创建会话
print('\nTest 3: Create Session')
r = requests.post(f'{BASE_URL}/api/sessions', params={'work_dir': 'C:\\Users\\xiaox\\Desktop'})
data = r.json()
session_id = data['session_id']
print(f'Status: {r.status_code}')
print(f'Session: {session_id}')

# 测试对话
print('\nTest 4: Chat')
r = requests.post(f'{BASE_URL}/api/chat', json={'message': '你好', 'session_id': session_id})
data = r.json()
print(f'Status: {r.status_code}')
print(f'Response: {data["response"]}')

# 测试上下文
print('\nTest 5: Context')
r = requests.post(f'{BASE_URL}/api/chat', json={'message': '我叫张三', 'session_id': session_id})
r = requests.post(f'{BASE_URL}/api/chat', json={'message': '我叫什么名字', 'session_id': session_id})
data = r.json()
print(f'Status: {r.status_code}')
print(f'Response: {data["response"]}')

# 测试历史
print('\nTest 6: History')
r = requests.get(f'{BASE_URL}/api/sessions/{session_id}/history')
data = r.json()
print(f'Status: {r.status_code}')
print(f'Count: {data["count"]}')

# 测试流式
print('\nTest 7: Stream Chat')
r = requests.post(f'{BASE_URL}/api/chat/stream', json={'message': '简短介绍Python', 'session_id': session_id}, stream=True)
print('Response: ', end='', flush=True)
for line in r.iter_lines():
    if line:
        line = line.decode('utf-8')
        if line.startswith('data: '):
            data_str = line[6:]
            if data_str == '[DONE]':
                break
            try:
                data = json.loads(data_str)
                if data.get('type') == 'text':
                    print(data['content'], end='', flush=True)
            except:
                pass
print('\n')

print('\nAll tests passed!')
