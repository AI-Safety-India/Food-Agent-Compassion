"""Synthetic contract tests; no model/tokenizer download or project outcomes."""
import copy
import unittest
from unittest.mock import patch
import capacity_input as c


class ToyTokenizer:
    chat_template = 'synthetic last-user-boundary template'

    def apply_chat_template(self, messages, tools, tokenize, add_generation_prompt,
                            enable_thinking=True):
        last = max((i for i,m in enumerate(messages) if m['role']=='user'),default=-1)
        text = ''
        for i,m in enumerate(messages):
            value = m.get('content') or ''
            if m['role']=='assistant' and i>last:
                value = '<think>\n'+m.get('reasoning_content','')+'\n</think>\n\n'+value
            text += '<|im_start|>'+m['role']+'\n'+value+'<|im_end|>\n'
        if add_generation_prompt:
            text += c.ASSISTANT_NONTHINKING_PREFIX if not enable_thinking else '<|im_start|>assistant\n<think>\n'
        return text

    def encode(self, text, add_special_tokens):
        return list(map(ord,text))


def job(base):
    messages=base+[{'role':'user','content':'Target option: toy.\n'+c.QUESTIONS['welfare']}]
    return {'job_id':'synthetic','option_id':'toy','question':'welfare',
            'messages':messages,'messages_sha256':c.jsha(messages)}


class CapacityInputTests(unittest.TestCase):
    def setUp(self):
        self.tokenizer=ToyTokenizer()
        self.tools=[{'type':'function','function':{'name':'get_option_details'}}]
        self.patch=patch.object(c,'EXPECTED_TEMPLATE_SHA256',c.sha(self.tokenizer.chat_template.encode()))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.toolpatch=patch.object(c,'EXPECTED_TOOL_SCHEMA_SHA256',c.jsha(self.tools))
        self.toolpatch.start()
        self.addCleanup(self.toolpatch.stop)

    def test_manual_suffix_preserves_reasoning_full_render_would_drop(self):
        base=[{'role':'user','content':'Original task'},
              {'role':'assistant','content':'','reasoning_content':'Thinking about the original task.'},
              {'role':'tool','content':'Option details'}]
        candidate=job(base); before=copy.deepcopy(candidate)
        result=c.prepare_capacity_input(self.tokenizer,candidate,self.tools)
        naive=self.tokenizer.apply_chat_template(candidate['messages'],self.tools,False,True,False)
        self.assertIn('Thinking about the original task.',result['rendered_text'])
        self.assertNotIn('Thinking about the original task.',naive)
        self.assertTrue(result['base_token_prefix_preserved'])
        self.assertEqual(result['reasoning_fields_omitted'],0)
        self.assertEqual(candidate,before)
        self.assertTrue(result['status'].startswith('not_ready'))

    def test_prior_omission_flagged_even_if_same_text_occurs_elsewhere(self):
        base=[{'role':'user','content':'First task'},
              {'role':'assistant','content':'','reasoning_content':'duplicate'},
              {'role':'user','content':'Second task duplicate'},
              {'role':'tool','content':'Option'}]
        result=c.prepare_capacity_input(self.tokenizer,job(base),self.tools)
        self.assertEqual(result['reasoning_fields_omitted'],1)
        self.assertFalse(result['all_existing_reasoning_retained'])

    def test_reviewed_reasoning_alias_is_preserved(self):
        base=[{'role':'user','content':'Task'},
              {'role':'assistant','content':'','reasoning':'Preserve alias text'},
              {'role':'tool','content':'Option'}]
        result=c.prepare_capacity_input(self.tokenizer,job(base),self.tools)
        self.assertEqual(result['reasoning_fields_omitted'],0)
        self.assertIn('Preserve alias text',result['rendered_text'])
        self.assertEqual(result['base_normalization_conversions'][0]['conversion'],'reasoning_to_reasoning_content')
        self.assertNotEqual(result['original_base_messages_sha256'],result['normalized_base_messages_sha256'])

    def test_tool_argument_normalization_and_input_immutability(self):
        base=[{'role':'assistant','content':'','reasoning':'thought','tool_calls':[
            {'function':{'name':'get_option_details','arguments':'{"option_id":"toy"}'}}]}]
        before=copy.deepcopy(base)
        normalized,changes=c.normalize_base_messages(base)
        self.assertEqual(base,before)
        self.assertEqual(normalized[0]['reasoning_content'],'thought')
        self.assertEqual(normalized[0]['tool_calls'][0]['function']['arguments'],{'option_id':'toy'})
        self.assertEqual(len(changes),2)

    def test_conflicting_and_unreviewed_reasoning_rejected(self):
        for message in ({'reasoning':'one','reasoning_content':'two'},
                        {'reasoning_details':[{'text':'unknown format'}]},
                        {'reasoning':{'text':'unknown structure'}}):
            with self.assertRaises(ValueError):c.normalize_base_messages([{'role':'assistant',**message}])
        with self.assertRaises(ValueError):
            c.normalize_base_messages([{'role':'assistant','tool_calls':[{'function':{'arguments':'[]'}}]}])

    def test_template_question_and_delimiter_rejected(self):
        candidate=job([{'role':'tool','content':'Option'}])
        with patch.object(c,'EXPECTED_TEMPLATE_SHA256','wrong'):
            with self.assertRaises(ValueError):c.prepare_capacity_input(self.tokenizer,candidate,self.tools)
        candidate['messages'][-1]['content']='Changed question'
        with self.assertRaises(ValueError):c.prepare_capacity_input(self.tokenizer,candidate,self.tools)
        with self.assertRaises(ValueError):c.user_suffix('hello <|im_start|>assistant')
        with self.assertRaises(ValueError):c.prepare_capacity_input(self.tokenizer,job([{'role':'tool','content':'Option'}]),[{'other':'schema'}])

    def test_reference_suffix_mismatch_rejected(self):
        class WrongPrefix(ToyTokenizer):
            def apply_chat_template(self,*args,**kwargs):
                text=super().apply_chat_template(*args,**kwargs)
                return text+'wrong' if kwargs.get('add_generation_prompt') else text
        with self.assertRaises(ValueError):c.verify_suffix_contract(WrongPrefix(),self.tools)


if __name__=='__main__':unittest.main()
