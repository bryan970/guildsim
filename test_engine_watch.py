import io,json,os,textwrap,unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT=textwrap.dedent((Path(__file__).parent/'.github/workflows/engine-release-watch.yml').read_text().split('        run: |\n',1)[1])
class EngineWatchTests(unittest.TestCase):
    def run_watch(self,latest,issues):
        calls=[]
        def open_url(request,timeout):
            calls.append((request.method,request.full_url,json.loads(request.data) if request.data else None))
            if '/contents/' in request.full_url:
                import base64
                data={'content':base64.b64encode(b"ENGINE_VERSION = 'v1.0.5'").decode()}
            elif '/releases/latest' in request.full_url:data={'tag_name':latest}
            elif request.method=='GET':data=issues
            else:data={}
            return io.BytesIO(json.dumps(data).encode())
        with patch.dict(os.environ,{'GH_TOKEN':'fixture-token','REPOSITORY':'example/guildsim'}),patch('urllib.request.urlopen',side_effect=open_url):
            exec(compile(SCRIPT,'engine-release-watch.yml','exec'),{})
        return calls
    def test_current_engine_does_not_open_issue(self):
        self.assertTrue(all(method=='GET' for method,_,_ in self.run_watch('v1.0.5',[])))
    def test_new_release_creates_single_actionable_issue(self):
        writes=[r for r in self.run_watch('v1.0.6',[]) if r[0]!='GET']
        self.assertEqual(len(writes),1);self.assertEqual(writes[0][0],'POST');self.assertIn('v1.0.6',writes[0][2]['body'])
    def test_existing_issue_is_updated_and_current_pin_closes_it(self):
        issue={'title':'WoWSims engine update available','number':3,'body':'old'}
        self.assertEqual(self.run_watch('v1.0.6',[issue])[-1][0],'PATCH')
        self.assertEqual(self.run_watch('v1.0.5',[issue])[-1][2],{'state':'closed'})
