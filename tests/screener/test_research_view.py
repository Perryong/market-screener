import importlib
import json
import re
import unittest


class ResearchViewTest(unittest.TestCase):
    def test_embedded_provider_text_cannot_terminate_script(self):
        self.assertIsNotNone(importlib.util.find_spec('screener.research_view'))
        view=importlib.import_module('screener.research_view')
        snapshot={'version':1,'mode':'live','generated_at':1,'instruments':[
            {'symbol':'BAD','name':'</script><script>alert(1)</script>'}],
            'news':[],'economy':[],'releases':[],'ipos':[],'resources':[]}
        payload={'mode':'live','generated_at':1,'results':[],'trades':[]}
        html=view.render_app(payload,snapshot)
        block=re.search(r'<script id="research-data" type="application/json">(.*?)</script>',html,re.S).group(1)
        self.assertNotIn('</script>',block)
        self.assertEqual(json.loads(block)['instruments'][0]['name'],'</script><script>alert(1)</script>')
        self.assertNotIn('<script>alert(1)</script>',html)

    def test_empty_research_preserves_breakout_evidence(self):
        self.assertIsNotNone(importlib.util.find_spec('screener.research_view'))
        view=importlib.import_module('screener.research_view')
        html=view.render_app({'mode':'live','generated_at':1,'results':[],'trades':[]},None)
        self.assertIn('No research snapshot',html)
        self.assertIn('Breakout',html)
        self.assertIn('Track record',html)


if __name__=='__main__':
    unittest.main()
