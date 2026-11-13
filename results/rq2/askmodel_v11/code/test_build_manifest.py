import copy
import unittest
from build_manifest import batch_prefix, select_context, render


OPTION = dict(id='x',name='Example',location='Town',description='Description',price=1,rating=4.5,tags=['a'])


def request():
    return {'messages':[{'role':'system','content':'S'}, {'role':'user','content':'U'},
        {'role':'assistant','content':'before','tool_calls':[{'id':'a'},{'id':'b'}]},
        {'role':'tool','tool_call_id':'a','content':render(OPTION)},
        {'role':'tool','tool_call_id':'b','content':'other detail'},
        {'role':'assistant','content':'FUTURE OUTCOME'}]}


class ManifestTests(unittest.TestCase):
    def test_complete_batch_and_no_future(self):
        p,start,end,ids=batch_prefix(request(),3)
        self.assertEqual((start,end,ids),(3,5,['a','b']))
        self.assertNotIn('FUTURE',str(p))
        self.assertEqual(p[-1]['tool_call_id'],'b')

    def test_incomplete_batch_rejected(self):
        r=request(); del r['messages'][4]
        with self.assertRaises(ValueError): batch_prefix(r,3)

    def test_first_bad_read_not_replaced_by_later(self):
        r=request(); r['messages'][3]['content'] += ' changed'
        epochs={1:dict(sample={'id':'s_base','epoch':1},member='m',sha256='h')}
        ctx,failures=select_context(epochs,OPTION,lambda s:[(r,'logged_request'),(request(),'logged_request')])
        self.assertIsNone(ctx)
        self.assertEqual(failures[0]['reason'],'first_read_differs_from_canonical_listing')

    def test_fixed_epoch_fallback(self):
        bad=request(); bad['messages'][3]['content'] += ' changed'
        epochs={e:dict(sample={'id':'s_base','epoch':e},member=str(e),sha256=str(e)) for e in (1,2,3)}
        ctx,_=select_context(epochs,OPTION,lambda s:[(bad if s['epoch']==1 else request(),'logged_request')])
        self.assertEqual(ctx['epoch'],2)
        self.assertNotIn('FUTURE',str(ctx['messages']))


if __name__=='__main__': unittest.main()
