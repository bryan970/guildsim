from guild_runtime import runtime_root, usable_faction
"""Read WoW SavedVariables as data. Never execute Lua from a saved file."""
import re

TOKEN = re.compile(r'\s+|--[^\n]*|"(?:\\[\s\S]|[^"\\])*"|\'(?:\\[\s\S]|[^\'\\])*\'|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[A-Za-z_][A-Za-z_0-9]*|[{}\[\]=,;]', re.M)

def unquote(s):
    s = s[1:-1]
    escapes = {'n':'\n','r':'\r','t':'\t','a':'\a','b':'\b','f':'\f','v':'\v','\\':'\\','"':'"',"'":"'"}
    def replace(m):
        v=m.group(1)
        if v.isdigit():
            n=int(v)
            if n>255: raise ValueError('Invalid Lua byte escape')
            return chr(n)
        if v not in escapes: raise ValueError('Unsupported Lua escape: '+v)
        return escapes[v]
    return re.sub(r'\\(\d{1,3}|[\s\S])', replace, s)

def loads(text):
    tokens=[]; end=0
    for m in TOKEN.finditer(text.lstrip('\ufeff')):
        if text.lstrip('\ufeff')[end:m.start()].strip(): raise ValueError('Unsupported SavedVariables syntax')
        end=m.end(); s=m.group()
        if not s.isspace() and not s.startswith('--'): tokens.append(s)
    if text.lstrip('\ufeff')[end:].strip(): raise ValueError('Trailing unsupported syntax')
    pos=0
    def take(expected=None):
        nonlocal pos
        if pos>=len(tokens): raise ValueError('Unexpected end of SavedVariables')
        t=tokens[pos]; pos+=1
        if expected is not None and t!=expected: raise ValueError('Expected '+expected)
        return t
    def value():
        nonlocal pos
        t=take()
        if t=='{':
            result={}; index=1
            while tokens[pos]!='}':
                if tokens[pos]=='[':
                    take('['); key=value(); take(']'); take('='); result[key]=value()
                elif pos+1<len(tokens) and tokens[pos+1]=='=':
                    key=take(); take('='); result[key]=value()
                else:
                    result[index]=value(); index+=1
                if tokens[pos] in (',',';'): take()
                elif tokens[pos]!='}': raise ValueError('Missing field separator')
            take('}'); return result
        if t[0] in ('"',"'"): return unquote(t)
        if t=='true': return True
        if t=='false': return False
        if t=='nil': return None
        if re.fullmatch(r'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?',t): return float(t) if any(c in t for c in '.eE') else int(t)
        raise ValueError('Executable Lua is not allowed: '+t)
    out={}
    while pos<len(tokens):
        name=take(); take('='); out[name]=value()
        if pos<len(tokens) and tokens[pos]==';': take()
    return out

def saved_characters(data):
    """Find documented exporter saved-character entries across AceDB profiles."""
    out=[]
    def visit(obj):
        if not isinstance(obj,dict): return
        if isinstance(obj.get('data'),str) and isinstance(obj.get('timestamp'),(int,float)):
            out.append(obj)
        else:
            for v in obj.values(): visit(v)
    visit(data.get('WSEDB',{}))
    return out
