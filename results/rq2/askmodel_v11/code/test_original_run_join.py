import unittest
from original_run_join import original_run_join, JoinBlocked


class JoinTests(unittest.TestCase):
    def setUp(self):
        self.jobs=[dict(job_id=x,scenario_id='s',option_id=x,setting='history',question='welfare') for x in ('h','safe')]
        self.ctx=[dict(scenario_id='s',option_id=x,run_id='r',epoch=1,prefix_sha256=x*64) for x in ('h','safe')]
        self.roster=[dict(scenario_id='s',option_id=x,context_available=True,benchmark_label=l) for x,l in [('h','harmful'),('safe','safe')]]
        self.rq1=[dict(run_id='r',scenario_id='s',prompt_condition='neutral',variant='base',epoch='1',ordered_option_id='h',outcome='harmful',score_a='0'),
                  dict(run_id='other',scenario_id='s',prompt_condition='ethical',variant='reversed',epoch='2',ordered_option_id='h',outcome='harmful',score_a='2')]

    def test_run_denominator_deduplicates_and_no_broad_inference(self):
        result=original_run_join(self.jobs,self.ctx,self.roster,self.rq1)
        self.assertEqual(result['summary']['history_welfare_contexts'],2)
        self.assertEqual(result['summary']['all_harmful_orders_in_selected_runs'],1)
        self.assertEqual(result['summary']['exact_ordered_harmful_score0_target_contexts'],1)
        self.assertEqual(result['summary']['broader_original_run_count'],2)
        self.assertTrue(all(r['capacity_result'] is None for r in result['exact_history_rows']))

    def test_missing_ordered_target_keeps_run_denominator(self):
        result=original_run_join(self.jobs[1:],self.ctx[1:],self.roster,self.rq1)
        self.assertEqual(result['summary']['all_harmful_orders_in_selected_runs'],1)
        self.assertEqual(result['summary']['exact_ordered_harmful_score0_target_contexts'],0)
        self.assertEqual(result['summary']['harmful_selected_runs_without_ordered_target_context'],['r'])

    def test_listing_and_value_do_not_duplicate(self):
        extra=[dict(self.jobs[0],job_id='listing',setting='listing'),dict(self.jobs[0],job_id='value',question='value')]
        result=original_run_join(self.jobs+extra,self.ctx,self.roster,self.rq1)
        self.assertEqual(result['summary']['history_welfare_contexts'],2)

    def test_mismatched_scenario_blocks(self):
        self.rq1[0]['scenario_id']='wrong'
        with self.assertRaises(JoinBlocked):original_run_join(self.jobs,self.ctx,self.roster,self.rq1)

    def test_duplicate_context_blocks(self):
        with self.assertRaises(JoinBlocked):original_run_join(self.jobs,self.ctx*2,self.roster,self.rq1)


if __name__=='__main__':unittest.main()
