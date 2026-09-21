import unittest
from curator_bench.costs import stage_cost, branch_cost


class CostTests(unittest.TestCase):
    def stage(self, prompt=2296, output=768, cached=0, writes=2293):
        return {'url': 'https://api.openai.com/v1/chat/completions', 'attempts': [{'response': {
            'model': 'gpt-5.6-terra', 'service_tier': 'default', 'usage': {
                'prompt_tokens': prompt, 'completion_tokens': output,
                'prompt_tokens_details': {'cached_tokens': cached, 'cache_write_tokens': writes}}}}]}

    def test_known_run_and_cache_rates(self):
        self.assertAlmostEqual(stage_cost(self.stage(), 'completion'), .0149545)
        self.assertAlmostEqual(stage_cost(self.stage(100, 10, 50, 20), 'completion'), .00024)

    def test_attempts_and_unknown_usage(self):
        stage = self.stage()
        stage['attempts'] *= 2
        self.assertAlmostEqual(stage_cost(stage, 'completion'), .029909)
        stage['attempts'].append({'response': {}})
        self.assertIsNone(stage_cost(stage, 'completion'))

    def test_jev_and_offline(self):
        jev = {'url': 'https://api.typesafe.ai/v1/systemone', 'attempts': [{'response': {'usage': {'input_tokens': 10028, 'output_tokens': 548}}}]}
        self.assertAlmostEqual(stage_cost(jev, 'jev'), .000421176)
        self.assertIsNone(branch_cost({'completion': self.stage()}, 'without_jev', True)['total'])

    def test_unknown_model_and_invalid_counts(self):
        stage = self.stage()
        stage['attempts'][0]['response']['model'] = 'another-model'
        self.assertIsNone(stage_cost(stage, 'completion'))
        self.assertIsNone(stage_cost(self.stage(10, 10, 20, 0), 'completion'))
        self.assertIsNone(stage_cost(self.stage(200000, 10, 0, 0), 'completion'))
