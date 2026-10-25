import base64
import ctypes
import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request

DEFAULTS = {'protocol': 'chat', 'endpoint': 'https://api.openai.com/v1', 'model': '',
            'role_models': {}, 'timeout': 120, 'max_tokens': 6000,
            'input_price': None, 'output_price': None}

def protect(secret, decrypt=False):
    """Windows user-bound DPAPI; never store an unencrypted fallback."""
    if os.name != 'nt':
        raise ValueError('本版本密钥保存需要 Windows DPAPI')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    raw = base64.b64decode(secret) if decrypt else secret.encode('utf-8')
    buf = ctypes.create_string_buffer(raw)
    src = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    dst = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(src), None, None, None, None, 1, ctypes.byref(dst)):
        raise ValueError('Windows 无法解密/保存密钥，请在当前账户重新填写')
    try:
        result = ctypes.string_at(dst.data, dst.size)
        return result.decode('utf-8') if decrypt else base64.b64encode(result).decode('ascii')
    finally:
        ctypes.windll.kernel32.LocalFree(dst.data)

def validate_settings(value):
    result = dict(DEFAULTS)
    result.update({k: value[k] for k in DEFAULTS if k in value})
    if result['protocol'] not in ('chat', 'responses', 'anthropic'):
        raise ValueError('未知 API 协议')
    url = urllib.parse.urlsplit(result['endpoint'])
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('接口地址必须是 http(s) URL，不含密钥、查询或账号')
    result['endpoint'] = result['endpoint'].rstrip('/')
    result['timeout'] = max(5, min(300, int(result['timeout'])))
    result['max_tokens'] = max(256, min(64000, int(result['max_tokens'])))
    result['model'] = str(result['model']).strip()[:200]
    if not isinstance(result['role_models'], dict):
        raise ValueError('角色模型格式错误')
    result['role_models'] = {k: str(v).strip()[:200] for k, v in result['role_models'].items() if k in ('planner','coder','writer','reviewer')}
    for key in ('input_price', 'output_price'):
        v = result[key]
        result[key] = None if v in ('', None) else float(v)
        if result[key] is not None and (not math.isfinite(result[key]) or result[key] < 0):
            raise ValueError('单价必须是非负有限数字')
    return result

def call(settings, key, system, prompt, role='writer'):
    protocol = settings['protocol']
    model = settings.get('role_models', {}).get(role) or settings['model']
    if not model:
        raise ValueError('请先在 API 设置里填写模型名称')
    suffix = {'chat': '/chat/completions', 'responses': '/responses', 'anthropic': '/messages'}[protocol]
    endpoint = settings['endpoint'].rstrip('/')
    if not endpoint.endswith(suffix):
        endpoint += suffix
    headers = {'Content-Type': 'application/json', 'User-Agent': 'ResearchDesk/0.1'}
    if protocol == 'anthropic':
        headers.update({'x-api-key': key, 'anthropic-version': '2023-06-01'})
        body = {'model': model, 'system': system, 'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': settings['max_tokens']}
    elif protocol == 'responses':
        if key: headers['Authorization'] = 'Bearer ' + key
        body = {'model': model, 'instructions': system, 'input': prompt, 'max_output_tokens': settings['max_tokens'], 'store': False}
    else:
        if key: headers['Authorization'] = 'Bearer ' + key
        body = {'model': model, 'messages': [{'role': 'system','content': system}, {'role': 'user', 'content': prompt}], 'max_tokens': settings['max_tokens']}
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError('API 返回重定向，请设置最终接口地址（避免密钥转发）')
    req = urllib.request.Request(endpoint, json.dumps(body).encode(), headers, method='POST')
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=settings['timeout']) as response:
            raw = response.read(8_000_001)
        if len(raw) > 8_000_000: raise ValueError('API 回复超过 8 MB')
        data = json.loads(raw)
    except urllib.error.HTTPError as exc:
        # Never include server error text: some gateways echo authorization headers.
        raise ValueError(f'API HTTP {exc.code}；检查协议、最终接口地址、模型与额度') from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ValueError('API 网络连接失败或超时；检查地址与网络') from None
    usage = data.get('usage') or {}
    if protocol == 'chat':
        choice = data['choices'][0]
        if choice.get('finish_reason') == 'length': raise ValueError('输出达到 token 上限，请调高输出上限后重试')
        content = choice['message']['content']
        if isinstance(content, list): content = ''.join(x.get('text', '') for x in content)
        incoming, outgoing = usage.get('prompt_tokens'), usage.get('completion_tokens')
    elif protocol == 'responses':
        if data.get('status') in ('incomplete', 'failed'): raise ValueError('Responses 回复未完成，请调整参数后重试')
        content = ''.join(c.get('text', '') for item in data.get('output', []) if item.get('type') == 'message' for c in item.get('content', []) if c.get('type') == 'output_text')
        incoming, outgoing = usage.get('input_tokens'), usage.get('output_tokens')
    else:
        if data.get('stop_reason') == 'max_tokens': raise ValueError('输出达到 token 上限，请调高后重试')
        content = ''.join(x.get('text', '') for x in data.get('content', []) if x.get('type') == 'text')
        incoming, outgoing = usage.get('input_tokens'), usage.get('output_tokens')
    if not content: raise ValueError('API 未返回文本内容')
    cost = None
    if incoming is not None and outgoing is not None and settings.get('input_price') is not None and settings.get('output_price') is not None:
        cost = (incoming * settings['input_price'] + outgoing * settings['output_price']) / 1_000_000
    return content, {'model': model, 'protocol': protocol, 'input_tokens': incoming, 'output_tokens': outgoing, 'estimated_cost': cost}
