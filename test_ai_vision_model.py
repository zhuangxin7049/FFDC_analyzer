import unittest
from unittest.mock import patch

import app


class AiVisionModelTests(unittest.TestCase):
    def test_default_is_nemotron_vl(self):
        self.assertEqual(app.DEFAULT_VISION_MODEL, 'nemotron-3.5-super-vl')

    def test_vision_payload_uses_nemotron_vl(self):
        response = {'choices': [{'message': {'content': 'image noted'}}]}
        with patch.object(app, 'load_ai_config', return_value=('https://davy.example/v1', 'key', 'model')), \
             patch.object(app, 'post_json', return_value=response) as post:
            answer = app._call_ai_vision_bytes(b'image', 'image/png', 'test.png', 'Describe this.')
        self.assertEqual(answer, 'image noted')
        self.assertEqual(post.call_args.args[2]['model'], 'nemotron-3.5-super-vl')


if __name__ == '__main__':
    unittest.main()
