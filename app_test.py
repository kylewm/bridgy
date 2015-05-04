"""Unit tests for app.py.
"""

import app
import testutil
import mf2py


class AppTest(testutil.ModelsTest):

  def test_poll_now(self):
    self.assertEqual([], self.taskqueue_stub.GetTasks('poll'))

    key = self.sources[0].key.urlsafe()
    resp = app.application.get_response('/poll-now', method='POST', body='key=' + key)
    self.assertEquals(302, resp.status_int)
    self.assertEquals(self.sources[0].bridgy_url(self.handler),
                      resp.headers['Location'].split('#')[0])
    params = testutil.get_task_params(self.taskqueue_stub.GetTasks('poll-now')[0])
    self.assertEqual(key, params['source_key'])

  def test_retry_response(self):
    self.assertEqual([], self.taskqueue_stub.GetTasks('propagate'))

    self.responses[0].put()
    key = self.responses[0].key.urlsafe()
    resp = app.application.get_response(
      '/retry', method='POST', body='key=' + key)
    self.assertEquals(302, resp.status_int)
    self.assertEquals(self.sources[0].bridgy_url(self.handler),
                      resp.headers['Location'].split('#')[0])
    params = testutil.get_task_params(self.taskqueue_stub.GetTasks('propagate')[0])
    self.assertEqual(key, params['response_key'])

  def test_poll_now_and_retry_response_missing_key(self):
    for endpoint in '/poll-now', '/retry':
      for body in '', 'key=' + self.responses[0].key.urlsafe():  # hasn't been stored
        resp = app.application.get_response(endpoint, method='POST', body=body)
        self.assertEquals(400, resp.status_int)

  def test_user_page(self):
    resp = app.application.get_response(self.sources[0].bridgy_path())
    self.assertEquals(200, resp.status_int)

  def test_user_page_with_no_features_404s(self):
    self.sources[0].features = []
    self.sources[0].put()

    resp = app.application.get_response(self.sources[0].bridgy_path())
    self.assertEquals(404, resp.status_int)

  def test_user_page_mf2(self):
    """parsing the user page with mf2 gives some informative fields
    about the user and their Bridgy account status.
    """
    user_url = self.sources[0].bridgy_path()
    resp = app.application.get_response(user_url)
    self.assertEquals(200, resp.status_int)
    parsed = mf2py.Parser(url=user_url, doc=resp.body).to_dict()
    hcard = parsed.get('items', [])[0]
    self.assertEquals(['h-card'], hcard['type'])
    self.assertEquals(
      ['fake'], hcard['properties'].get('name'))
    self.assertEquals(
      ['http://fa.ke/profile/url'], hcard['properties'].get('url'))
    self.assertEquals(
      ['enabled'], hcard['properties'].get('bridgy-account-status'))
    self.assertEquals(
      ['enabled'], hcard['properties'].get('bridgy-listen-status'))
    self.assertEquals(
      ['disabled'], hcard['properties'].get('bridgy-publish-status'))
